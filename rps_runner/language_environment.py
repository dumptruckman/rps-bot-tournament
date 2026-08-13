from __future__ import annotations

import ast
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
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
class SourceSchema:
    version: str
    identity: str
    required_paths: Sequence[str]
    allowed_files: Sequence[str]
    forbidden_paths: Sequence[str]
    max_file_count: int
    max_file_bytes: int
    max_total_bytes: int


@dataclass(frozen=True)
class ParticipantContract:
    version: str
    callable: str
    signature: str
    static_validation: str

    def as_manifest(self) -> Mapping[str, str]:
        return {
            "version": self.version,
            "callable": self.callable,
            "signature": self.signature,
            "static_validation": self.static_validation,
        }


@dataclass(frozen=True)
class CatalogAsset:
    version: str
    catalog_path: str
    path: Path
    digest: str
    content: bytes

    @property
    def identity(self) -> str:
        return self.version + "@" + self.digest


@dataclass(frozen=True)
class CatalogImage:
    version: str
    reference: str
    digest: str

    @property
    def identity(self) -> str:
        return self.version + "@" + self.digest


@dataclass(frozen=True)
class LanguageEnvironment:
    name: str
    language: str
    contract_only: bool
    publication: str
    participant_contract: ParticipantContract
    source_schema: SourceSchema
    descriptor_version: str
    descriptor_identity: str
    assets: Mapping[str, CatalogAsset]

    def platform_images(self, platform: str) -> tuple[CatalogImage, CatalogImage]:
        try:
            definition = json.loads(self.assets["base_runtime"].content)
            selected = definition["platforms"][platform]
            build = selected.get("build_toolchain", selected)
            execution = selected.get("execution_runtime", selected)
            return (
                _catalog_image(build, self.name + " " + platform + " build toolchain"),
                _catalog_image(
                    execution, self.name + " " + platform + " execution runtime"
                ),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise CatalogError(
                self.name + " has no complete image definitions for " + platform
            ) from error


@dataclass(frozen=True)
class LanguageEnvironmentCatalog:
    version: str
    digest: str
    environments: Mapping[str, LanguageEnvironment]

    @property
    def identity(self) -> str:
        return self.version + "@" + self.digest

    def environment(self, name: str) -> LanguageEnvironment:
        try:
            return self.environments[name]
        except KeyError:
            choices = ", ".join(sorted(self.environments))
            raise CatalogError(
                "Language Environment " + repr(name) + " is not in the catalog; "
                "available environments: " + choices
            )

@dataclass(frozen=True)
class FrozenSourceBundle:
    path: Path
    source_path: Path
    manifest: Mapping[str, Any]
    environment: LanguageEnvironment
    files: Sequence[SourceFile]


def _catalog_image(value: Any, location: str) -> CatalogImage:
    if not isinstance(value, dict):
        raise CatalogError(location + " must be an image record")
    version = value.get("version")
    reference = value.get("image")
    if not isinstance(version, str) or not version:
        raise CatalogError(location + ".version must be a non-empty string")
    if not isinstance(reference, str) or "@" not in reference:
        raise CatalogError(location + ".image must be pinned by digest")
    digest = reference.rsplit("@", 1)[1]
    if (
        not digest.startswith("sha256:")
        or len(digest) != 71
        or any(character not in "0123456789abcdef" for character in digest[7:])
        or ":latest" in reference.lower()
    ):
        raise CatalogError(location + ".image must use a full immutable sha256 digest")
    return CatalogImage(version, reference, digest)


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


def _content_identity(version: str, value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return version + "@sha256:" + hashlib.sha256(canonical).hexdigest()


def _validate_asset(
    catalog_directory: Path,
    value: Any,
    location: str,
) -> CatalogAsset:
    asset = _require_mapping(value, location)
    version = _require_string(asset, "version", location)
    relative_path = _require_string(asset, "path", location)
    _validate_relative_catalog_path(relative_path, location + ".path")
    expected_digest = _require_string(asset, "sha256", location)
    if not expected_digest.startswith("sha256:") or len(expected_digest) != 71:
        raise CatalogError(location + ".sha256 must be a full sha256 digest")
    path = catalog_directory / PurePosixPath(relative_path)
    if path.is_symlink():
        raise CatalogError(location + ".path must not be a symbolic link")
    try:
        path.resolve().relative_to(catalog_directory.resolve())
    except ValueError:
        raise CatalogError(location + ".path must stay within the catalog directory")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CatalogError(
            "could not read organizer-owned asset "
            + repr(relative_path)
            + ": "
            + str(error)
        )
    if not path.is_file():
        raise CatalogError(location + ".path must name a regular file")
    actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise CatalogError(
            "organizer-owned asset "
            + repr(relative_path)
            + " does not match "
            + location
            + ".sha256"
        )
    return CatalogAsset(
        version=version,
        catalog_path=relative_path,
        path=path,
        digest=actual_digest,
        content=content,
    )


def _validate_descriptor(
    name: str, value: Any, catalog_directory: Path
) -> LanguageEnvironment:
    location = "environments." + name
    descriptor = _require_mapping(value, location)
    descriptor_version = _require_string(
        descriptor, "descriptor_version", location
    )
    language = _require_string(descriptor, "language", location)
    if not isinstance(descriptor.get("contract_only"), bool):
        raise CatalogError(location + ".contract_only must be a boolean")
    contract_only = bool(descriptor["contract_only"])
    publication = _require_string(descriptor, "publication", location)
    if publication not in ("production", "internal"):
        raise CatalogError(location + ".publication must be 'production' or 'internal'")
    if publication == "production" and contract_only:
        raise CatalogError(location + " cannot publish a contract-only environment")

    participant_value = _require_mapping(
        descriptor.get("participant_contract"), location + ".participant_contract"
    )
    participant_location = location + ".participant_contract"
    participant_contract = ParticipantContract(
        version=_require_string(participant_value, "version", participant_location),
        callable=_require_string(participant_value, "callable", participant_location),
        signature=_require_string(
            participant_value, "signature", participant_location
        ),
        static_validation=_require_string(
            participant_value, "static_validation", participant_location
        ),
    )
    if participant_contract.static_validation not in _PARTICIPANT_CONTRACT_VALIDATORS:
        raise CatalogError(
            participant_location
            + ".static_validation "
            + repr(participant_contract.static_validation)
            + " is unsupported"
        )

    schema_location = location + ".source_schema"
    schema = _require_mapping(descriptor.get("source_schema"), schema_location)
    _require_string(schema, "version", schema_location)
    path_fields = {}
    for key in ("required_paths", "allowed_files", "forbidden_paths"):
        paths = tuple(
            _require_string_list(
                schema, key, schema_location, allow_empty=(key == "forbidden_paths")
            )
        )
        for index, path in enumerate(paths):
            _validate_relative_catalog_path(
                path, schema_location + "." + key + "[" + str(index) + "]"
            )
        path_fields[key] = paths
    source_schema = SourceSchema(
        version=_require_string(schema, "version", schema_location),
        identity=_content_identity(
            _require_string(schema, "version", schema_location), schema
        ),
        required_paths=path_fields["required_paths"],
        allowed_files=path_fields["allowed_files"],
        forbidden_paths=path_fields["forbidden_paths"],
        max_file_count=_require_positive_integer(
            schema, "max_file_count", schema_location
        ),
        max_file_bytes=_require_positive_integer(
            schema, "max_file_bytes", schema_location
        ),
        max_total_bytes=_require_positive_integer(
            schema, "max_total_bytes", schema_location
        ),
    )
    assets_location = location + ".assets"
    assets = _require_mapping(descriptor.get("assets"), assets_location)
    expected_assets = {
        "wrapper",
        "recipe",
        "entrypoint",
        "dependency_definition",
        "build_target",
        "workflow",
        "readiness",
        "base_runtime",
        "build_toolchain",
        "platform",
        "conformance",
    }
    if set(assets) != expected_assets:
        raise CatalogError(
            assets_location
            + " must define exactly: "
            + ", ".join(sorted(expected_assets))
        )
    validated_assets = {
        key: _validate_asset(
            catalog_directory,
            assets[key],
            assets_location + "." + key,
        )
        for key in expected_assets
    }
    return LanguageEnvironment(
        name=name,
        language=language,
        contract_only=contract_only,
        publication=publication,
        participant_contract=participant_contract,
        source_schema=source_schema,
        descriptor_version=descriptor_version,
        descriptor_identity=_content_identity(descriptor_version, descriptor),
        assets=validated_assets,
    )


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
        name: _validate_descriptor(name, descriptor, path.parent)
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

    files = []
    total_bytes = 0
    for relative_path, path, details in _walk_source(source):
        if _is_forbidden(relative_path, schema.forbidden_paths):
            raise SourceValidationError(
                relative_path,
                "forbidden_paths",
                "forbidden infrastructure path cannot be supplied by a Team",
            )
        if not stat.S_ISREG(details.st_mode):
            raise SourceValidationError(
                relative_path, "regular_files", "only regular files are allowed"
            )
        if not _is_allowed(relative_path, schema.allowed_files):
            raise SourceValidationError(
                relative_path,
                "allowed_files",
                "unsupported file type or source location for " + environment.name,
            )
        if len(files) + 1 > schema.max_file_count:
            raise SourceValidationError(
                relative_path,
                "max_file_count",
                "source contains more than " + str(schema.max_file_count) + " files",
            )
        content = _read_regular_file(path, relative_path, schema.max_file_bytes)
        total_bytes += len(content)
        if total_bytes > schema.max_total_bytes:
            raise SourceValidationError(
                relative_path,
                "max_total_bytes",
                "aggregate source size exceeds "
                + str(schema.max_total_bytes)
                + " bytes",
            )
        files.append(SourceFile(path=relative_path, content=content))

    found = {item.path for item in files}
    for required_path in schema.required_paths:
        if required_path not in found:
            raise SourceValidationError(
                required_path,
                "required_paths",
                "required Team source file is missing",
            )
    _validate_participant_contract(files, environment)
    return files


def _validate_participant_contract(
    files: Sequence[SourceFile], environment: LanguageEnvironment
) -> None:
    _PARTICIPANT_CONTRACT_VALIDATORS[
        environment.participant_contract.static_validation
    ](files)


def _validate_no_static_contract(_files: Sequence[SourceFile]) -> None:
    return


def _validate_go_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.go")
    go_sources = []
    for item in files:
        if not item.path.endswith(".go"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Go strategy source must be UTF-8: " + str(error),
            )
        significant_source = _go_significant_source(source)
        go_sources.append((item, significant_source))
        if not re.search(r"(?m)^\s*package\s+main\s*$", significant_source):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Go strategy files must declare package main",
            )
        for reserved in ("init", "main"):
            if re.search(
                r"(?m)^\s*func\s+" + reserved + r"\s*\(", significant_source
            ):
                raise SourceValidationError(
                    item.path,
                    "participant_contract",
                    "Team Source must not define the organizer-owned "
                    + reserved
                    + " function",
                )
        if re.search(r"(?m)^\s*//go:", source):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Go compiler directives are not allowed in Team Source",
            )
    source = _go_significant_source(source_file.content.decode("utf-8"))
    signature = re.compile(
        r"(?m)^\s*func\s+ChooseMove\s*\(\s*turn\s+int\s*,\s*"
        r"myHistory\s*,\s*opponentHistory\s+string\s*,\s*"
        r"rng\s+\*rand\.Rand\s*\)\s+string\s*\{"
    )
    bindings = sum(len(signature.findall(value)) for _, value in go_sources)
    if bindings != 1 or not signature.search(source):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one ChooseMove(turn int, myHistory, opponentHistory "
            "string, rng *rand.Rand) string function",
        )


