"""Durable canonical storage for a Tournament.

Competition Records and the Tournament Manifest are the authoritative data in
this module. Operational Telemetry and the Scoreboard Projection intentionally
use separate files and do not participate in canonical record hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional, Union

from rps_runner.tournament.immutable import FrozenJsonDict, freeze_json, thaw_json


class StorageError(Exception):
    """Base class for Tournament storage failures."""


class IntegrityError(StorageError):
    """Canonical Tournament data failed verification."""


class ManifestAlreadySealedError(StorageError):
    """A sealed Tournament Manifest already exists."""


class RecordSequenceError(IntegrityError):
    """Competition Records are missing or out of canonical order."""


@dataclass(frozen=True)
class StoredManifest:
    manifest: FrozenJsonDict
    checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest",
            _freeze_json_object(thaw_json(self.manifest), "Manifest"),
        )


@dataclass(frozen=True)
class StoredCompetitionRecord:
    sequence: int
    record: FrozenJsonDict
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "record",
            _freeze_json_object(thaw_json(self.record), "Competition Record"),
        )


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value to deterministic UTF-8 bytes."""

    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def seal_manifest(
    tournament_directory: Union[Path, str], manifest: Mapping[str, Any]
) -> StoredManifest:
    """Atomically seal the immutable checksummed Tournament Manifest."""

    manifest_value = _freeze_json_object(
        _detached_json_object(manifest, "Manifest"), "Manifest"
    )
    checksum = _sha256(canonical_json_bytes(manifest_value))
    stored = StoredManifest(manifest=manifest_value, checksum=checksum)
    encoded = canonical_json_bytes(
        {"checksum": stored.checksum, "manifest": stored.manifest}
    )
    path = Path(tournament_directory) / "manifest.json"
    try:
        _atomic_create(path, encoded)
    except FileExistsError as error:
        raise ManifestAlreadySealedError(
            f"Tournament Manifest is already sealed at {path}"
        ) from error
    return stored


def load_manifest(tournament_directory: Union[Path, str]) -> StoredManifest:
    """Load and checksum-verify a sealed Tournament Manifest."""

    path = Path(tournament_directory) / "manifest.json"
    envelope = _read_json_object(path, "Tournament Manifest")
    if set(envelope) != {"checksum", "manifest"}:
        raise IntegrityError("Tournament Manifest envelope is invalid")
    checksum = envelope["checksum"]
    manifest = envelope["manifest"]
    if not isinstance(checksum, str) or not isinstance(manifest, dict):
        raise IntegrityError("Tournament Manifest envelope is invalid")
    actual = _sha256(canonical_json_bytes(manifest))
    if actual != checksum:
        raise IntegrityError("Tournament Manifest checksum does not match")
    return StoredManifest(
        manifest=_freeze_json_object(manifest, "Manifest"), checksum=checksum
    )


def append_competition_record(
    tournament_directory: Union[Path, str], record: Mapping[str, Any]
) -> StoredCompetitionRecord:
    """Atomically append one canonical, sequenced Competition Record."""

    directory = Path(tournament_directory)
    existing = load_competition_records(directory)
    sequence = len(existing) + 1
    record_value = _freeze_json_object(
        _detached_json_object(record, "Competition Record"),
        "Competition Record",
    )
    body = {"record": record_value, "sequence": sequence}
    content_hash = _sha256(canonical_json_bytes(body))
    stored = StoredCompetitionRecord(
        sequence=sequence,
        record=record_value,
        content_hash=content_hash,
    )
    envelope = dict(body)
    envelope["content_hash"] = content_hash
    path = directory / "records" / f"{sequence:08d}.json"
    try:
        _atomic_create(path, canonical_json_bytes(envelope))
    except FileExistsError as error:
        raise RecordSequenceError(
            f"Competition Record sequence {sequence} already exists"
        ) from error
    _write_records_index(directory, existing + [stored])
    return stored


def load_competition_records(
    tournament_directory: Union[Path, str]
) -> list[StoredCompetitionRecord]:
    """Load all Competition Records after verifying order and hashes."""

    directory = Path(tournament_directory)
    records_directory = directory / "records"
    index_path = directory / "records.index.json"
    if not records_directory.exists():
        if index_path.exists():
            raise RecordSequenceError(
                "Competition Record count cannot be verified without records"
            )
        return []
    paths = sorted(records_directory.glob("*.json"))
    loaded: list[StoredCompetitionRecord] = []
    for expected_sequence, path in enumerate(paths, start=1):
        expected_name = f"{expected_sequence:08d}.json"
        if path.name != expected_name:
            raise RecordSequenceError(
                "Competition Record sequence is missing or reordered at "
                f"{expected_name}"
            )
        envelope = _read_json_object(path, "Competition Record")
        if set(envelope) != {"content_hash", "record", "sequence"}:
            raise IntegrityError(f"Competition Record envelope is invalid: {path}")
        sequence = envelope["sequence"]
        record = envelope["record"]
        content_hash = envelope["content_hash"]
        if sequence != expected_sequence or isinstance(sequence, bool):
            raise RecordSequenceError(
                f"Competition Record sequence is invalid: {path}"
            )
        if not isinstance(record, dict) or not isinstance(content_hash, str):
            raise IntegrityError(f"Competition Record envelope is invalid: {path}")
        body = {"record": record, "sequence": sequence}
        actual_hash = _sha256(canonical_json_bytes(body))
        if actual_hash != content_hash:
            raise IntegrityError(
                f"Competition Record content hash does not match: {path}"
            )
        loaded.append(
            StoredCompetitionRecord(
                sequence=sequence,
                record=_freeze_json_object(record, "Competition Record"),
                content_hash=content_hash,
            )
        )
    index = _read_json_object(index_path, "Competition Record index")
    if set(index) != {"count", "records_hash"}:
        raise IntegrityError("Competition Record index is invalid")
    count = index["count"]
    if isinstance(count, bool) or not isinstance(count, int) or count != len(loaded):
        raise RecordSequenceError(
            "Competition Record count does not match the canonical index"
        )
    records_hash = index["records_hash"]
    actual_records_hash = _sha256(
        canonical_json_bytes([record.content_hash for record in loaded])
    )
    if not isinstance(records_hash, str) or records_hash != actual_records_hash:
        raise IntegrityError("Competition Record index hash does not match")
    return loaded


