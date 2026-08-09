from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Iterator, Literal, Mapping, Optional

from rps_runner.artifact_builder import ArtifactBuildFailure, build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationFailure,
    CertificationInputs,
    certify_artifact_candidate,
)
from rps_runner.artifact_store import (
    ArtifactSelection,
    ArtifactStoreIntegrityError,
    preserve_artifact_set,
    resolve_artifact,
)
from rps_runner.engine.container_session import CONTAINER_ISOLATION_PROFILE_VERSION
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.host_readiness import (
    DEFAULT_MINIMUM_FREE_DISK_BYTES,
    HostReadinessRequest,
    diagnose_host_readiness,
    runtime_references,
)
from rps_runner.language_environment import (
    CatalogError,
    SourceValidationError,
    freeze_source_bundle,
    load_catalog,
)


PREPARATION_REPORT_FORMAT_VERSION = "rps-preparation-report-v1"


class PreparationFailure(ValueError):
    """An organizer preparation failure with an explicit recovery disposition."""

    def __init__(
        self,
        disposition: Literal["retry", "catalog_correction", "organizer_intervention"],
        explanation: str,
    ) -> None:
        super().__init__(explanation)
        self.disposition = disposition

    def as_mapping(self) -> Mapping[str, object]:
        return {
            "status": "failed",
            "disposition": self.disposition,
            "can_retry": self.disposition == "retry",
            "can_retry_after_correction": self.disposition == "catalog_correction",
            "requires_organizer_intervention": self.disposition
            == "organizer_intervention",
            "team_fault": False,
            "detail": str(self),
        }


class PreparationArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise PreparationFailure("organizer_intervention", message)