def _go_significant_source(source: str) -> str:
    """Blank Go comments and literal contents while preserving line structure."""

    return _c_like_significant_source(source, raw_delimiters=("`",))


def _c_like_significant_source(
    source: str, *, raw_delimiters: Sequence[str]
) -> str:
    """Blank C-like comments and literal contents while preserving line structure."""

    result = list(source)
    index = 0
    state = "code"
    delimiter = ""
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if character == "/" and following == "/":
                result[index] = result[index + 1] = " "
                state = "line-comment"
                index += 2
                continue
            if character == "/" and following == "*":
                result[index] = result[index + 1] = " "
                state = "block-comment"
                index += 2
                continue
            raw_delimiter = next(
                (value for value in raw_delimiters if source.startswith(value, index)),
                None,
            )
            if raw_delimiter is not None:
                delimiter = raw_delimiter
                for offset in range(len(delimiter)):
                    result[index + offset] = " "
                state = "raw-string"
                index += len(delimiter)
                continue
            if character in ('"', "'"):
                delimiter = character
                result[index] = " "
                state = "string"
        elif state == "line-comment":
            if character == "\n":
                state = "code"
            else:
                result[index] = " "
        elif state == "block-comment":
            if character == "*" and following == "/":
                result[index] = result[index + 1] = " "
                state = "code"
                index += 2
                continue
            if character != "\n":
                result[index] = " "
        elif state == "raw-string":
            if source.startswith(delimiter, index):
                for offset in range(len(delimiter)):
                    result[index + offset] = " "
                state = "code"
                index += len(delimiter)
                continue
            elif character != "\n":
                result[index] = " "
        elif state == "string":
            result[index] = " " if character != "\n" else "\n"
            if character == "\\":
                if index + 1 < len(source):
                    if source[index + 1] != "\n":
                        result[index + 1] = " "
                    index += 2
                    continue
            elif character == delimiter:
                state = "code"
        index += 1
    return "".join(result)


