from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile
import time
from typing import Any, Mapping, Sequence
import uuid

from rps_runner.language_environment import (
    FrozenSourceBundle,
    LanguageEnvironmentCatalog,
    load_frozen_source_bundle,
    materialize_source_files,
)


ARTIFACT_CANDIDATE_FORMAT_VERSION = "artifact-candidate-v1"
BUILD_FORMAT_VERSION = "build-v1"
CORE_TOOL_VERSION = "rps-core-tool-v1"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_DIAGNOSTICS_BYTES = 65536
MAX_TIMEOUT_SECONDS = 3600.0
MAX_DIAGNOSTICS_BYTES = 1048576
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLATFORM = re.compile(r"^linux/(amd64|arm64)$")


class ArtifactBuildFailure(ValueError):
    """A non-competitive failure while producing a Bot Artifact candidate."""

    def __init__(self, explanation: str, diagnostics: str = "") -> None:
        super().__init__(explanation)
        self.diagnostics = diagnostics


@dataclass(frozen=True)
class RuntimeIdentity:
    reference: str
    digest: str
    identity: str

    def as_manifest(self) -> Mapping[str, str]:
        return {
            "reference": self.reference,
            "digest": self.digest,
            "identity": self.identity,
        }


def _canonical_identity(version: str, value: Any) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return version + "@sha256:" + hashlib.sha256(content).hexdigest()


def _core_tool_identity() -> str:
    digest = hashlib.sha256()
    package = Path(__file__).resolve().parent
    for name in ("artifact_builder.py", "artifact_cli.py", "language_environment.py"):
        content = (package / name).read_bytes()
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return CORE_TOOL_VERSION + "@sha256:" + digest.hexdigest()


def _read_json(content: bytes, description: str) -> Mapping[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactBuildFailure("could not read " + description + ": " + str(error))
    if not isinstance(value, dict):
        raise ArtifactBuildFailure(description + " must be a JSON object")
    return value


def _runtime_for(bundle: FrozenSourceBundle, platform: str) -> RuntimeIdentity:
    if not _PLATFORM.fullmatch(platform):
        raise ArtifactBuildFailure(
            "target platform "
            + repr(platform)
            + " is unsupported; expected linux/amd64 or linux/arm64"
        )
    data = _read_json(
        bundle.environment.assets["base_runtime"].content,
        "organizer-owned base runtime definition",
    )
    platforms = data.get("platforms")
    if not isinstance(platforms, dict) or not isinstance(platforms.get(platform), dict):
        raise ArtifactBuildFailure(
            "target platform " + repr(platform) + " has no pinned base runtime"
        )
    selected = platforms[platform]
    reference = selected.get("image")
    version = selected.get("version")
    if not isinstance(reference, str) or "@" not in reference:
        raise ArtifactBuildFailure(
            "selected base runtime is not referenced by immutable digest"
        )
    digest = reference.rsplit("@", 1)[1]
    if not _DIGEST.fullmatch(digest) or not isinstance(version, str) or not version:
        raise ArtifactBuildFailure("selected base runtime identity is invalid or mutable")
    return RuntimeIdentity(
        reference=reference,
        digest=digest,
        identity=version + "@" + digest,
    )


def _entrypoint(bundle: FrozenSourceBundle) -> Sequence[str]:
    data = _read_json(
        bundle.environment.assets["entrypoint"].content, "organizer-owned entrypoint"
    )
    argv = data.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) for item in argv)
    ):
        raise ArtifactBuildFailure("organizer-owned entrypoint argv is invalid")
    return tuple(argv)


