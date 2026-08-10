"""Installed, offline presentation asset resources and integrity checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib import resources
from typing import Mapping


@dataclass(frozen=True)
class PresentationAsset:
    filename: str
    content_type: str
    cache_control: str


ASSET_ROUTES: Mapping[str, PresentationAsset] = {
    "/": PresentationAsset("index.html", "text/html; charset=utf-8", "no-store"),
    "/assets/styles.css": PresentationAsset(
        "styles.css",
        "text/css; charset=utf-8",
        "public, max-age=31536000, immutable",
    ),
    "/assets/app.js": PresentationAsset(
        "app.js",
        "text/javascript; charset=utf-8",
        "public, max-age=31536000, immutable",
    ),
}


def presentation_asset_bytes(filename: str) -> bytes:
    """Read one allowlisted asset from the installed package."""

    if filename not in {asset.filename for asset in ASSET_ROUTES.values()}:
        raise ValueError("Unknown presentation asset: " + filename)
    return (
        resources.files("rps_runner.presentation")
        .joinpath("assets", filename)
        .read_bytes()
    )


def served_presentation_asset_bytes(asset: PresentationAsset) -> bytes:
    """Render the shell with content-addressed URLs; copy other assets exactly."""

    content = presentation_asset_bytes(asset.filename)
    if asset.filename != "index.html":
        return content
    versions = {
        "__STYLES_VERSION__": _asset_version("styles.css"),
        "__APP_VERSION__": _asset_version("app.js"),
    }
    shell = content.decode("utf-8")
    for placeholder, version in versions.items():
        shell = shell.replace(placeholder, version)
    return shell.encode("utf-8")


def _asset_version(filename: str) -> str:
    return hashlib.sha256(presentation_asset_bytes(filename)).hexdigest()[:16]


def verify_presentation_assets() -> dict[str, object]:
    """Verify that every offline browser asset is installed and self-contained."""

    decoded: dict[str, str] = {}
    digest = hashlib.sha256()
    for filename in sorted(asset.filename for asset in ASSET_ROUTES.values()):
        content = presentation_asset_bytes(filename)
        if not content:
            raise ValueError("Installed presentation asset is empty: " + filename)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                "Installed presentation asset is not UTF-8: " + filename
            ) from error
        decoded[filename] = text
        digest.update(filename.encode("utf-8") + b"\0" + content + b"\0")

    shell = decoded["index.html"]
    for required in (
        "/assets/styles.css?v=__STYLES_VERSION__",
        "/assets/app.js?v=__APP_VERSION__",
    ):
        if required not in shell:
            raise ValueError("Presentation shell omits packaged asset " + required)
    combined = "\n".join(decoded.values()).lower()
    if "http://" in combined or "https://" in combined or "//cdn." in combined:
        raise ValueError("Presentation assets include an external network resource")
    return {"identity": "sha256:" + digest.hexdigest(), "assets": decoded}
