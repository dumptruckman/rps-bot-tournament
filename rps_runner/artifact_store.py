from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


ARTIFACT_SET_INDEX_FORMAT_VERSION = "artifact-set-index-v1"
ARCHIVE_FORMAT = "docker-image-archive-v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLATFORM = re.compile(r"^linux/(amd64|arm64)$")


class ArtifactStoreIntegrityError(ValueError):
    """A durable Bot Artifact set failed closed on an integrity condition."""


@dataclass(frozen=True)
class ArtifactSelection:
    candidate: Path
    certification: Path


@dataclass(frozen=True)
class ArtifactIdentity:
    artifact_digest: str
    source_digest: str
    platform: str
    validation_identity: str
    image_id: str


def _read_object(path: Path, description: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactStoreIntegrityError(
            description + " is missing or not a regular file"
        )
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactStoreIntegrityError(
            description + " is corrupt or unreadable: " + str(error)
        )
    if not isinstance(value, dict):
        raise ArtifactStoreIntegrityError(description + " must be a JSON object")
    return value


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ArtifactStoreIntegrityError(field + " must be an immutable sha256 digest")
    return value


def _require_platform(value: object, field: str) -> str:
    if not isinstance(value, str) or _PLATFORM.fullmatch(value) is None:
        raise ArtifactStoreIntegrityError(
            field + " must be 'linux/amd64' or 'linux/arm64'"
        )
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ArtifactStoreIntegrityError(field + " must be an object")
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except OSError as error:
        raise ArtifactStoreIntegrityError(
            "could not hash retained file " + str(path) + ": " + str(error)
        )
    return "sha256:" + digest.hexdigest()


def _artifact_set_index_identity(value: Mapping[str, Any]) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return ARTIFACT_SET_INDEX_FORMAT_VERSION + "@sha256:" + hashlib.sha256(
        content
    ).hexdigest()


def _inspect_image(
    image_id: str, platform: str, *, allow_missing: bool = False
) -> bool:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", image_id],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactStoreIntegrityError(
            "could not inspect selected image " + image_id + ": " + str(error)
        )
    diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
    if completed.returncode != 0:
        missing = (
            "no such image" in diagnostics.lower()
            or "no such object" in diagnostics.lower()
        )
        if allow_missing and missing:
            return False
        raise ArtifactStoreIntegrityError(
            "could not verify selected image in the active Docker context: "
            + image_id
            + (": " + diagnostics if diagnostics else "")
        )
    try:
        details = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactStoreIntegrityError(
            "Docker returned corrupt image inspection for "
            + image_id
            + ": "
            + str(error)
        )
    if (
        not isinstance(details, list)
        or len(details) != 1
        or not isinstance(details[0], dict)
    ):
        raise ArtifactStoreIntegrityError(
            "Docker image inspection did not resolve exactly one selected image"
        )
    observed = details[0]
    if observed.get("Id") != image_id:
        raise ArtifactStoreIntegrityError(
            "digest mismatch for selected image: expected "
            + image_id
            + ", observed "
            + repr(observed.get("Id"))
        )
    observed_platform = str(observed.get("Os", "")) + "/" + str(
        observed.get("Architecture", "")
    )
    if observed_platform != platform:
        raise ArtifactStoreIntegrityError(
            "wrong platform for selected image "
            + image_id
            + ": expected "
            + platform
            + ", observed "
            + observed_platform
        )
    return True


