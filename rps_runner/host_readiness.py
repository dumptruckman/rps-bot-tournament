from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
from typing import Any, Literal, Mapping, Optional, Sequence

from rps_runner.artifact_store import verify_artifact_store
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import CatalogError, load_catalog


HOST_READINESS_REPORT_FORMAT_VERSION = "container-host-readiness-v1"
REHEARSAL_REPORT_FORMAT_VERSION = "rps-rehearsal-report-v1"
DEFAULT_MINIMUM_FREE_DISK_BYTES = 10 * 1024**3
_PLATFORMS = ("linux/arm64", "linux/amd64")
_IMMUTABLE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def _is_immutable_image_reference(value: str) -> bool:
    digest = value.rsplit("@", 1)[-1]
    return _IMMUTABLE_DIGEST.fullmatch(digest) is not None


@dataclass(frozen=True)
class HostReadinessRequest:
    catalog: Path
    platform: str
    artifact_store: Path
    parallelism: int = INITIAL_EXECUTION_PROFILE.recommended_match_parallelism
    minimum_free_disk_bytes: int = DEFAULT_MINIMUM_FREE_DISK_BYTES
    expected_context: Optional[str] = None
    organizer_images: tuple[str, ...] = ()
    practice_artifacts: tuple[tuple[str, str], ...] = ()
    rehearsal_evidence: Optional[Path] = None

    def validate(self) -> None:
        if self.platform not in _PLATFORMS:
            raise ValueError("platform must be linux/arm64 or linux/amd64")
        if (
            not isinstance(self.parallelism, int)
            or isinstance(self.parallelism, bool)
            or self.parallelism <= 0
        ):
            raise ValueError("parallelism must be a positive integer")
        if (
            not isinstance(self.minimum_free_disk_bytes, int)
            or isinstance(self.minimum_free_disk_bytes, bool)
            or self.minimum_free_disk_bytes < 0
        ):
            raise ValueError("minimum free disk bytes must be a non-negative integer")
        if self.expected_context is not None and not self.expected_context.strip():
            raise ValueError("expected Docker context must be non-empty")
        if any(
            not value or not _is_immutable_image_reference(value)
            for value in self.organizer_images
        ):
            raise ValueError("organizer images must use immutable sha256 references")
        names = [name for name, reference in self.practice_artifacts if name and reference]
        if len(names) != len(self.practice_artifacts) or len(set(names)) != len(names):
            raise ValueError("practice artifacts require unique non-empty names and references")
        if any(
            not _is_immutable_image_reference(reference)
            for _, reference in self.practice_artifacts
        ):
            raise ValueError("practice artifacts must use immutable sha256 references")


@dataclass(frozen=True)
class ReadinessCheck:
    status: Literal["passed", "failed"]
    code: str
    detail: str
    remediation: str = ""

    def as_mapping(self) -> Mapping[str, str]:
        return {
            "status": self.status,
            "code": self.code,
            "detail": self.detail,
            "remediation": self.remediation,
        }


def _canonical_identity(version: str, value: Mapping[str, Any]) -> str:
    content = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return version + "@sha256:" + hashlib.sha256(content).hexdigest()


def _check(
    checks: list[ReadinessCheck],
    status: Literal["passed", "failed"],
    code: str,
    detail: str,
    remediation: str = "",
) -> None:
    checks.append(ReadinessCheck(status, code, detail, remediation))


def _run_docker(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    command = ["docker", *arguments]
    try:
        return subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(str(error)) from error


def _successful_docker(arguments: Sequence[str], description: str) -> str:
    completed = _run_docker(arguments)
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            description
            + " failed"
            + (": " + diagnostic[:1000] if diagnostic else "")
        )
    return completed.stdout


def _normalize_architecture(value: object) -> str:
    return {
        "aarch64": "arm64",
        "arm64": "arm64",
        "x86_64": "amd64",
        "x86-64": "amd64",
        "amd64": "amd64",
    }.get(str(value).lower(), str(value).lower())


def _server_platform(info: Mapping[str, Any], server: Mapping[str, Any]) -> str:
    operating_system = str(info.get("OSType") or server.get("Os") or "")
    architecture = _normalize_architecture(
        info.get("Architecture") or server.get("Arch") or ""
    )
    return operating_system + "/" + architecture


def _api_at_least(value: object, minimum: tuple[int, int]) -> bool:
    try:
        major, minor = str(value).split(".", 1)
        observed = (int(major), int(minor))
    except (TypeError, ValueError):
        return False
    return observed >= minimum