def _validate_java_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "Strategy.java")
    java_sources = []
    for item in files:
        if not item.path.endswith(".java"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Java Team Source must be UTF-8: " + str(error),
            )
        significant_source = _java_significant_source(source)
        java_sources.append((item, significant_source))
        if re.search(r"(?m)^\s*package\s+", significant_source):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Java Team Source must use the organizer-owned default package",
            )
        if re.search(r"\bclass\s+RpsWrapper\b", significant_source):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned RpsWrapper class",
            )
        if re.search(r"\bstatic\s+void\s+main\s*\(", significant_source):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned main method",
            )

    strategy_source = _java_significant_source(source_file.content.decode("utf-8"))
    if len(re.findall(r"\bpublic\s+final\s+class\s+Strategy\b", strategy_source)) != 1:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "Strategy.java must define exactly one public final Strategy class",
        )
    signature = re.compile(
        r"\bpublic\s+static\s+String\s+chooseMove\s*\(\s*"
        r"int\s+turn\s*,\s*String\s+myHistory\s*,\s*"
        r"String\s+opponentHistory\s*,\s*RandomGenerator\s+rng\s*\)\s*\{"
    )
    bindings = sum(len(signature.findall(value)) for _, value in java_sources)
    if bindings != 1 or not signature.search(strategy_source):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one public static String chooseMove(int turn, "
            "String myHistory, String opponentHistory, RandomGenerator rng) method",
        )