@contextmanager
def _writable_temporary_directory(parent: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(
        prefix="rps-prepare-", dir=str(parent)
    ) as temporary_name:
        root = Path(temporary_name)
        try:
            yield root
        finally:
            for path in root.rglob("*"):
                path.chmod(0o755 if path.is_dir() else 0o644)
            root.chmod(0o755)


def _discard_generated_store(store: Path) -> None:
    """Roll back only the previously absent store created by this invocation."""
    if not store.exists() or store.is_symlink():
        return
    for path in store.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    store.chmod(0o755)
    shutil.rmtree(store)


def build_parser() -> argparse.ArgumentParser:
    parser = PreparationArgumentParser(
        prog="rps-prepare",
        description="Prepare an explicit frozen organizer configuration for offline use",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--platform", required=True, choices=("linux/arm64", "linux/amd64")
    )
    parser.add_argument("--profile", required=True)
    parser.add_argument("--artifact-store", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--parallelism",
        type=int,
        default=INITIAL_EXECUTION_PROFILE.recommended_match_parallelism,
    )
    parser.add_argument("--expected-context")
    parser.add_argument("--allow-pull", action="store_true")
    parser.add_argument(
        "--minimum-free-disk-bytes",
        type=int,
        default=DEFAULT_MINIMUM_FREE_DISK_BYTES,
    )
    return parser


def _validate_options(options: argparse.Namespace) -> None:
    if "latest" in options.profile.lower():
        raise ValueError("profile selection refuses mutable latest")
    if options.profile != CONTAINER_ISOLATION_PROFILE_VERSION:
        raise ValueError(
            "profile must be the explicit published profile "
            + repr(CONTAINER_ISOLATION_PROFILE_VERSION)
        )
    if options.parallelism <= 0:
        raise ValueError("parallelism must be a positive integer")
    if options.minimum_free_disk_bytes < 0:
        raise ValueError("minimum free disk bytes must be non-negative")
    if options.artifact_store.exists() or options.artifact_store.is_symlink():
        raise ValueError("artifact store destination already exists and will not be replaced")
    if options.report.exists() or options.report.is_symlink():
        raise ValueError("readiness report destination already exists and will not be replaced")
    store = options.artifact_store.expanduser().resolve()
    report = options.report.expanduser().resolve()
    if report == store or store in report.parents:
        raise ValueError("readiness report must be outside the read-only artifact store")


def _docker(arguments: list[str], *, timeout: float = 300) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["docker", *arguments], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreparationFailure("retry", "Docker operation could not run: " + str(error)) from error


def _ensure_pinned_runtimes(
    catalog: object, platform: str, allow_pull: bool
) -> list[str]:
    references = runtime_references(catalog, platform)
    for reference in references:
        inspected = _docker(["image", "inspect", reference], timeout=10)
        if inspected.returncode == 0:
            continue
        diagnostic = inspected.stderr.decode("utf-8", errors="replace").lower()
        missing = "no such image" in diagnostic or "no such object" in diagnostic
        if not missing:
            raise PreparationFailure(
                "retry", "Pinned runtime inspection failed: " + diagnostic.strip()
            )
        if not allow_pull:
            raise PreparationFailure(
                "retry",
                "Pinned runtime is absent; rerun with --allow-pull while network access is allowed: "
                + reference,
            )
        pulled = _docker(["pull", "--platform", platform, reference])
        if pulled.returncode != 0:
            raise PreparationFailure(
                "retry",
                "Pinned runtime pull failed: "
                + pulled.stderr.decode("utf-8", errors="replace").strip(),
            )
        verified = _docker(["image", "inspect", reference], timeout=10)
        if verified.returncode != 0:
            raise PreparationFailure(
                "retry", "Pinned runtime remained unavailable after its explicit pull"
            )
    return references


def _verify_engine_selection(
    platform: str, expected_context: Optional[str]
) -> Mapping[str, object]:
    context_result = _docker(["context", "show"], timeout=10)
    if context_result.returncode != 0:
        raise PreparationFailure("retry", "Active Docker context is unavailable")
    context = context_result.stdout.decode("utf-8", errors="replace").strip()
    if expected_context is not None and context != expected_context:
        raise PreparationFailure(
            "organizer_intervention",
            "Active Docker context "
            + repr(context)
            + " does not match explicit context "
            + repr(expected_context),
        )
    info_result = _docker(["info", "--format", "{{json .}}"], timeout=10)
    if info_result.returncode != 0:
        raise PreparationFailure("retry", "Docker server information is unavailable")
    try:
        info = json.loads(info_result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreparationFailure("retry", "Docker returned invalid server information") from error
    if not isinstance(info, dict):
        raise PreparationFailure("retry", "Docker returned invalid server information")
    architecture = {
        "aarch64": "arm64",
        "x86_64": "amd64",
    }.get(str(info.get("Architecture", "")).lower(), str(info.get("Architecture", "")).lower())
    observed = str(info.get("OSType", "")) + "/" + architecture
    if observed != platform:
        raise PreparationFailure(
            "organizer_intervention",
            "Docker server is native " + repr(observed) + ", requested " + repr(platform),
        )
    return {"context": context, "platform": observed}


def _remove_preparation_image(reference: str) -> None:
    completed = _docker(["image", "rm", reference], timeout=30)
    if completed.returncode != 0:
        raise PreparationFailure(
            "retry",
            "Could not remove the preparation-owned image before archive restore: "
            + completed.stderr.decode("utf-8", errors="replace").strip(),
        )


def prepare_offline_inputs(
    *,
    catalog: object,
    platform: str,
    profile: str,
    artifact_store: Path,
    allow_pull: bool,
) -> Mapping[str, object]:
    """Build and retain organizer-owned evidence using only pinned inputs."""
    runtime_references = _ensure_pinned_runtimes(catalog, platform, allow_pull)
    artifact_store.parent.mkdir(parents=True, exist_ok=True)
    with _writable_temporary_directory(artifact_store.parent) as work:
        source = work / "representative-source"
        source.mkdir()
        (source / "strategy.py").write_text(
            "def choose_move(history, seed=None):\n    return 'rock'\n"
        )
        bundle = work / "representative-bundle"
        freeze_source_bundle(source, bundle, catalog, catalog.environment("python"))
        candidate = work / "representative-candidate"
        candidate_manifest = build_artifact_candidate(
            bundle, candidate, catalog, platform
        )
        certification = work / "representative-certification"
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        certification_result = certify_artifact_candidate(
            candidate,
            certification,
            catalog,
            CertificationInputs(mode, platform, profile),
            retain_practice_images=True,
        )
        report = certification_result["report"]
        if not isinstance(report, dict):
            raise PreparationFailure("retry", "Certification returned no validation report")
        index = preserve_artifact_set(
            artifact_store, [ArtifactSelection(candidate, certification)]
        )
        retention = candidate_manifest["retention"]
        if not isinstance(retention, dict):
            raise PreparationFailure("retry", "Builder omitted image retention metadata")
        image_reference = str(retention["local_image_reference"])
        image_id = str(retention["local_image_id"])
        artifact_digest = str(candidate_manifest["artifact_digest"])
        _remove_preparation_image(image_reference)
        restore_telemetry: dict[str, object] = {}
        restored = resolve_artifact(
            artifact_store,
            artifact_digest,
            platform,
            operational_telemetry=restore_telemetry,
        )
        if restored != image_id or restore_telemetry.get("archive_restored") is not True:
            raise PreparationFailure(
                "retry", "Verified archive restore did not restore the exact prepared image"
            )
        smoke = report.get("smoke_match")
        practices = smoke.get("practice_artifacts") if isinstance(smoke, dict) else None
        if not isinstance(practices, dict):
            raise PreparationFailure("retry", "Certification omitted practice Bot Artifacts")
        practice_images = {
            name: str(value["cached_image_id"])
            for name, value in practices.items()
            if isinstance(name, str)
            and isinstance(value, dict)
            and isinstance(value.get("cached_image_id"), str)
        }
        if set(practice_images) != {"fixed-move", "random", "copycat", "protocol-test"}:
            raise PreparationFailure(
                "retry", "Certification did not retain every practice Bot Artifact"
            )
        return {
            "organizer_images": [image_id],
            "runtime_references": runtime_references,
            "practice_artifacts": dict(sorted(practice_images.items())),
            "artifact_digest": artifact_digest,
            "artifact_image_id": image_id,
            "validation_identity": report["validation_identity"],
            "offline_checks": {
                "networkless_rebuild": "passed",
                "readiness_handshake": "passed",
                "isolation_profile": "passed",
                "artifact_archive": "passed",
                "artifact_restore": "passed",
            },
            "artifact_store_identity": index["integrity"]["index_identity"],
        }


def run(arguments: Optional[list[str]] = None) -> dict[str, object]:
    options = build_parser().parse_args(arguments)
    _validate_options(options)
    catalog_path = options.catalog.expanduser().resolve()
    artifact_store = options.artifact_store.expanduser().resolve()
    report_path = options.report.expanduser().resolve()
    started = time.monotonic()
    try:
        catalog = load_catalog(catalog_path)
        _verify_engine_selection(options.platform, options.expected_context)
        prepared = prepare_offline_inputs(
            catalog=catalog,
            platform=options.platform,
            profile=options.profile,
            artifact_store=artifact_store,
            allow_pull=options.allow_pull,
        )
    except PreparationFailure:
        _discard_generated_store(artifact_store)
        raise
    except (CatalogError, SourceValidationError) as error:
        _discard_generated_store(artifact_store)
        raise PreparationFailure("catalog_correction", str(error)) from error
    except (ArtifactBuildFailure, CertificationFailure, ArtifactStoreIntegrityError) as error:
        _discard_generated_store(artifact_store)
        raise PreparationFailure("retry", str(error)) from error
    except BaseException:
        _discard_generated_store(artifact_store)
        raise

    try:
        return _finalize_preparation(
            options=options,
            catalog=catalog,
            catalog_path=catalog_path,
            artifact_store=artifact_store,
            report_path=report_path,
            started=started,
            prepared=prepared,
        )
    except BaseException:
        _discard_generated_store(artifact_store)
        raise


def _finalize_preparation(
    *,
    options: argparse.Namespace,
    catalog: object,
    catalog_path: Path,
    artifact_store: Path,
    report_path: Path,
    started: float,
    prepared: Mapping[str, object],
) -> dict[str, object]:
    practices = prepared["practice_artifacts"]
    assert isinstance(practices, dict)
    doctor_request = HostReadinessRequest(
        catalog=catalog_path,
        platform=options.platform,
        artifact_store=artifact_store,
        parallelism=options.parallelism,
        minimum_free_disk_bytes=options.minimum_free_disk_bytes,
        expected_context=options.expected_context,
        organizer_images=tuple(str(value) for value in prepared["organizer_images"]),
        practice_artifacts=tuple(
            (str(name), str(reference))
            for name, reference in sorted(practices.items())
        ),
    )
    doctor = diagnose_host_readiness(doctor_request)
    if not doctor.get("ready"):
        raise PreparationFailure(
            "organizer_intervention",
            "Preparation completed but doctor did not accept the prepared configuration",
        )
    elapsed = round(time.monotonic() - started, 6)
    docker = doctor["docker"]
    machine = doctor["machine"]
    doctor_arguments = [
        "--catalog",
        str(catalog_path),
        "--platform",
        options.platform,
        "--artifact-store",
        str(artifact_store),
        "--parallelism",
        str(options.parallelism),
        "--minimum-free-disk-bytes",
        str(options.minimum_free_disk_bytes),
    ]
    if options.expected_context is not None:
        doctor_arguments.extend(["--expected-context", options.expected_context])
    for reference in prepared["organizer_images"]:
        doctor_arguments.extend(["--organizer-layer", str(reference)])
    for name, reference in sorted(practices.items()):
        doctor_arguments.extend(
            ["--practice-artifact", str(name) + "=" + str(reference)]
        )
    result: dict[str, object] = {
        "preparation_report_format_version": PREPARATION_REPORT_FORMAT_VERSION,
        "status": "passed",
        "mode": "fast",
        "machine_identity": machine["identity"],
        "machine": machine,
        "engine_identity": docker["engine_identity"],
        "docker_context": docker["context"],
        "docker_version": docker["server_version"],
        "docker": {
            "context": docker["context"],
            "engine_identity": docker["engine_identity"],
            "server_name": docker.get("server_name"),
            "server_platform": docker.get("server_platform"),
            "server_version": docker["server_version"],
        },
        "platform": options.platform,
        "catalog_identity": catalog.identity,
        "catalog": {"path": str(catalog_path), "identity": catalog.identity},
        "profile_identity": INITIAL_EXECUTION_PROFILE.identity,
        "profile": {
            "version": options.profile,
            "identity": INITIAL_EXECUTION_PROFILE.identity,
        },
        "resource_values": dict(INITIAL_EXECUTION_PROFILE.as_mapping()),
        "parallelism": options.parallelism,
        "artifact_store": {
            "path": str(artifact_store),
            "identity": prepared["artifact_store_identity"],
        },
        "cached_identities": {
            "pinned_runtimes": prepared.get("runtime_references", []),
            "organizer_images": prepared["organizer_images"],
            "practice_artifacts": practices,
            "representative_artifact": prepared["artifact_digest"],
            "validation": prepared["validation_identity"],
        },
        "offline_checks": prepared["offline_checks"],
        "doctor": {
            "report_format_version": doctor.get("report_format_version"),
            "status": doctor["status"],
            "consistent": True,
            "arguments": doctor_arguments,
        },
        "elapsed_seconds": elapsed,
        "full_rehearsal": {
            "status": "not_run",
            "operation": "rps-rehearse --parallelism " + str(options.parallelism),
        },
        "mutation_policy": {
            "host_or_engine_settings_changed": False,
            "unrelated_images_deleted": False,
            "cache_pruned": False,
            "docker_installed": False,
        },
    }
    report_created = False
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("x") as stream:
            report_created = True
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except BaseException:
        if report_created:
            report_path.unlink(missing_ok=True)
        raise
    return result


def main(arguments: Optional[list[str]] = None) -> int:
    try:
        report = run(arguments)
    except PreparationFailure as error:
        print("rps-prepare: " + json.dumps(error.as_mapping(), sort_keys=True), file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        failure = PreparationFailure("organizer_intervention", str(error))
        print("rps-prepare: " + json.dumps(failure.as_mapping(), sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