def _machine_report() -> dict[str, Any]:
    facts: dict[str, Any] = {
        "hostname": platform.node(),
        "system": platform.system(),
        "release": platform.release(),
        "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(),
    }
    return {
        **facts,
        "identity": _canonical_identity("container-host-machine-v1", facts),
    }


def runtime_references(
    catalog: object, target_platform: str, environment_name: str | None = None
) -> list[str]:
    references: list[str] = []
    environments = getattr(catalog, "environments")
    for environment in environments.values():
        if environment_name is not None and environment.name != environment_name:
            continue
        if environment.contract_only:
            continue
        try:
            build, execution = environment.platform_images(target_platform)
        except CatalogError:
            raise
        references.extend((build.reference, execution.reference))
    if not references:
        raise CatalogError("catalog has no base runtime for " + target_platform)
    return sorted(set(references))


def _inspect_images(
    references: Sequence[str], target_platform: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    present: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []
    for reference in references:
        try:
            completed = _run_docker(("image", "inspect", reference))
        except RuntimeError as error:
            problems.append(
                {
                    "reference": reference,
                    "reason": "inspection_failed",
                    "diagnostic": str(error),
                }
            )
            continue
        if completed.returncode != 0:
            diagnostic = (completed.stderr or completed.stdout).strip()
            lowered = diagnostic.lower()
            reason = (
                "missing"
                if "no such image" in lowered or "no such object" in lowered
                else "inspection_failed"
            )
            problems.append(
                {
                    "reference": reference,
                    "reason": reason,
                    "diagnostic": diagnostic[:1000],
                }
            )
            continue
        try:
            value = json.loads(completed.stdout)
            image = value[0]
        except (json.JSONDecodeError, IndexError, TypeError) as error:
            problems.append(
                {
                    "reference": reference,
                    "reason": "corrupt_inspection",
                    "diagnostic": "invalid image inspection: " + str(error),
                }
            )
            continue
        if not isinstance(image, dict):
            problems.append(
                {
                    "reference": reference,
                    "reason": "corrupt_inspection",
                    "diagnostic": "invalid image inspection",
                }
            )
            continue
        observed_platform = str(image.get("Os", "")) + "/" + _normalize_architecture(
            image.get("Architecture", "")
        )
        if observed_platform != target_platform:
            problems.append(
                {
                    "reference": reference,
                    "reason": "wrong_platform",
                    "diagnostic": "wrong platform: " + observed_platform,
                }
            )
            continue
        expected_digest = reference.rsplit("@", 1)[-1]
        repository_digests = image.get("RepoDigests")
        digest_matches = image.get("Id") == expected_digest or (
            isinstance(repository_digests, list)
            and any(
                isinstance(value, str) and value.endswith("@" + expected_digest)
                for value in repository_digests
            )
        )
        if (
            ("@" in reference or reference.startswith("sha256:"))
            and _IMMUTABLE_DIGEST.fullmatch(expected_digest) is not None
            and not digest_matches
        ):
            problems.append(
                {
                    "reference": reference,
                    "reason": "digest_mismatch",
                    "diagnostic": "immutable digest mismatch",
                }
            )
            continue
        present.append(
            {
                "reference": reference,
                "image_id": image.get("Id"),
                "platform": observed_platform,
                "size_bytes": image.get("Size"),
            }
        )
    return present, problems


def _disk_path(path: Path) -> Path:
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _read_rehearsal_evidence(path: Path) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("rehearsal evidence is missing or not a regular file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("rehearsal evidence is corrupt or unreadable: " + str(error)) from error
    if not isinstance(value, dict):
        raise ValueError("rehearsal evidence must be a JSON object")
    if value.get("rehearsal_report_format_version") != REHEARSAL_REPORT_FORMAT_VERSION:
        raise ValueError("rehearsal evidence format is unsupported")
    return value


def diagnose_host_readiness(request: HostReadinessRequest) -> Mapping[str, Any]:
    """Inspect host and Docker prerequisites without changing either one."""
    request.validate()
    checks: list[ReadinessCheck] = []
    machine = _machine_report()
    docker: dict[str, Any] = {
        "status": "unavailable",
        "context": None,
        "server_name": None,
        "server_platform": None,
        "engine_identity": None,
        "features": {},
    }
    docker_available = False
    docker_info: Mapping[str, Any] = {}

    try:
        context = _successful_docker(
            ("context", "show"), "Docker context inspection"
        ).strip()
        if not context:
            raise RuntimeError("Docker returned an empty active context")
        docker["context"] = context
        if request.expected_context is not None and context != request.expected_context:
            _check(
                checks,
                "failed",
                "wrong_context",
                "Active context is "
                + repr(context)
                + ", expected "
                + repr(request.expected_context)
                + ".",
                "Select the intended Docker context explicitly, then run doctor again.",
            )
        else:
            _check(
                checks,
                "passed",
                "active_context",
                "Active Docker context is " + repr(context) + ".",
            )
        version_value = json.loads(
            _successful_docker(("version", "--format", "{{json .}}"), "Docker version inspection")
        )
        info_value = json.loads(
            _successful_docker(("info", "--format", "{{json .}}"), "Docker server inspection")
        )
        if not isinstance(version_value, dict) or not isinstance(info_value, dict):
            raise ValueError("Docker returned non-object engine metadata")
        server = version_value.get("Server")
        if not isinstance(server, dict):
            raise ValueError("Docker returned no server version metadata")
        docker_info = info_value
        server_platform = _server_platform(info_value, server)
        server_os, server_architecture = server_platform.split("/", 1)
        server_name = server.get("Platform", {}).get("Name") if isinstance(server.get("Platform"), dict) else None
        server_name = str(server_name or info_value.get("OperatingSystem") or "Docker-compatible engine")
        engine_facts = {
            "context": context,
            "engine_id": info_value.get("ID"),
            "server_platform": server_platform,
            "server_version": server.get("Version"),
            "api_version": server.get("ApiVersion"),
        }
        security_options = info_value.get("SecurityOptions")
        security_text = " ".join(str(value).lower() for value in security_options) if isinstance(security_options, list) else ""
        features = {
            "linux_containers": server_platform.startswith("linux/"),
            "private_cgroup_namespace": "cgroupns" in security_text
            or _api_at_least(server.get("ApiVersion"), (1, 41)),
            "seccomp": "seccomp" in security_text,
            "memory_limit": info_value.get("MemoryLimit") is True,
            "cpu_limit": info_value.get("CPUCfs") is True
            or str(info_value.get("CgroupVersion")) == "2",
            "pid_limit": info_value.get("PidsLimit") is True,
        }
        docker.update(
            {
                "status": "connected",
                "context": context,
                "server_name": server_name,
                "server_platform": server_platform,
                "server_os": server_os,
                "server_architecture": server_architecture,
                "server_version": server.get("Version"),
                "api_version": server.get("ApiVersion"),
                "minimum_api_version": server.get("MinAPIVersion"),
                "engine_id": info_value.get("ID"),
                "engine_identity": _canonical_identity("docker-engine-v1", engine_facts),
                "features": features,
            }
        )
        docker_available = True
        _check(checks, "passed", "docker_connected", "Docker server is reachable through the active context.")
        if server_platform != request.platform:
            _check(
                checks,
                "failed",
                "wrong_platform",
                "Docker server platform is " + repr(server_platform) + ", requested " + repr(request.platform) + ".",
                "Use a native Docker context for the requested platform; emulation is not accepted.",
            )
        else:
            _check(checks, "passed", "native_platform", "Docker server is native " + request.platform + ".")
        if features["linux_containers"] and features["private_cgroup_namespace"]:
            _check(checks, "passed", "engine_features", "Docker API and Linux container features satisfy the execution-profile baseline.")
        else:
            _check(
                checks,
                "failed",
                "unsupported_engine_features",
                "Docker lacks Linux containers or private cgroup namespace support.",
                "Use a current Docker-compatible Linux engine.",
            )
        unsupported = sorted(name for name, supported in features.items() if not supported)
        if unsupported:
            _check(
                checks,
                "failed",
                "unsupported_controls",
                "Required controls are unavailable: " + ", ".join(unsupported) + ".",
                "Enable the named engine controls or select another Docker-compatible context; doctor will not change settings.",
            )
        else:
            _check(checks, "passed", "profile_prerequisites", "All published execution-profile controls are reported available.")
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        docker["diagnostic"] = str(error)
        _check(
            checks,
            "failed",
            "docker_unavailable",
            "Docker is unavailable: " + str(error),
            "Start or select the intended Docker-compatible engine and retry; no Docker Desktop-specific engine is required.",
        )

    catalog_report: dict[str, Any] = {"status": "failed", "path": str(request.catalog)}
    required_runtime_references: list[str] = []
    try:
        catalog = load_catalog(request.catalog)
        required_runtime_references = runtime_references(catalog, request.platform)
        catalog_report.update(
            {
                "status": "passed",
                "identity": catalog.identity,
                "runtime_references": required_runtime_references,
            }
        )
        _check(checks, "passed", "catalog_integrity", "Frozen Language Environment catalog and organizer-owned assets are intact.")
    except (CatalogError, OSError, ValueError) as error:
        catalog_report["diagnostic"] = str(error)
        _check(
            checks,
            "failed",
            "corrupt_catalog",
            "Frozen catalog integrity failed: " + str(error),
            "Restore the exact frozen catalog; do not edit it in place.",
        )

    image_report: dict[str, Any] = {
        "base_runtime": {
            "required": required_runtime_references,
            "present": [],
            "problems": [],
        },
        "organizer": {
            "required": list(request.organizer_images),
            "present": [],
            "problems": [],
        },
        "practice": {
            "required": [
                {"name": name, "reference": reference}
                for name, reference in request.practice_artifacts
            ],
            "present": [],
            "problems": [],
        },
    }
    if docker_available:
        groups = (
            ("base_runtime", required_runtime_references, "base_images_present", "missing_pinned_images"),
            ("organizer", request.organizer_images, "organizer_images_present", "missing_organizer_images"),
            ("practice", tuple(reference for _, reference in request.practice_artifacts), "practice_artifacts_present", "missing_practice_artifacts"),
        )
        for group, references, passed_code, failed_code in groups:
            if not references:
                _check(
                    checks,
                    "failed",
                    failed_code,
                    group.replace("_", " ").capitalize() + " requirements were not configured.",
                    "Provide the immutable prepared image references to doctor.",
                )
                continue
            present, problems = _inspect_images(references, request.platform)
            image_report[group]["present"] = present
            image_report[group]["problems"] = problems
            missing = [item for item in problems if item["reason"] == "missing"]
            wrong_platform = [
                item for item in problems if item["reason"] == "wrong_platform"
            ]
            digest_mismatches = [
                item for item in problems if item["reason"] == "digest_mismatch"
            ]
            inspection_failures = [
                item
                for item in problems
                if item["reason"] in ("inspection_failed", "corrupt_inspection")
            ]
            if missing:
                _check(
                    checks,
                    "failed",
                    failed_code,
                    "Missing "
                    + group.replace("_", " ")
                    + ": "
                    + ", ".join(item["reference"] for item in missing)
                    + ".",
                    "Run the explicit preparation workflow; doctor never pulls, builds, loads, or retags images.",
                )
            if wrong_platform:
                _check(
                    checks,
                    "failed",
                    "wrong_platform_images",
                    "Images have the wrong platform: "
                    + ", ".join(item["reference"] for item in wrong_platform)
                    + ".",
                    "Prepare native images for " + request.platform + ".",
                )
            if digest_mismatches:
                _check(
                    checks,
                    "failed",
                    "image_digest_mismatch",
                    "Local images do not match immutable references: "
                    + ", ".join(item["reference"] for item in digest_mismatches)
                    + ".",
                    "Restore the exact pinned images; doctor never retags or substitutes them.",
                )
            if inspection_failures:
                _check(
                    checks,
                    "failed",
                    "image_inspection_failed",
                    "Docker image metadata could not be verified: "
                    + ", ".join(item["reference"] for item in inspection_failures)
                    + ".",
                    "Restore Docker connectivity or correct corrupt local image metadata.",
                )
            if not problems:
                _check(checks, "passed", passed_code, "All required " + group.replace("_", " ") + " images are present for " + request.platform + ".")
    else:
        _check(
            checks,
            "failed",
            "images_unverifiable",
            "Required local images cannot be inspected while Docker is unavailable.",
            "Restore Docker connectivity and retry.",
        )

    artifact_store: dict[str, Any] = {
        "status": "failed",
        "path": str(request.artifact_store),
    }
    try:
        index = verify_artifact_store(request.artifact_store)
        platforms = sorted(
            {str(item.get("platform")) for item in index["artifacts"] if isinstance(item, dict)}
        )
        artifact_store.update(
            {
                "status": "passed",
                "index_identity": index["integrity"]["index_identity"],
                "artifact_count": len(index["artifacts"]),
                "platforms": platforms,
            }
        )
        _check(checks, "passed", "artifact_store_readable", "Bot Artifact store bytes and integrity metadata are readable.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        artifact_store["diagnostic"] = str(error)
        _check(
            checks,
            "failed",
            "corrupt_artifact_store",
            "Bot Artifact store is unavailable or corrupt: " + str(error),
            "Restore the verified store from organizer backup; doctor will not load or repair it.",
        )

    disk_location = _disk_path(request.artifact_store)
    try:
        usage = shutil.disk_usage(disk_location)
        disk = {
            "path": str(disk_location),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "minimum_free_bytes": request.minimum_free_disk_bytes,
        }
        if usage.free < request.minimum_free_disk_bytes:
            _check(
                checks,
                "failed",
                "insufficient_disk",
                "Available disk is " + str(usage.free) + " bytes; at least " + str(request.minimum_free_disk_bytes) + " bytes is required.",
                "Free space outside this command or choose a store filesystem with sufficient capacity; doctor never prunes caches.",
            )
        else:
            _check(checks, "passed", "disk_available", "Available disk meets the configured minimum.")
    except OSError as error:
        disk = {"path": str(disk_location), "diagnostic": str(error)}
        _check(checks, "failed", "disk_unavailable", "Available disk could not be inspected: " + str(error), "Choose a readable artifact-store filesystem and retry.")

    visible_cpus = docker_info.get("NCPU") if docker_available else None
    required_bot_cpus = (
        2
        * request.parallelism
        * INITIAL_EXECUTION_PROFILE.cpu_quota_millis_per_second
        / 1000
    )
    capacity = {
        "visible_cpus": visible_cpus,
        "host_logical_cpus": machine["logical_cpus"],
        "requested_match_parallelism": request.parallelism,
        "recommended_match_parallelism": INITIAL_EXECUTION_PROFILE.recommended_match_parallelism,
        "required_bot_cpu_capacity": required_bot_cpus,
    }
    if not isinstance(visible_cpus, (int, float)) or isinstance(visible_cpus, bool) or visible_cpus <= 0:
        _check(checks, "failed", "cpu_visibility_unavailable", "Docker did not report a positive visible CPU count.", "Configure CPU visibility in the selected engine and retry.")
    elif required_bot_cpus > visible_cpus:
        _check(
            checks,
            "failed",
            "parallelism_impossible",
            "Requested Match parallelism requires " + str(required_bot_cpus) + " Bot Artifact CPUs but Docker exposes " + str(visible_cpus) + ".",
            "Reduce Match parallelism or explicitly allocate more CPUs to the selected engine.",
        )
    else:
        _check(checks, "passed", "cpu_capacity", "Requested Match parallelism fits within Docker's visible CPU count.")

    profile_report = {
        "identity": INITIAL_EXECUTION_PROFILE.identity,
        "values": INITIAL_EXECUTION_PROFILE.as_mapping(),
    }
    rehearsal: dict[str, Any] = {"status": "not_provided", "mismatches": []}
    if request.rehearsal_evidence is not None:
        try:
            evidence = _read_rehearsal_evidence(request.rehearsal_evidence)
            expected = {
                "machine_identity": machine["identity"],
                "engine_identity": docker.get("engine_identity"),
                "docker_context": docker.get("context"),
                "catalog_identity": catalog_report.get("identity"),
                "profile_identity": profile_report["identity"],
                "platform": request.platform,
                "parallelism": request.parallelism,
            }
            mismatches = sorted(
                key for key, value in expected.items() if evidence.get(key) != value
            )
            if evidence.get("status") != "passed":
                mismatches.append("status")
                mismatches = sorted(set(mismatches))
            rehearsal = {
                "status": "matched" if not mismatches else "mismatched",
                "path": str(request.rehearsal_evidence),
                "mismatches": mismatches,
                "evidence": {key: evidence.get(key) for key in (*expected, "status")},
            }
            if mismatches:
                _check(
                    checks,
                    "failed",
                    "stale_rehearsal_evidence",
                    "Prior rehearsal evidence does not match: " + ", ".join(mismatches) + ".",
                    "Run the explicit full rehearsal for this exact machine, context, catalog, profile, platform, and parallelism.",
                )
            else:
                _check(checks, "passed", "rehearsal_evidence_matches", "Prior passed rehearsal evidence matches the current configuration.")
        except ValueError as error:
            rehearsal = {
                "status": "corrupt",
                "path": str(request.rehearsal_evidence),
                "mismatches": [],
                "diagnostic": str(error),
            }
            _check(checks, "failed", "corrupt_rehearsal_evidence", str(error), "Restore or regenerate the rehearsal report; doctor will not edit it.")

    ready = not any(check.status == "failed" for check in checks)
    return {
        "report_format_version": HOST_READINESS_REPORT_FORMAT_VERSION,
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "machine": machine,
        "docker": docker,
        "catalog": catalog_report,
        "images": image_report,
        "artifact_store": artifact_store,
        "disk": disk,
        "capacity": capacity,
        "profile": profile_report,
        "rehearsal": rehearsal,
        "checks": [check.as_mapping() for check in checks],
        "mutation_policy": {
            "status": "read_only",
            "docker_commands": [
                "docker context show",
                "docker version --format",
                "docker info --format",
                "docker image inspect",
            ],
        },
    }