def _java_significant_source(source: str) -> str:
    """Blank Java comments and literal contents while preserving line structure."""

    return _c_like_significant_source(source, raw_delimiters=('"""',))


def _validate_kotlin_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "Strategy.kt")
    kotlin_sources = []
    for item in files:
        if not item.path.endswith(".kt"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Kotlin Team Source must be UTF-8: " + str(error),
            )
        significant = _c_like_significant_source(source, raw_delimiters=('"""',))
        kotlin_sources.append((item, significant))
        if re.search(r"(?m)^\s*package\s+", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Kotlin Team Source must use the organizer-owned default package",
            )
        if re.search(r"\b(?:object|class)\s+RpsWrapper\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned RpsWrapper object",
            )
        if re.search(r"\bfun\s+main\s*\(", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned main function",
            )

    strategy = _c_like_significant_source(
        source_file.content.decode("utf-8"), raw_delimiters=('"""',)
    )
    if len(re.findall(r"\bobject\s+Strategy\b", strategy)) != 1:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "Strategy.kt must define exactly one Strategy object",
        )
    signature = re.compile(
        r"\bfun\s+chooseMove\s*\(\s*turn\s*:\s*Int\s*,\s*"
        r"myHistory\s*:\s*String\s*,\s*opponentHistory\s*:\s*String\s*,\s*"
        r"rng\s*:\s*RandomGenerator\s*\)\s*:\s*String\s*(?:=|\{)"
    )
    bindings = sum(
        len(
            re.findall(
                r"\b(?:fun|val|var|class|object)\s+chooseMove\b",
                significant_source,
            )
        )
        for _, significant_source in kotlin_sources
    )
    if bindings != 1 or not signature.search(strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one fun chooseMove(turn: Int, myHistory: String, "
            "opponentHistory: String, rng: RandomGenerator): String function",
        )


def _validate_csharp_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "Strategy.cs")
    sources = []
    for item in files:
        if not item.path.endswith(".cs"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "C# Team Source must be UTF-8: " + str(error),
            )
        significant = _c_like_significant_source(source, raw_delimiters=('"""',))
        sources.append((item, significant))
        if re.search(r"\bnamespace\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "C# Team Source must use the organizer-owned global namespace",
            )
        if re.search(r"\b(?:class|record|struct)\s+(?:Program|RpsWrapper|RpsRandom)\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define organizer-owned wrapper types",
            )
        if re.search(r"\bstatic\s+void\s+Main\s*\(", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned Main method",
            )

    strategy = _c_like_significant_source(
        source_file.content.decode("utf-8"), raw_delimiters=('"""',)
    )
    if len(re.findall(r"\bpublic\s+static\s+class\s+Strategy\b", strategy)) != 1:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "Strategy.cs must define exactly one public static Strategy class",
        )
    signature = re.compile(
        r"\bpublic\s+static\s+string\s+ChooseMove\s*\(\s*"
        r"int\s+turn\s*,\s*string\s+myHistory\s*,\s*"
        r"string\s+opponentHistory\s*,\s*RpsRandom\s+rng\s*\)\s*(?:=>|\{)"
    )
    bindings = sum(
        len(re.findall(r"\b(?:class|record|struct|string)\s+ChooseMove\b", value))
        for _, value in sources
    )
    if bindings != 1 or not signature.search(strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one public static string ChooseMove(int turn, string "
            "myHistory, string opponentHistory, RpsRandom rng) method",
        )


def _validate_typescript_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.ts")
    sources = []
    for item in files:
        if not item.path.endswith(".ts"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "TypeScript Team Source must be UTF-8: " + str(error),
            )
        significant = _c_like_significant_source(source, raw_delimiters=("`",))
        sources.append((item, significant))
        if re.search(r"\bprocess\s*\.\s*(?:stdin|stdout|stderr)\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not redefine organizer-owned wrapper I/O "
                "responsibilities",
            )

    strategy_source = _c_like_significant_source(
        source_file.content.decode("utf-8"), raw_delimiters=("`",)
    )
    signature = re.compile(
        r"\bexport\s+function\s+chooseMove\s*\(\s*"
        r"turn\s*:\s*number\s*,\s*myHistory\s*:\s*string\s*,\s*"
        r"opponentHistory\s*:\s*string\s*,\s*rng\s*:\s*\{\s*"
        r"nextInt\s*\(\s*(?:limit|upperExclusive)\s*:\s*number\s*\)\s*:\s*number\s*"
        r"\}\s*\)\s*:\s*string\s*\{"
    )
    bindings = sum(
        len(re.findall(r"\b(?:function|const|let|var|class)\s+chooseMove\b", value))
        for _, value in sources
    )
    if bindings != 1 or not signature.search(strategy_source):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one exported chooseMove(turn: number, myHistory: string, "
            "opponentHistory: string, rng: { nextInt(limit: number): number }): "
            "string function",
        )


def _validate_javascript_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.js")
    sources = []
    for item in files:
        if not item.path.endswith(".js"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "JavaScript Team Source must be UTF-8: " + str(error),
            )
        significant = _c_like_significant_source(source, raw_delimiters=("`",))
        sources.append((item, significant))
        if re.search(r"\bprocess\s*\.\s*(?:stdin|stdout|stderr)\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not redefine organizer-owned wrapper I/O "
                "responsibilities",
            )

    strategy_source = _c_like_significant_source(
        source_file.content.decode("utf-8"), raw_delimiters=("`",)
    )
    signature = re.compile(
        r"\bfunction\s+chooseMove\s*\(\s*turn\s*,\s*myHistory\s*,\s*"
        r"opponentHistory\s*,\s*rng\s*\)\s*\{"
    )
    bindings = sum(
        len(re.findall(r"\b(?:function|const|let|var|class)\s+chooseMove\b", value))
        for _, value in sources
    )
    exports = sum(
        len(
            re.findall(
                r"\bmodule\s*\.\s*exports\s*=\s*\{\s*chooseMove\s*\}\s*;?",
                value,
            )
        )
        for _, value in sources
    )
    if bindings != 1 or exports != 1 or not signature.search(strategy_source):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one function chooseMove(turn, myHistory, "
            "opponentHistory, rng) and export it with module.exports",
        )


def _validate_rust_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.rs")
    sources = []
    for item in files:
        if not item.path.endswith(".rs"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Rust Team Source must be UTF-8: " + str(error),
            )
        significant = _rust_significant_source(source)
        sources.append((item, significant))
        if re.search(r"\bfn\s+main\s*\(", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned main function",
            )
        if re.search(r"\b(?:struct|enum|type|trait)\s+RpsRandom\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned RpsRandom type",
            )

    strategy = _rust_significant_source(source_file.content.decode("utf-8"))
    signature = re.compile(
        r"\bpub\s+fn\s+choose_move\s*\(\s*_?turn\s*:\s*usize\s*,\s*"
        r"_?my_history\s*:\s*&str\s*,\s*_?opponent_history\s*:\s*&str\s*,\s*"
        r"_?rng\s*:\s*&mut\s+RpsRandom\s*\)\s*->\s*&\s*static\s+str\s*\{"
    )
    bindings = sum(
        len(re.findall(r"\b(?:fn|const|static|struct|enum|type|trait)\s+choose_move\b", value))
        for _, value in sources
    )
    if bindings != 1 or not signature.search(strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one pub fn choose_move(turn: usize, my_history: &str, "
            "opponent_history: &str, rng: &mut RpsRandom) -> &'static str function",
        )


def _validate_clojure_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.clj")
    sources = []
    for item in files:
        if not item.path.endswith(".clj"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Clojure Team Source must be UTF-8: " + str(error),
            )
        significant = _clojure_significant_source(source)
        sources.append((item, significant))
        if re.search(
            r"\(\s*(?:deftype|defrecord|definterface)\s+"
            r"(?:RpsRandom|RpsRandomApi)\b",
            significant,
        ):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define an organizer-owned random type",
            )
        if re.search(r"\(\s*defn\s+-main\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned -main entrypoint",
            )

    strategy = _clojure_significant_source(source_file.content.decode("utf-8"))
    if not re.search(r"\(\s*ns\s+strategy(?:\s|\))", strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "strategy.clj must declare the strategy namespace",
        )
    signature = re.compile(
        r"\(\s*defn\s+choose-move\s+\[\s*turn\s+my-history\s+"
        r"opponent-history\s+rng\s*\]"
    )
    bindings = sum(
        len(re.findall(r"\(\s*(?:defn|def|defmacro)\s+choose-move\b", value))
        for _, value in sources
    )
    if bindings != 1 or not signature.search(strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one (defn choose-move "
            "[turn my-history opponent-history rng] ...) function",
        )


def _clojure_significant_source(source: str) -> str:
    """Blank Clojure comments and strings while preserving form structure."""

    result = list(source)
    index = 0
    in_string = False
    escaped = False
    while index < len(source):
        character = source[index]
        if in_string:
            if character == '"' and not escaped:
                result[index] = " "
                in_string = False
            elif character != "\n":
                result[index] = " "
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            index += 1
            continue
        if character == ";":
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            for cursor in range(index, end):
                result[cursor] = " "
            index = end
            continue
        if character == '"':
            result[index] = " "
            in_string = True
        index += 1
    return "".join(result)


def _validate_ruby_strategy_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.rb")
    sources = []
    for item in files:
        if not item.path.endswith(".rb"):
            continue
        try:
            source = item.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Ruby Team Source must be UTF-8: " + str(error),
            )
        significant = _ruby_significant_source(source)
        sources.append((item, significant))
        if re.search(r"\bclass\s+RpsRandom\b", significant):
            raise SourceValidationError(
                item.path,
                "participant_contract",
                "Team Source must not define the organizer-owned RpsRandom class",
            )

    strategy = _ruby_significant_source(source_file.content.decode("utf-8"))
    signature = re.compile(
        r"\bdef\s+choose_move\s*\(\s*turn\s*,\s*my_history\s*,\s*"
        r"opponent_history\s*,\s*rng\s*\)"
    )
    bindings = sum(
        len(re.findall(r"\bdef\s+(?:self\.)?choose_move\b", value))
        for _, value in sources
    )
    if bindings != 1 or not signature.search(strategy):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define exactly one choose_move(turn, my_history, opponent_history, rng) method",
        )