def _artifact_identity_from_documents(
    source_bundle: Mapping[str, Any],
    artifact: Mapping[str, Any],
    report: Mapping[str, Any],
) -> ArtifactIdentity:
    if (
        artifact.get("bot_artifact_manifest_format_version")
        != "bot-artifact-manifest-v1"
    ):
        raise ArtifactStoreIntegrityError("Bot Artifact Manifest format is unsupported")
    if report.get("validation_report_format_version") != "validation-report-v1":
        raise ArtifactStoreIntegrityError("validation report format is unsupported")
    if artifact.get("status") != "validated" or report.get("status") != "passed":
        raise ArtifactStoreIntegrityError("Bot Artifact validation has not passed")
    artifact_digest = _require_digest(
        artifact.get("artifact_digest"), "artifact_digest"
    )
    source_digest = _require_digest(artifact.get("source_digest"), "source_digest")
    platform = _require_platform(artifact.get("platform"), "platform")
    validation_identity = artifact.get("validation_identity")
    if not isinstance(validation_identity, str) or not validation_identity:
        raise ArtifactStoreIntegrityError("validation identity is missing")
    image = _mapping(artifact.get("image"), "image")
    retention = _mapping(artifact.get("retention"), "retention")
    image_id = _require_digest(image.get("local_image_id"), "image.local_image_id")
    comparisons = (
        (source_bundle.get("source_digest"), source_digest, "frozen source digest"),
        (report.get("platform"), platform, "validation report platform"),
        (
            report.get("validation_identity"),
            validation_identity,
            "validation report identity",
        ),
        (image.get("manifest_digest"), artifact_digest, "image manifest digest"),
        (retention.get("authority"), artifact_digest, "retention authority"),
        (retention.get("local_image_id"), image_id, "retention image ID"),
    )
    for observed, expected, description in comparisons:
        if observed != expected:
            raise ArtifactStoreIntegrityError(description + " mismatch")
    return ArtifactIdentity(
        artifact_digest,
        source_digest,
        platform,
        validation_identity,
        image_id,
    )


def _validated_selection(selection: ArtifactSelection) -> ArtifactIdentity:
    if selection.candidate.is_symlink() or not selection.candidate.is_dir():
        raise ArtifactStoreIntegrityError("artifact candidate directory is missing")
    if selection.certification.is_symlink() or not selection.certification.is_dir():
        raise ArtifactStoreIntegrityError("artifact certification directory is missing")
    candidate = _read_object(
        selection.candidate / "artifact-candidate.json", "artifact candidate manifest"
    )
    source_bundle = _read_object(
        selection.candidate / "source-bundle.json", "frozen source bundle manifest"
    )
    artifact = _read_object(
        selection.certification / "bot-artifact-manifest.json", "Bot Artifact Manifest"
    )
    report = _read_object(
        selection.certification / "validation-report.json", "validation report"
    )
    if candidate.get("artifact_candidate_format_version") != "artifact-candidate-v1":
        raise ArtifactStoreIntegrityError(
            "artifact candidate manifest format is unsupported"
        )
    identity = _artifact_identity_from_documents(source_bundle, artifact, report)
    comparisons = (
        (
            candidate.get("artifact_digest"),
            identity.artifact_digest,
            "candidate artifact digest",
        ),
        (
            candidate.get("source_digest"),
            identity.source_digest,
            "candidate source digest",
        ),
        (candidate.get("platform"), identity.platform, "candidate platform"),
    )
    for observed, expected, description in comparisons:
        if observed != expected:
            raise ArtifactStoreIntegrityError(description + " mismatch")
    candidate_image = _mapping(candidate.get("image"), "candidate image")
    if (
        candidate_image.get("manifest_digest") != identity.artifact_digest
        or candidate_image.get("local_image_id") != identity.image_id
    ):
        raise ArtifactStoreIntegrityError("candidate image digest mismatch")
    return identity


def _copy_source(candidate: Path, destination: Path) -> Mapping[str, str]:
    source = candidate / "source"
    if source.is_symlink() or not source.is_dir():
        raise ArtifactStoreIntegrityError("frozen source directory is missing")
    destination.mkdir()
    digests: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ArtifactStoreIntegrityError(
                "frozen source contains a symlink: " + relative.as_posix()
            )
        output = destination / relative
        if path.is_dir():
            output.mkdir()
        elif path.is_file():
            output.write_bytes(path.read_bytes())
            retained_path = (PurePosixPath("source") / relative).as_posix()
            digests[retained_path] = _file_digest(output)
        else:
            raise ArtifactStoreIntegrityError(
                "frozen source contains a non-regular path: " + relative.as_posix()
            )
    return digests