def _bounded_command(
    arguments: Sequence[str], timeout_seconds: float, maximum_bytes: int
) -> tuple[int, bytes]:
    try:
        process = subprocess.Popen(
            list(arguments), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
    except OSError as error:
        raise ArtifactBuildFailure("could not start Docker CLI: " + str(error))
    assert process.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + timeout_seconds
    failure: str | None = None
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = (
                    "Docker operation timed out after "
                    + str(timeout_seconds)
                    + " seconds"
                )
                break
            events = selector.select(min(remaining, 0.1))
            for key, _ in events:
                chunk = os.read(key.fd, min(8192, maximum_bytes + 1 - len(output)))
                if not chunk:
                    selector.unregister(process.stdout)
                    continue
                output.extend(chunk)
                if len(output) > maximum_bytes:
                    failure = (
                        "Docker output exceeded the limit of "
                        + str(maximum_bytes)
                        + " bytes"
                    )
                    break
            if failure is not None:
                break
            if process.poll() is not None and not selector.get_map():
                break
        if failure is not None:
            process.kill()
            process.wait()
            raise ArtifactBuildFailure(
                failure, bytes(output[:maximum_bytes]).decode("utf-8", errors="replace")
            )
        return process.wait(), bytes(output)
    finally:
        selector.close()
        process.stdout.close()


def _docker_json(arguments: Sequence[str], timeout_seconds: float) -> Any:
    code, output = _bounded_command(
        arguments, timeout_seconds, DEFAULT_MAX_DIAGNOSTICS_BYTES
    )
    diagnostics = output.decode("utf-8", errors="replace")
    if code != 0:
        raise ArtifactBuildFailure(
            "Docker CLI failed with exit code " + str(code), diagnostics
        )
    try:
        return json.loads(output)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactBuildFailure(
            "Docker CLI returned invalid inspection data: " + str(error), diagnostics
        )


def _inspect_one(reference: str, timeout_seconds: float) -> Mapping[str, Any]:
    value = _docker_json(["docker", "image", "inspect", reference], timeout_seconds)
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ArtifactBuildFailure(
            "Docker image inspection did not resolve exactly one image"
        )
    return value[0]


def _verify_platform(details: Mapping[str, Any], platform: str, subject: str) -> None:
    observed = str(details.get("Os", "")) + "/" + str(details.get("Architecture", ""))
    if observed != platform:
        raise ArtifactBuildFailure(
            subject
            + " has wrong platform "
            + repr(observed)
            + "; expected "
            + repr(platform)
        )


def _verify_runtime(
    runtime: RuntimeIdentity, platform: str, timeout_seconds: float
) -> None:
    details = _inspect_one(runtime.reference, timeout_seconds)
    _verify_platform(details, platform, "pinned base runtime")
    repo_digests = details.get("RepoDigests")
    if not isinstance(repo_digests, list) or not any(
        isinstance(item, str) and item.endswith("@" + runtime.digest)
        for item in repo_digests
    ):
        raise ArtifactBuildFailure(
            "local base runtime does not verify against pinned digest " + runtime.digest
        )


def _write_frozen_candidate(
    staging: Path,
    bundle: FrozenSourceBundle,
    manifest: Mapping[str, Any],
    diagnostics: bytes,
) -> None:
    materialize_source_files(bundle.files, staging / "source")
    (staging / "source-bundle.json").write_text(
        json.dumps(bundle.manifest, indent=2, sort_keys=True) + "\n"
    )
    (staging / "build.log").write_bytes(diagnostics)
    (staging / "artifact-candidate.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    for path in staging.rglob("*"):
        path.chmod(0o555 if path.is_dir() else 0o444)
    staging.chmod(0o555)


def build_artifact_candidate(
    bundle_path: Path,
    candidate: Path,
    catalog: LanguageEnvironmentCatalog,
    platform: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_diagnostics_bytes: int = DEFAULT_MAX_DIAGNOSTICS_BYTES,
) -> Mapping[str, Any]:
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ArtifactBuildFailure(
            "build timeout must be finite, positive, and no greater than "
            + str(MAX_TIMEOUT_SECONDS)
            + " seconds"
        )
    if not 0 < maximum_diagnostics_bytes <= MAX_DIAGNOSTICS_BYTES:
        raise ArtifactBuildFailure(
            "diagnostics limit must be positive and no greater than "
            + str(MAX_DIAGNOSTICS_BYTES)
            + " bytes"
        )
    if candidate.exists() or candidate.is_symlink():
        raise ArtifactBuildFailure(
            "candidate destination already exists and will not be replaced"
        )
    bundle = load_frozen_source_bundle(bundle_path, catalog)
    if bundle.environment.contract_only:
        raise ArtifactBuildFailure(
            "contract-only Language Environment cannot build a Bot Artifact"
        )
    runtime = _runtime_for(bundle, platform)
    entrypoint = _entrypoint(bundle)
    _verify_runtime(runtime, platform, timeout_seconds)

    candidate.parent.mkdir(parents=True, exist_ok=True)
    image_reference = "rps-tournament-candidate:" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(
        prefix="rps-build-", dir=str(candidate.parent)
    ) as work_name:
        work = Path(work_name)
        team = work / "team-context"
        materialize_source_files(bundle.files, team)
        organizer = work / "organizer-context"
        (organizer / "organizer").mkdir(parents=True)
        (organizer / "organizer" / "wrapper.py").write_bytes(
            bundle.environment.assets["wrapper"].content
        )
        recipe = organizer / "Dockerfile"
        recipe.write_bytes(bundle.environment.assets["recipe"].content)
        iid_file = work / "image-id"
        metadata_file = work / "metadata.json"
        arguments = [
            "docker",
            "build",
            "--network=none",
            "--pull=false",
            "--platform",
            platform,
            "--build-arg",
            "RPS_BASE_RUNTIME=" + runtime.reference,
            "--build-context",
            "team=" + str(team),
            "--iidfile",
            str(iid_file),
            "--metadata-file",
            str(metadata_file),
            "--tag",
            image_reference,
            "--file",
            str(recipe),
            str(organizer),
        ]
        code, diagnostics = _bounded_command(
            arguments, timeout_seconds, maximum_diagnostics_bytes
        )
        if code != 0:
            raise ArtifactBuildFailure(
                "Docker build failed with exit code " + str(code),
                diagnostics.decode("utf-8", errors="replace"),
            )
        try:
            image_id = iid_file.read_text().strip()
            metadata = _read_json(metadata_file.read_bytes(), "Docker build metadata")
        except OSError as error:
            raise ArtifactBuildFailure(
                "Docker build did not record image identity: " + str(error)
            )
        artifact_digest = metadata.get("containerimage.digest")
        if not isinstance(artifact_digest, str) or not _DIGEST.fullmatch(
            artifact_digest
        ):
            raise ArtifactBuildFailure(
                "Docker build did not produce an exact image manifest digest"
            )
        if not _DIGEST.fullmatch(image_id):
            raise ArtifactBuildFailure("Docker build did not produce an exact local image ID")
        details = _inspect_one(image_reference, timeout_seconds)
        _verify_platform(details, platform, "built Bot Artifact candidate")
        if details.get("Id") != image_id:
            raise ArtifactBuildFailure("built image identity does not match Docker build output")
        config = details.get("Config")
        if not isinstance(config, dict) or config.get("Entrypoint") != list(entrypoint):
            raise ArtifactBuildFailure("built image entrypoint does not match the frozen catalog")

        identities = {
            "catalog": catalog.identity,
            "core_tool": _core_tool_identity(),
            "entrypoint": bundle.environment.assets["entrypoint"].identity,
            "language_environment": bundle.environment.descriptor_identity,
            "platform": bundle.environment.assets["platform"].identity,
            "recipe": bundle.environment.assets["recipe"].identity,
            "suite_candidate": bundle.environment.assets["conformance"].identity,
            "wrapper": bundle.environment.assets["wrapper"].identity,
        }
        build_inputs = {
            "artifact_digest": artifact_digest,
            "identities": identities,
            "language": bundle.environment.language,
            "platform": platform,
            "runtime_identity": runtime.identity,
            "source_digest": bundle.manifest["source_digest"],
        }
        manifest = {
            "artifact_candidate_format_version": ARTIFACT_CANDIDATE_FORMAT_VERSION,
            "status": "suite-candidate",
            "source_digest": bundle.manifest["source_digest"],
            "artifact_digest": artifact_digest,
            "build_identity": _canonical_identity(BUILD_FORMAT_VERSION, build_inputs),
            "runtime_digest": runtime.digest,
            "runtime": runtime.as_manifest(),
            "language": bundle.environment.language,
            "platform": platform,
            "entrypoint": list(entrypoint),
            "identities": identities,
            "image": {
                "manifest_digest": artifact_digest,
                "local_image_id": image_id,
            },
            "retention": {
                "authority": artifact_digest,
                "local_image_id": image_id,
                "local_image_reference": image_reference,
                "store": "active-docker-context",
            },
            "diagnostics": {
                "bytes": len(diagnostics),
                "file": "build.log",
                "limit_bytes": maximum_diagnostics_bytes,
            },
        }
        staging = Path(
            tempfile.mkdtemp(prefix="rps-candidate-", dir=str(candidate.parent))
        )
        try:
            _write_frozen_candidate(staging, bundle, manifest, diagnostics)
            os.replace(staging, candidate)
        except BaseException:
            if staging.exists():
                for path in staging.rglob("*"):
                    path.chmod(0o755 if path.is_dir() else 0o644)
                staging.chmod(0o755)
                shutil.rmtree(staging)
            raise
        return manifest