def _ruby_significant_source(source: str) -> str:
    """Blank Ruby comments and quoted literals while preserving line structure."""

    result = list(source)
    index = 0
    quote = None
    escaped = False
    while index < len(source):
        if source.startswith("=begin", index) and (index == 0 or source[index - 1] == "\n"):
            end = source.find("\n=end", index + 6)
            end = len(source) if end == -1 else source.find("\n", end + 1)
            end = len(source) if end == -1 else end
            for cursor in range(index, end):
                if result[cursor] != "\n":
                    result[cursor] = " "
            index = end
            continue
        character = source[index]
        if quote:
            if character == quote and not escaped:
                result[index] = " "
                quote = None
            elif character != "\n":
                result[index] = " "
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            index += 1
            continue
        if character == "#":
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            for cursor in range(index, end):
                result[cursor] = " "
            index = end
            continue
        percent = re.match(r"%[qQwWiIxr]?(.)", source[index:])
        if percent and not percent.group(1).isalnum() and not percent.group(1).isspace():
            opener = percent.group(1)
            closer = {"(": ")", "[": "]", "{": "}", "<": ">"}.get(opener, opener)
            end = source.find(closer, index + len(percent.group(0)))
            end = len(source) if end == -1 else end + 1
            for cursor in range(index, end):
                if result[cursor] != "\n":
                    result[cursor] = " "
            index = end
            continue
        if character in ("'", '"'):
            result[index] = " "
            quote = character
        index += 1
    return "".join(result)