def _write_artifact(
    staging: Path, selection: ArtifactSelection, identity: ArtifactIdentity
) -> Mapping[str, Any]:
    artifact_key = identity.artifact_digest.split(":", 1)[1]
    relative_root = PurePosixPath("artifacts") / artifact_key
    output = staging / relative_root
    output.mkdir(parents=True)
    files = dict(_copy_source(selection.candidate, output / "source"))
    inputs = {
        "source-bundle.json": selection.candidate / "source-bundle.json",
        "bot-artifact-manifest.json": selection.certification
        / "bot-artifact-manifest.json",
        "validation-report.json": selection.certification / "validation-report.json",
    }
    for name, source in inputs.items():
        target = output / name
        target.write_bytes(source.read_bytes())
        files[name] = _file_digest(target)
    return {
        "artifact_digest": identity.artifact_digest,
        "source_digest": identity.source_digest,
        "platform": identity.platform,
        "validation_identity": identity.validation_identity,
        "image_id": identity.image_id,
        "path": relative_root.as_posix(),
        "files": dict(sorted(files.items())),
    }


def _export_archive(path: Path, image_ids: Sequence[str]) -> None:
    command = ["docker", "image", "save", "--output", str(path), *image_ids]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactStoreIntegrityError(
            "could not export selected images to the durable archive: " + str(error)
        )
    if completed.returncode != 0:
        diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ArtifactStoreIntegrityError(
            "Docker could not export the selected image set"
            + (": " + diagnostics if diagnostics else "")
        )
    if not path.is_file():
        raise ArtifactStoreIntegrityError(
            "Docker did not create the selected image archive"
        )


def _make_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _make_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    root.chmod(0o755)


