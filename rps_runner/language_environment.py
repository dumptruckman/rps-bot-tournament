from __future__ import annotations

from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
from typing import Any, BinaryIO, Iterable, Mapping, Sequence


BUNDLE_FORMAT_VERSION = "source-bundle-v1"


class CatalogError(ValueError):
    """The organizer-owned Language Environment catalog is invalid."""


class SourceValidationError(ValueError):
    """Team-editable source violates its Language Environment schema."""

    def __init__(self, path: str, rule: str, explanation: str) -> None:
        super().__init__(
            "source validation failed for "
            + repr(path)
            + ": "
            + explanation
            + " (rule: "
            + rule
            + ")"
        )
        self.path = path
        self.rule = rule


@dataclass(frozen=True)
class SourceFile:
    path: str
    content: bytes


@dataclass(frozen=True)
class LanguageEnvironment:
    name: str
    descriptor: Mapping[str, Any]

    @property
    def source_schema(self) -> Mapping[str, Any]:
        value = self.descriptor["source_schema"]
        assert isinstance(value, Mapping)
        return value


@dataclass(frozen=True)
class LanguageEnvironmentCatalog:
    version: str
    digest: str
    environments: Mapping[str, LanguageEnvironment]

    def environment(self, name: str) -> LanguageEnvironment:
        try:
            return self.environments[name]
        except KeyError:
            choices = ", ".join(sorted(self.environments))
            raise CatalogError(
                "Language Environment " + repr(name) + " is not in the catalog; "
                "available environments: " + choices
            )


def _require_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(location + " must be an object")
    return value