def _rust_significant_source(source: str) -> str:
    """Blank Rust comments and literals while preserving line structure."""

    result = list(source)
    index = 0
    block_depth = 0
    while index < len(source):
        following = source[index + 1] if index + 1 < len(source) else ""
        if block_depth:
            if source.startswith("/*", index):
                _blank_rust_range(result, index, index + 2)
                block_depth += 1
                index += 2
            elif source.startswith("*/", index):
                _blank_rust_range(result, index, index + 2)
                block_depth -= 1
                index += 2
            else:
                if source[index] != "\n":
                    result[index] = " "
                index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            _blank_rust_range(result, index, end)
            index = end
            continue
        if source.startswith("/*", index):
            _blank_rust_range(result, index, index + 2)
            block_depth = 1
            index += 2
            continue
        raw_end = _rust_raw_string_end(source, index)
        if raw_end is not None:
            _blank_rust_range(result, index, raw_end)
            index = raw_end
            continue
        string_start = index + 1 if source[index] == "b" and following == '"' else index
        if source[string_start : string_start + 1] == '"':
            end = _rust_escaped_literal_end(source, string_start, '"')
            _blank_rust_range(result, index, end)
            index = end
            continue
        quote_index = index + 1 if source[index] == "b" and following == "'" else index
        if source[quote_index : quote_index + 1] == "'":
            end = _rust_character_literal_end(source, quote_index)
            if end is not None:
                _blank_rust_range(result, index, end)
                index = end
                continue
            result[quote_index] = " "
        index += 1
    return "".join(result)


def _blank_rust_range(result: list[str], start: int, end: int) -> None:
    for index in range(start, min(end, len(result))):
        if result[index] != "\n":
            result[index] = " "


def _rust_raw_string_end(source: str, index: int) -> Optional[int]:
    cursor = index
    if source.startswith("br", cursor):
        cursor += 2
    elif source.startswith("r", cursor):
        cursor += 1
    else:
        return None
    hashes = 0
    while cursor < len(source) and source[cursor] == "#":
        hashes += 1
        cursor += 1
    if cursor >= len(source) or source[cursor] != '"':
        return None
    closing = '"' + ("#" * hashes)
    end = source.find(closing, cursor + 1)
    return len(source) if end == -1 else end + len(closing)


