"""Standard-library HTTP server for live Tournament presentation."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import socket
import threading
from typing import Any, Optional, TextIO, Type
from urllib.parse import urlsplit

from rps_runner.presentation.contract import ProjectionContractError, project_live


LOGGER = logging.getLogger(__name__)
_ASSET_DIRECTORY = Path(__file__).with_name("assets")
_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8", "no-store"),
    "/assets/styles.css": (
        "styles.css",
        "text/css; charset=utf-8",
        "public, max-age=3600, immutable",
    ),
    "/assets/app.js": (
        "app.js",
        "text/javascript; charset=utf-8",
        "public, max-age=3600, immutable",
    ),
}


@dataclass(frozen=True)
class LiveResponse:
    status: HTTPStatus
    body: dict[str, Any]
    etag: Optional[str]


class LiveProjectionState:
    """Read complete projection generations and retain the last valid one."""

    def __init__(self, tournament_directory: Path):
        self._path = tournament_directory / "scoreboard.json"
        self._last_valid: Optional[dict[str, Any]] = None
        self._lock = threading.Lock()

    def response(self) -> LiveResponse:
        with self._lock:
            try:
                raw = self._path.read_bytes()
                decoded = json.loads(raw)
                live = project_live(decoded)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ProjectionContractError,
            ) as error:
                LOGGER.warning("Scoreboard Projection unavailable: %s", error)
                if self._last_valid is None:
                    body = {
                        "freshness": {"available": False},
                        "error": "presentation_data_unavailable",
                    }
                    return LiveResponse(
                        HTTPStatus.SERVICE_UNAVAILABLE, body, None
                    )
                body = {
                    "tournament": self._last_valid,
                    "freshness": {"available": False},
                }
                return LiveResponse(HTTPStatus.OK, body, _etag(body))
            self._last_valid = live
            body = {
                "tournament": live,
                "freshness": {"available": True},
            }
            return LiveResponse(HTTPStatus.OK, body, _etag(body))


class PresentationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: Type[BaseHTTPRequestHandler],
        state: LiveProjectionState,
    ):
        self.presentation_state = state
        super().__init__(server_address, handler)


class _IPv6PresentationServer(PresentationServer):
    address_family = socket.AF_INET6


class PresentationRequestHandler(BaseHTTPRequestHandler):
    server: PresentationServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/live":
            self._serve_live()
            return
        asset = _ASSETS.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type, cache_control = asset
        try:
            content = (_ASSET_DIRECTORY / filename).read_bytes()
        except OSError:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_live(self) -> None:
        response = self.server.presentation_state.response()
        if (
            response.status == HTTPStatus.OK
            and response.etag is not None
            and self.headers.get("If-None-Match") == response.etag
        ):
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", response.etag)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        encoded = _json_bytes(response.body)
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if response.etag is not None:
            self.send_header("ETag", response.etag)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("Presentation HTTP: " + format, *args)


def create_server(
    tournament_directory: Path, host: str, port: int
) -> PresentationServer:
    """Validate and bind a presentation server without serving requests yet."""

    directory = validate_tournament_directory(tournament_directory)
    family = validate_loopback_host(host)
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError("Presentation port must be between 0 and 65535")
    server_type: Type[PresentationServer] = (
        _IPv6PresentationServer if family == socket.AF_INET6 else PresentationServer
    )
    return server_type(
        (host, port), PresentationRequestHandler, LiveProjectionState(directory)
    )


def serve_presentation(
    directory: Path, host: str, port: int, output: TextIO
) -> None:
    """Bind, print the browser URL, and serve until interrupted."""

    server = create_server(directory, host, port)
    try:
        bound_host, bound_port = server.server_address[:2]
        url_host = f"[{bound_host}]" if ":" in str(bound_host) else str(bound_host)
        print(f"http://{url_host}:{bound_port}/", file=output, flush=True)
        server.serve_forever()
    finally:
        server.server_close()


def validate_tournament_directory(directory: Path) -> Path:
    resolved = directory.expanduser().resolve()
    if (
        not resolved.is_dir()
        or not os.access(str(resolved), os.R_OK | os.X_OK)
    ):
        raise ValueError(f"Not a readable Tournament directory: {resolved}")
    try:
        next(resolved.iterdir(), None)
    except OSError as error:
        raise ValueError(
            f"Not a readable Tournament directory: {resolved}"
        ) from error
    return resolved


def validate_loopback_host(host: str) -> socket.AddressFamily:
    try:
        addresses = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ValueError(f"Invalid presentation bind address: {host}") from error
    families: list[socket.AddressFamily] = []
    for family, _kind, _protocol, _canonical, address in addresses:
        try:
            loopback = ipaddress.ip_address(address[0]).is_loopback
        except ValueError as error:
            raise ValueError(f"Invalid presentation bind address: {host}") from error
        if not loopback:
            raise ValueError("Presentation bind address must be loopback")
        families.append(family)
    if not families:
        raise ValueError(f"Invalid presentation bind address: {host}")
    return socket.AF_INET6 if families[0] == socket.AF_INET6 else socket.AF_INET


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _etag(value: Any) -> str:
    digest = hashlib.sha256(_json_bytes(value)).hexdigest()
    return f'"{digest}"'