def _require_string(mapping: Mapping[str, Any], key: str, location: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogError(location + "." + key + " must be a non-empty string")
    return value


def _require_positive_integer(
    mapping: Mapping[str, Any], key: str, location: str
) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CatalogError(location + "." + key + " must be a positive integer")
    return value


def _require_string_list(
    mapping: Mapping[str, Any], key: str, location: str, *, allow_empty: bool = False
) -> Sequence[str]:
    value = mapping.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CatalogError(location + "." + key + " must be a list of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise CatalogError(location + "." + key + " must be a list of strings")
    return value


def _validate_relative_catalog_path(value: str, location: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise CatalogError(location + " must be a safe relative POSIX path")


def _validate_descriptor(name: str, value: Any) -> LanguageEnvironment:
    location = "environments." + name
    descriptor = _require_mapping(value, location)
    for key in (
        "descriptor_version",
        "language",
        "wrapper_version",
        "recipe_version",
        "entrypoint_version",
        "dependency_definition_version",
        "build_target_version",
        "workflow_version",
        "readiness_version",
        "base_runtime_version",
        "platform_version",
        "conformance_version",
    ):
        _require_string(descriptor, key, location)
    if not isinstance(descriptor.get("contract_only"), bool):
        raise CatalogError(location + ".contract_only must be a boolean")

    participant_contract = _require_mapping(
        descriptor.get("participant_contract"), location + ".participant_contract"
    )
    _require_string(participant_contract, "version", location + ".participant_contract")
    _require_string(
        participant_contract, "callable", location + ".participant_contract"
    )
    _require_string(
        participant_contract, "signature", location + ".participant_contract"
    )

    schema_location = location + ".source_schema"
    schema = _require_mapping(descriptor.get("source_schema"), schema_location)
    _require_string(schema, "version", schema_location)
    for key in ("max_file_count", "max_file_bytes", "max_total_bytes"):
        _require_positive_integer(schema, key, schema_location)
    for key in ("required_paths", "allowed_files", "forbidden_paths"):
        paths = _require_string_list(
            schema, key, schema_location, allow_empty=(key == "forbidden_paths")
        )
        for index, path in enumerate(paths):
            _validate_relative_catalog_path(
                path, schema_location + "." + key + "[" + str(index) + "]"
            )
    return LanguageEnvironment(name=name, descriptor=descriptor)


def load_catalog(path: Path) -> LanguageEnvironmentCatalog:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CatalogError(
            "could not read catalog " + repr(str(path)) + ": " + str(error)
        )
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogError(
            "catalog " + repr(str(path)) + " is not valid JSON: " + str(error)
        )

    root = _require_mapping(value, "catalog")
    format_version = _require_string(root, "format_version", "catalog")
    if format_version != "language-environment-catalog-format-v1":
        raise CatalogError(
            "catalog.format_version "
            + repr(format_version)
            + " is unsupported; expected 'language-environment-catalog-format-v1'"
        )
    version = _require_string(root, "catalog_version", "catalog")
    environment_values = _require_mapping(
        root.get("environments"), "catalog.environments"
    )
    if not environment_values:
        raise CatalogError("catalog.environments must not be empty")
    environments = {
        name: _validate_descriptor(name, descriptor)
        for name, descriptor in environment_values.items()
        if isinstance(name, str) and name
    }
    if len(environments) != len(environment_values):
        raise CatalogError("catalog environment names must be non-empty strings")

    canonical = json.dumps(root, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return LanguageEnvironmentCatalog(
        version=version, digest=digest, environments=environments
    )


def _is_forbidden(path: str, forbidden_paths: Sequence[str]) -> bool:
    lowered = path.casefold()
    basename = PurePosixPath(lowered).name
    for forbidden in forbidden_paths:
        candidate = forbidden.casefold()
        if "/" in candidate:
            if lowered == candidate or lowered.startswith(candidate.rstrip("/") + "/"):
                return True
        elif (
            basename == candidate
            or lowered == candidate
            or lowered.startswith(candidate + "/")
        ):
            return True
    return False


def _is_allowed(path: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _read_regular_file(path: Path, relative_path: str, maximum_bytes: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        raise SourceValidationError(
            relative_path,
            "regular_files",
            "could not safely read regular file: " + str(error),
        )
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise SourceValidationError(
                relative_path,
                "regular_files",
                "only regular files are allowed",
            )
        if details.st_size > maximum_bytes:
            raise SourceValidationError(
                relative_path,
                "max_file_bytes",
                "file is "
                + str(details.st_size)
                + " bytes; maximum is "
                + str(maximum_bytes)
                + " bytes",
            )
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = _read_bounded(stream, maximum_bytes, relative_path)
        after = os.fstat(descriptor)
        if (details.st_dev, details.st_ino, details.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise SourceValidationError(
                relative_path,
                "stable_source",
                "file changed while it was being validated; retry with an "
                "unchanged source directory",
            )
        return content
    finally:
        os.close(descriptor)


def _read_bounded(stream: BinaryIO, maximum_bytes: int, relative_path: str) -> bytes:
    content = stream.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise SourceValidationError(
            relative_path,
            "max_file_bytes",
            "file exceeds the maximum of " + str(maximum_bytes) + " bytes",
        )
    return content


def _walk_source(source: Path) -> Iterable[tuple[str, Path, os.stat_result]]:
    def walk(
        directory: Path, prefix: str
    ) -> Iterable[tuple[str, Path, os.stat_result]]:
        try:
            with os.scandir(str(directory)) as scanned:
                entries = sorted(scanned, key=lambda item: item.name)
        except OSError as error:
            shown = prefix or "."
            raise SourceValidationError(
                shown,
                "readable_source",
                "could not read source directory: " + str(error),
            )
        for entry in entries:
            relative_path = entry.name if not prefix else prefix + "/" + entry.name
            try:
                details = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise SourceValidationError(
                    relative_path,
                    "readable_source",
                    "could not inspect path: " + str(error),
                )
            if stat.S_ISLNK(details.st_mode):
                raise SourceValidationError(
                    relative_path,
                    "no_symlinks",
                    "symbolic links are not allowed because their targets can "
                    "traverse or use absolute paths",
                )
            if stat.S_ISDIR(details.st_mode):
                yield from walk(Path(entry.path), relative_path)
            else:
                yield relative_path, Path(entry.path), details

    return walk(source, "")


def validate_source(
    source: Path, environment: LanguageEnvironment
) -> Sequence[SourceFile]:
    if not source.exists():
        raise SourceValidationError(
            ".", "source_directory", "source directory does not exist"
        )
    if source.is_symlink():
        raise SourceValidationError(
            ".",
            "no_symlinks",
            "the selected source directory must not be a symbolic link",
        )
    if not source.is_dir():
        raise SourceValidationError(
            ".", "source_directory", "selected source is not a directory"
        )

    schema = environment.source_schema
    allowed = _require_string_list(schema, "allowed_files", "source_schema")
    forbidden = _require_string_list(
        schema, "forbidden_paths", "source_schema", allow_empty=True
    )
    maximum_count = _require_positive_integer(schema, "max_file_count", "source_schema")
    maximum_file_bytes = _require_positive_integer(
        schema, "max_file_bytes", "source_schema"
    )
    maximum_total_bytes = _require_positive_integer(
        schema, "max_total_bytes", "source_schema"
    )

    files = []
    total_bytes = 0
    for relative_path, path, details in _walk_source(source):
        if _is_forbidden(relative_path, forbidden):
            raise SourceValidationError(
                relative_path,
                "forbidden_paths",
                "forbidden infrastructure path cannot be supplied by a Team",
            )
        if not stat.S_ISREG(details.st_mode):
            raise SourceValidationError(
                relative_path, "regular_files", "only regular files are allowed"
            )
        if not _is_allowed(relative_path, allowed):
            raise SourceValidationError(
                relative_path,
                "allowed_files",
                "unsupported file type or source location for " + environment.name,
            )
        if len(files) + 1 > maximum_count:
            raise SourceValidationError(
                relative_path,
                "max_file_count",
                "source contains more than " + str(maximum_count) + " files",
            )
        content = _read_regular_file(path, relative_path, maximum_file_bytes)
        total_bytes += len(content)
        if total_bytes > maximum_total_bytes:
            raise SourceValidationError(
                relative_path,
                "max_total_bytes",
                "aggregate source size exceeds " + str(maximum_total_bytes) + " bytes",
            )
        files.append(SourceFile(path=relative_path, content=content))

    found = {item.path for item in files}
    required = _require_string_list(schema, "required_paths", "source_schema")
    for required_path in required:
        if required_path not in found:
            raise SourceValidationError(
                required_path,
                "required_paths",
                "required Team source file is missing",
            )
    return files


def _source_digest(files: Sequence[SourceFile]) -> str:
    digest = hashlib.sha256()
    digest.update((BUNDLE_FORMAT_VERSION + "\0").encode("utf-8"))
    for item in files:
        path = item.path.encode("utf-8")
        digest.update(len(path).to_bytes(8, "big"))
        digest.update(path)
        digest.update(len(item.content).to_bytes(8, "big"))
        digest.update(item.content)
    return "sha256:" + digest.hexdigest()


def _version_manifest(
    catalog: LanguageEnvironmentCatalog, environment: LanguageEnvironment
) -> Mapping[str, str]:
    descriptor = environment.descriptor
    schema = environment.source_schema
    return {
        "catalog": catalog.version,
        "descriptor": str(descriptor["descriptor_version"]),
        "source_schema": str(schema["version"]),
        "wrapper": str(descriptor["wrapper_version"]),
        "recipe": str(descriptor["recipe_version"]),
        "entrypoint": str(descriptor["entrypoint_version"]),
        "dependency_definition": str(descriptor["dependency_definition_version"]),
        "build_target": str(descriptor["build_target_version"]),
        "workflow": str(descriptor["workflow_version"]),
        "readiness": str(descriptor["readiness_version"]),
        "base_runtime": str(descriptor["base_runtime_version"]),
        "platform": str(descriptor["platform_version"]),
        "conformance": str(descriptor["conformance_version"]),
    }


def freeze_source_bundle(
    source: Path,
    bundle: Path,
    catalog: LanguageEnvironmentCatalog,
    environment: LanguageEnvironment,
) -> Mapping[str, Any]:
    try:
        bundle.resolve().relative_to(source.resolve())
    except ValueError:
        pass
    else:
        raise SourceValidationError(
            ".",
            "bundle_location",
            "bundle destination must be outside the source directory",
        )
    if bundle.exists() or bundle.is_symlink():
        raise SourceValidationError(
            str(bundle),
            "immutable_bundle",
            "bundle already exists and will not be replaced",
        )

    files = validate_source(source, environment)
    participant_contract = environment.descriptor["participant_contract"]
    result = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "catalog_digest": catalog.digest,
        "contract_only": environment.descriptor["contract_only"],
        "environment": environment.name,
        "files": [item.path for item in files],
        "participant_contract": participant_contract,
        "source_digest": _source_digest(files),
        "versions": _version_manifest(catalog, environment),
    }

    bundle.parent.mkdir(parents=True, exist_ok=True)
    try:
        bundle.mkdir()
        source_output = bundle / "source"
        source_output.mkdir()
        for item in files:
            destination = source_output / PurePosixPath(item.path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(item.content)
            destination.chmod(0o444)
        manifest = bundle / "source-bundle.json"
        manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        manifest.chmod(0o444)
        for directory in sorted(
            (path for path in source_output.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            directory.chmod(0o555)
        source_output.chmod(0o555)
        bundle.chmod(0o555)
    except BaseException:
        if bundle.exists():
            for path in bundle.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            bundle.chmod(0o755)
            shutil.rmtree(bundle)
        raise
    return result