def _rust_escaped_literal_end(source: str, quote_index: int, quote: str) -> int:
    cursor = quote_index + 1
    escaped = False
    while cursor < len(source):
        character = source[cursor]
        if character == quote and not escaped:
            return cursor + 1
        if character == "\n" and not escaped:
            return cursor
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
        cursor += 1
    return len(source)


def _rust_character_literal_end(source: str, quote_index: int) -> Optional[int]:
    """Return the exclusive end of a Rust character literal, if present."""

    cursor = quote_index + 1
    if cursor >= len(source) or source[cursor] in "'\r\n":
        return None
    if source[cursor] == "\\":
        cursor += 1
        if cursor >= len(source) or source[cursor] in "\r\n":
            return None
        if source[cursor] == "x":
            cursor += 3
        elif source[cursor] == "u" and source[cursor + 1 : cursor + 2] == "{":
            closing_brace = source.find("}", cursor + 2)
            if closing_brace == -1:
                return None
            cursor = closing_brace + 1
        else:
            cursor += 1
    else:
        cursor += 1
    if cursor < len(source) and source[cursor] == "'":
        return cursor + 1
    return None


def _validate_python_function_contract(files: Sequence[SourceFile]) -> None:
    source_file = next(item for item in files if item.path == "strategy.py")
    try:
        tree = ast.parse(source_file.content, filename=source_file.path)
    except (SyntaxError, ValueError) as error:
        detail = getattr(error, "msg", str(error))
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "Python source is not valid syntax: " + detail,
        )
    bindings = list(_module_bindings(tree.body, "choose_move"))
    if not bindings:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "define a module-level choose_move callable that accepts four "
            "positional arguments",
        )
    if len(bindings) != 1 or not isinstance(bindings[0], ast.FunctionDef):
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "choose_move must have one unambiguous module-level function binding",
        )
    binding = bindings[0]
    if binding.decorator_list:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "choose_move decorators cannot be validated without executing Team code",
        )
    arguments = binding.args
    positional = list(arguments.posonlyargs) + list(arguments.args)
    required_positionals = len(positional) - len(arguments.defaults)
    accepts_four_positionals = (
        required_positionals <= 4
        and (len(positional) >= 4 or arguments.vararg is not None)
    )
    has_required_keyword_only = any(
        default is None for default in arguments.kw_defaults
    )
    if not accepts_four_positionals or has_required_keyword_only:
        raise SourceValidationError(
            source_file.path,
            "participant_contract",
            "choose_move must accept the wrapper's four positional arguments "
            "without requiring additional arguments",
        )


def _target_binds_name(target: ast.AST, name: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.List, ast.Tuple)):
        return any(_target_binds_name(item, name) for item in target.elts)
    return False


def _module_bindings(
    statements: Sequence[ast.stmt], name: str
) -> Iterable[ast.AST]:
    for node in statements:
        if not isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and _contains_module_named_expression(node, name):
            yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                yield node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_target_binds_name(target, name) for target in targets):
                yield node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name == name:
                    yield node
        elif isinstance(node, ast.Delete):
            if any(_target_binds_name(target, name) for target in node.targets):
                yield node
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if _target_binds_name(node.target, name):
                yield node
            yield from _module_bindings(node.body, name)
            yield from _module_bindings(node.orelse, name)
        elif isinstance(node, (ast.If, ast.While)):
            yield from _module_bindings(node.body, name)
            yield from _module_bindings(node.orelse, name)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None and _target_binds_name(
                    item.optional_vars, name
                ):
                    yield node
            yield from _module_bindings(node.body, name)
        elif isinstance(node, ast.Try):
            yield from _module_bindings(node.body, name)
            yield from _module_bindings(node.orelse, name)
            yield from _module_bindings(node.finalbody, name)
            for handler in node.handlers:
                if handler.name == name:
                    yield handler
                yield from _module_bindings(handler.body, name)


def _contains_module_named_expression(node: ast.AST, name: str) -> bool:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.NamedExpr) and _target_binds_name(child.target, name):
            return True
        if _contains_module_named_expression(child, name):
            return True
    return False


_PARTICIPANT_CONTRACT_VALIDATORS = {
    "clojure-strategy-contract-v1": _validate_clojure_strategy_contract,
    "csharp-strategy-contract-v1": _validate_csharp_strategy_contract,
    "go-strategy-contract-v1": _validate_go_strategy_contract,
    "java-strategy-contract-v1": _validate_java_strategy_contract,
    "javascript-strategy-contract-v1": _validate_javascript_strategy_contract,
    "kotlin-strategy-contract-v1": _validate_kotlin_strategy_contract,
    "rust-strategy-contract-v1": _validate_rust_strategy_contract,
    "ruby-strategy-contract-v1": _validate_ruby_strategy_contract,
    "typescript-strategy-contract-v1": _validate_typescript_strategy_contract,
    "none-v1": _validate_no_static_contract,
    "single-unconditional-function-v1": _validate_python_function_contract,
}


