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
from urllib.parse import unquote, urlsplit

from rps_runner.presentation.contract import (
    ProjectionContractError,
    ReplayContractError,
    project_live,
    project_replay,
)
from rps_runner.presentation.resources import (
    ASSET_ROUTES,
    served_presentation_asset_bytes,
)
from rps_runner.tournament.storage import StorageError, load_competition_records


LOGGER = logging.getLogger(__name__)
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


@dataclass(frozen=True)
class ReplayResponse:
    status: HTTPStatus
    body: dict[str, Any]


class ReplayState:
    """Load one committed Match through verified Competition Record storage."""

    def __init__(
        self,
        tournament_directory: Path,
        live_state: LiveProjectionState,
    ):
        self._directory = tournament_directory
        self._live_state = live_state

    def response(self, match_id: str) -> ReplayResponse:
        live_response = self._live_state.response()
        freshness = live_response.body.get("freshness")
        if (
            live_response.status != HTTPStatus.OK
            or not isinstance(freshness, dict)
            or freshness.get("available") is not True
        ):
            return _replay_unavailable()
        tournament = live_response.body.get("tournament")
        if not isinstance(tournament, dict):
            return _replay_unavailable()
        if _completed_match_occurrences(tournament, match_id) != 1:
            return _replay_unavailable()

        try:
            terminal_records = [
                stored.record
                for stored in load_competition_records(self._directory)
                if stored.record.get("type") == "match_terminal"
                and stored.record.get("match_id") == match_id
            ]
            if len(terminal_records) != 1:
                return _replay_unavailable()
            replay = project_replay(terminal_records[0])
        except (OSError, StorageError, ReplayContractError) as error:
            LOGGER.warning("Replay unavailable for Match %s: %s", match_id, error)
            return _replay_unavailable()

        return ReplayResponse(HTTPStatus.OK, {"replay": replay})


class PresentationServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: Type[BaseHTTPRequestHandler],
        state: LiveProjectionState,
        replay_state: ReplayState,
    ):
        self.presentation_state = state
        self.replay_state = replay_state
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
        replay_prefix = "/api/matches/"
        replay_suffix = "/replay"
        if path.startswith(replay_prefix) and path.endswith(replay_suffix):
            encoded_match_id = path[len(replay_prefix) : -len(replay_suffix)]
            try:
                match_id = unquote(encoded_match_id, errors="strict")
            except UnicodeDecodeError:
                match_id = ""
            if match_id and "/" not in match_id:
                self._serve_replay(match_id)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "replay_unavailable"})
            return
        asset = ASSET_ROUTES.get(path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = served_presentation_asset_bytes(asset)
        except (OSError, ValueError):
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", asset.content_type)
        self.send_header("Cache-Control", asset.cache_control)
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

    def _serve_replay(self, match_id: str) -> None:
        response = self.server.replay_state.response(match_id)
        self._send_json(response.status, response.body)

    def _send_json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
        encoded = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
    live_state = LiveProjectionState(directory)
    return server_type(
        (host, port),
        PresentationRequestHandler,
        live_state,
        ReplayState(directory, live_state),
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


def _completed_match_occurrences(
    tournament: dict[str, Any], match_id: str
) -> int:
    occurrences = 0
    phase_fixtures = [tournament.get("fixtures", [])]
    bracket = tournament.get("bracket")
    if isinstance(bracket, dict):
        phase_fixtures.append(bracket.get("fixtures", []))
    for fixtures in phase_fixtures:
        for fixture in fixtures:
            for match in fixture.get("matches", []):
                if match.get("match_id") == match_id:
                    occurrences += 1
    return occurrences


def _replay_unavailable() -> ReplayResponse:
    return ReplayResponse(
        HTTPStatus.NOT_FOUND, {"error": "replay_unavailable"}
    )