def preserve_artifact_set(
    store: Path, selections: Sequence[ArtifactSelection]
) -> Mapping[str, Any]:
    """Atomically retain selected Bot Artifacts and one shared Docker archive."""
    if store.exists() or store.is_symlink():
        raise ArtifactStoreIntegrityError(
            "artifact store destination already exists and will not be replaced"
        )
    if not selections:
        raise ArtifactStoreIntegrityError(
            "at least one selected Bot Artifact is required"
        )
    validated = [_validated_selection(selection) for selection in selections]
    artifact_digests = [item.artifact_digest for item in validated]
    if len(set(artifact_digests)) != len(artifact_digests):
        raise ArtifactStoreIntegrityError(
            "selected Bot Artifact digests must be unique"
        )
    for item in validated:
        _inspect_image(item.image_id, item.platform)

    store.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix="rps-artifact-store-", dir=str(store.parent))
    )
    try:
        entries = [
            _write_artifact(staging, selection, details)
            for selection, details in sorted(
                zip(selections, validated),
                key=lambda pair: pair[1].artifact_digest,
            )
        ]
        archive = staging / "images.tar"
        _export_archive(archive, [str(entry["image_id"]) for entry in entries])
        unsigned_index = {
            "artifact_set_index_format_version": ARTIFACT_SET_INDEX_FORMAT_VERSION,
            "artifacts": entries,
            "archive": {
                "format": ARCHIVE_FORMAT,
                "path": "images.tar",
                "digest": _file_digest(archive),
            },
        }
        index = {
            **unsigned_index,
            "integrity": {
                "algorithm": "sha256",
                "index_identity": _artifact_set_index_identity(unsigned_index),
            },
        }
        (staging / "artifact-set-index.json").write_text(
            json.dumps(index, indent=2, sort_keys=True) + "\n"
        )
        _make_read_only(staging)
        os.replace(staging, store)
        return index
    except BaseException:
        _make_writable(staging)
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _safe_store_path(store: Path, relative: object, description: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ArtifactStoreIntegrityError(description + " path is missing")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ArtifactStoreIntegrityError(
            description + " path escapes the artifact store"
        )
    return store.joinpath(*path.parts)


def _verify_retained_entry(
    store: Path, entry: Mapping[str, Any]
) -> ArtifactIdentity:
    artifact_digest = _require_digest(entry.get("artifact_digest"), "artifact_digest")
    source_digest = _require_digest(entry.get("source_digest"), "source_digest")
    platform = _require_platform(entry.get("platform"), "platform")
    image_id = _require_digest(entry.get("image_id"), "image_id")
    validation_identity = entry.get("validation_identity")
    if not isinstance(validation_identity, str) or not validation_identity:
        raise ArtifactStoreIntegrityError("validation identity is missing from index")
    expected_root = "artifacts/" + artifact_digest.split(":", 1)[1]
    if entry.get("path") != expected_root:
        raise ArtifactStoreIntegrityError(
            "indexed artifact path does not match its digest"
        )
    root = _safe_store_path(store, entry.get("path"), "indexed artifact")
    if root.is_symlink() or not root.is_dir():
        raise ArtifactStoreIntegrityError("indexed artifact directory is missing")
    files = _mapping(entry.get("files"), "indexed artifact files")
    required = {
        "source-bundle.json",
        "bot-artifact-manifest.json",
        "validation-report.json",
    }
    if not required.issubset(files):
        missing = sorted(required - set(files))
        raise ArtifactStoreIntegrityError(
            "indexed artifact is missing required retained files: " + ", ".join(missing)
        )
    if not any(str(name).startswith("source/") for name in files):
        raise ArtifactStoreIntegrityError(
            "indexed artifact is missing its frozen source files"
        )
    actual_files = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ArtifactStoreIntegrityError(
                "retained artifact contains a symlink: "
                + path.relative_to(root).as_posix()
            )
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise ArtifactStoreIntegrityError(
                "retained artifact contains a non-regular path"
            )
    if actual_files != set(files):
        raise ArtifactStoreIntegrityError(
            "retained artifact files do not match the integrity-protected index"
        )
    for relative, expected_digest in files.items():
        _require_digest(expected_digest, "retained file digest")
        path = _safe_store_path(root, relative, "retained file")
        if path.is_symlink() or not path.is_file():
            raise ArtifactStoreIntegrityError(
                "retained file is missing: " + str(relative)
            )
        if _file_digest(path) != expected_digest:
            raise ArtifactStoreIntegrityError(
                "retained file digest mismatch: " + str(relative)
            )

    source = _read_object(root / "source-bundle.json", "frozen source bundle manifest")
    manifest = _read_object(
        root / "bot-artifact-manifest.json", "Bot Artifact Manifest"
    )
    report = _read_object(root / "validation-report.json", "validation report")
    declared_source_files = source.get("files")
    indexed_source_files = sorted(
        name.removeprefix("source/")
        for name in files
        if name.startswith("source/")
    )
    if (
        not isinstance(declared_source_files, list)
        or sorted(declared_source_files) != indexed_source_files
    ):
        raise ArtifactStoreIntegrityError(
            "frozen source manifest files do not match retained source files"
        )
    retained_identity = _artifact_identity_from_documents(source, manifest, report)
    comparisons = (
        (
            retained_identity.artifact_digest,
            artifact_digest,
            "manifest artifact digest",
        ),
        (retained_identity.source_digest, source_digest, "manifest source digest"),
        (retained_identity.platform, platform, "manifest platform"),
        (
            retained_identity.validation_identity,
            validation_identity,
            "manifest validation identity",
        ),
        (retained_identity.image_id, image_id, "image ID"),
    )
    for observed, expected, description in comparisons:
        if observed != expected:
            raise ArtifactStoreIntegrityError(description + " mismatch")
    return retained_identity


def verify_artifact_store(store: Path) -> Mapping[str, Any]:
    """Verify every retained byte and identity without changing Docker state."""
    if store.is_symlink() or not store.is_dir():
        raise ArtifactStoreIntegrityError(
            "artifact store is missing or not a directory"
        )
    index = _read_object(store / "artifact-set-index.json", "artifact store index")
    if (
        index.get("artifact_set_index_format_version")
        != ARTIFACT_SET_INDEX_FORMAT_VERSION
    ):
        raise ArtifactStoreIntegrityError("artifact store index format is unsupported")
    integrity = _mapping(index.get("integrity"), "artifact store index integrity")
    if integrity.get("algorithm") != "sha256":
        raise ArtifactStoreIntegrityError(
            "artifact store index integrity algorithm is unsupported"
        )
    unsigned = {key: value for key, value in index.items() if key != "integrity"}
    if integrity.get("index_identity") != _artifact_set_index_identity(unsigned):
        raise ArtifactStoreIntegrityError("artifact store index integrity mismatch")

    archive = _mapping(index.get("archive"), "image archive")
    if archive.get("format") != ARCHIVE_FORMAT or archive.get("path") != "images.tar":
        raise ArtifactStoreIntegrityError(
            "image archive reference is unsupported or corrupt"
        )
    archive_path = _safe_store_path(store, archive.get("path"), "image archive")
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ArtifactStoreIntegrityError("image archive is missing")
    expected_archive_digest = _require_digest(
        archive.get("digest"), "image archive digest"
    )
    if _file_digest(archive_path) != expected_archive_digest:
        raise ArtifactStoreIntegrityError("image archive digest mismatch")

    artifacts = index.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ArtifactStoreIntegrityError("artifact store index contains no artifacts")
    seen: set[tuple[str, str]] = set()
    for value in artifacts:
        if not isinstance(value, dict):
            raise ArtifactStoreIntegrityError("indexed artifact must be an object")
        key = (str(value.get("artifact_digest")), str(value.get("platform")))
        if key in seen:
            raise ArtifactStoreIntegrityError(
                "artifact store index contains a duplicate image"
            )
        seen.add(key)
        _verify_retained_entry(store, value)
    return index


def _load_archive(archive: Path) -> None:
    try:
        completed = subprocess.run(
            ["docker", "image", "load", "--input", str(archive)],
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ArtifactStoreIntegrityError(
            "could not load the verified image archive: " + str(error)
        )
    if completed.returncode != 0:
        diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ArtifactStoreIntegrityError(
            "Docker rejected the verified image archive"
            + (": " + diagnostics if diagnostics else "")
        )


def resolve_artifact(store: Path, artifact_digest: str, platform: str) -> str:
    """Resolve one exact image, restoring only from the verified local archive."""
    requested_digest = _require_digest(artifact_digest, "requested artifact digest")
    requested_platform = _require_platform(platform, "requested platform")
    index = verify_artifact_store(store)
    matches = [
        entry
        for entry in index["artifacts"]
        if entry.get("artifact_digest") == requested_digest
        and entry.get("platform") == requested_platform
    ]
    if len(matches) != 1:
        same_digest = [
            entry
            for entry in index["artifacts"]
            if entry.get("artifact_digest") == requested_digest
        ]
        if same_digest:
            available = ", ".join(
                sorted(str(entry.get("platform")) for entry in same_digest)
            )
            raise ArtifactStoreIntegrityError(
                "wrong platform for indexed image: requested "
                + requested_platform
                + ", available "
                + available
            )
        raise ArtifactStoreIntegrityError(
            "requested image is missing from the verified artifact store: "
            + requested_digest
        )
    entry = matches[0]
    image_id = str(entry["image_id"])
    if _inspect_image(image_id, requested_platform, allow_missing=True):
        _verify_resolved_authority(store, entry, requested_digest)
        return image_id
    _load_archive(store / "images.tar")
    if not _inspect_image(image_id, requested_platform, allow_missing=True):
        raise ArtifactStoreIntegrityError(
            "requested image is missing after loading the verified archive: "
            + requested_digest
            + " (expected local image ID "
            + image_id
            + ")"
        )
    _verify_resolved_authority(store, entry, requested_digest)
    return image_id


def _verify_resolved_authority(
    store: Path, entry: Mapping[str, Any], requested_digest: str
) -> None:
    """Close the archive-to-engine chain back to the authoritative digest."""
    identity = _verify_retained_entry(store, entry)
    if identity.artifact_digest != requested_digest:
        raise ArtifactStoreIntegrityError(
            "restored image authority digest mismatch: expected "
            + requested_digest
            + ", observed "
            + identity.artifact_digest
        )