def source_digest(files: Sequence[SourceFile]) -> str:
    digest = hashlib.sha256()
    digest.update((BUNDLE_FORMAT_VERSION + "\0").encode("utf-8"))
    for item in files:
        path = item.path.encode("utf-8")
        digest.update(len(path).to_bytes(8, "big"))
        digest.update(path)
        digest.update(len(item.content).to_bytes(8, "big"))
        digest.update(item.content)
    return "sha256:" + digest.hexdigest()


def environment_identity_manifest(
    catalog: LanguageEnvironmentCatalog, environment: LanguageEnvironment
) -> Mapping[str, str]:
    assets = environment.assets
    return {
        "catalog": catalog.identity,
        "descriptor": environment.descriptor_identity,
        "source_schema": environment.source_schema.identity,
        "wrapper": assets["wrapper"].identity,
        "recipe": assets["recipe"].identity,
        "entrypoint": assets["entrypoint"].identity,
        "dependency_definition": assets["dependency_definition"].identity,
        "build_target": assets["build_target"].identity,
        "workflow": assets["workflow"].identity,
        "readiness": assets["readiness"].identity,
        "base_runtime": assets["base_runtime"].identity,
        "build_toolchain": assets["build_toolchain"].identity,
        "platform": assets["platform"].identity,
        "conformance": assets["conformance"].identity,
    }


def materialize_source_files(
    files: Sequence[SourceFile], destination: Path
) -> None:
    destination.mkdir()
    for item in files:
        output = destination / PurePosixPath(item.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(item.content)
        output.chmod(0o444)
    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o555)
    destination.chmod(0o555)


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
    result = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "catalog_digest": catalog.digest,
        "contract_only": environment.contract_only,
        "environment": environment.name,
        "files": [item.path for item in files],
        "participant_contract": environment.participant_contract.as_manifest(),
        "source_digest": source_digest(files),
        "versions": environment_identity_manifest(catalog, environment),
    }

    bundle.parent.mkdir(parents=True, exist_ok=True)
    created_bundle = False
    try:
        bundle.mkdir()
        created_bundle = True
        source_output = bundle / "source"
        materialize_source_files(files, source_output)
        manifest = bundle / "source-bundle.json"
        manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        manifest.chmod(0o444)
        bundle.chmod(0o555)
    except BaseException:
        if created_bundle:
            for path in bundle.rglob("*"):
                if path.is_dir():
                    path.chmod(0o755)
                else:
                    path.chmod(0o644)
            bundle.chmod(0o755)
            shutil.rmtree(bundle)
        raise
    return result


def load_frozen_source_bundle(
    bundle: Path, catalog: LanguageEnvironmentCatalog
) -> FrozenSourceBundle:
    manifest_path = bundle / "source-bundle.json"
    if bundle.is_symlink() or not bundle.is_dir():
        raise SourceValidationError(
            str(bundle), "frozen_bundle", "validated source bundle is not a directory"
        )
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle",
            "validated source bundle manifest is missing or is not a regular file",
        )
    try:
        manifest_value = json.loads(manifest_path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle",
            "could not read a valid source bundle manifest: " + str(error),
        )
    if not isinstance(manifest_value, dict):
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle",
            "source bundle manifest must be an object",
        )
    environment_name = manifest_value.get("environment")
    if not isinstance(environment_name, str):
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle",
            "source bundle manifest has no valid Language Environment",
        )
    environment = catalog.environment(environment_name)
    expected_values = {
        "bundle_format_version": BUNDLE_FORMAT_VERSION,
        "catalog_digest": catalog.digest,
        "contract_only": environment.contract_only,
        "participant_contract": environment.participant_contract.as_manifest(),
        "versions": environment_identity_manifest(catalog, environment),
    }
    for key, expected in expected_values.items():
        if manifest_value.get(key) != expected:
            raise SourceValidationError(
                "source-bundle.json",
                "frozen_bundle_identity",
                "source bundle " + key + " does not match the selected frozen catalog",
            )
    source_path = bundle / "source"
    files = validate_source(source_path, environment)
    if manifest_value.get("files") != [item.path for item in files]:
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle_identity",
            "source bundle file list does not match its frozen source",
        )
    actual_digest = source_digest(files)
    if manifest_value.get("source_digest") != actual_digest:
        raise SourceValidationError(
            "source-bundle.json",
            "frozen_bundle_identity",
            "source digest does not match the frozen source bytes",
        )
    return FrozenSourceBundle(
        path=bundle,
        source_path=source_path,
        manifest=manifest_value,
        environment=environment,
        files=files,
    )