def committed_match_ids(
    tournament_directory: Union[Path, str]
) -> set[str]:
    """Return Match IDs having a verified terminal Competition Record."""

    committed: set[str] = set()
    for stored in load_competition_records(tournament_directory):
        if stored.record.get("type") != "match_terminal":
            continue
        match_id = stored.record.get("match_id")
        if not isinstance(match_id, str) or not match_id:
            raise IntegrityError(
                "Terminal Competition Record must contain a non-empty match_id"
            )
        committed.add(match_id)
    return committed


def is_match_committed(
    tournament_directory: Union[Path, str], match_id: str
) -> bool:
    """Report whether a verified terminal record commits ``match_id``."""

    return match_id in committed_match_ids(tournament_directory)


def append_operational_telemetry(
    tournament_directory: Union[Path, str], telemetry: Mapping[str, Any]
) -> int:
    """Append non-canonical execution observations outside Competition Records."""

    directory = Path(tournament_directory)
    existing = load_operational_telemetry(directory)
    sequence = len(existing) + 1
    telemetry_value = _detached_json_object(telemetry, "Operational Telemetry")
    path = directory / "telemetry" / f"{sequence:08d}.json"
    try:
        _atomic_create(path, canonical_json_bytes(telemetry_value))
    except FileExistsError as error:
        raise StorageError(
            f"Operational Telemetry sequence {sequence} already exists"
        ) from error
    return sequence


def load_operational_telemetry(
    tournament_directory: Union[Path, str]
) -> list[dict[str, Any]]:
    """Load variable Operational Telemetry in its append order."""

    telemetry_directory = Path(tournament_directory) / "telemetry"
    if not telemetry_directory.exists():
        return []
    loaded: list[dict[str, Any]] = []
    for expected_sequence, path in enumerate(
        sorted(telemetry_directory.glob("*.json")), start=1
    ):
        if path.name != f"{expected_sequence:08d}.json":
            raise IntegrityError(f"Operational Telemetry sequence is invalid: {path}")
        loaded.append(_read_json_object(path, "Operational Telemetry"))
    return loaded


def write_scoreboard_projection(
    tournament_directory: Union[Path, str], projection: Mapping[str, Any]
) -> None:
    """Atomically replace the rebuildable read-only Scoreboard Projection."""

    projection_value = _detached_json_object(projection, "Scoreboard Projection")
    _atomic_replace(
        Path(tournament_directory) / "scoreboard.json",
        canonical_json_bytes(projection_value),
    )


def load_scoreboard_projection(
    tournament_directory: Union[Path, str]
) -> Optional[dict[str, Any]]:
    """Load the Scoreboard Projection, or ``None`` when it needs rebuilding."""

    path = Path(tournament_directory) / "scoreboard.json"
    if not path.exists():
        return None
    return _read_json_object(path, "Scoreboard Projection")


def _write_records_index(
    tournament_directory: Path, records: list[StoredCompetitionRecord]
) -> None:
    index = {
        "count": len(records),
        "records_hash": _sha256(
            canonical_json_bytes([record.content_hash for record in records])
        ),
    }
    _atomic_replace(
        tournament_directory / "records.index.json", canonical_json_bytes(index)
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _detached_json_object(
    value: Mapping[str, Any], description: str
) -> dict[str, Any]:
    try:
        detached = json.loads(canonical_json_bytes(thaw_json(value)))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise StorageError(f"{description} is not a canonical JSON object") from error
    if not isinstance(detached, dict):
        raise StorageError(f"{description} is not a canonical JSON object")
    return detached


def _freeze_json_object(value: dict[str, Any], description: str) -> FrozenJsonDict:
    try:
        frozen = freeze_json(value)
    except (TypeError, ValueError) as error:
        raise StorageError(f"{description} is not a canonical JSON object") from error
    if not isinstance(frozen, FrozenJsonDict):
        raise StorageError(f"{description} is not a canonical JSON object")
    return frozen


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
        value = json.loads(encoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrityError(f"{description} is missing or invalid: {path}") from error
    if not isinstance(value, dict):
        raise IntegrityError(f"{description} is not a JSON object: {path}")
    if encoded != canonical_json_bytes(value):
        raise IntegrityError(f"{description} does not use canonical JSON: {path}")
    return value


def _atomic_create(path: Path, content: bytes) -> None:
    """Publish complete content without ever replacing an existing target."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.chmod(0o444)
        os.link(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _atomic_replace(path: Path, content: bytes) -> None:
    """Replace a rebuildable or derived file with complete durable content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
