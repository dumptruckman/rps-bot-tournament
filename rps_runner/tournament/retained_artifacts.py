"""Authoritative verification of retained Bot Artifacts selected for a Tournament."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from rps_runner.artifact_store import (
    load_retained_artifact_manifests,
    load_retained_validation_reports,
    verify_artifact_store,
)
from rps_runner.execution_profile import ExecutionProfile
from rps_runner.language_environment import LanguageEnvironmentCatalog


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTITY = re.compile(r"[^@]+@sha256:[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class RetainedBotArtifactRequirement:
    location: str
    artifact_digest: str
    platform: str
    canonical_identity: Mapping[str, Any]


def verify_retained_bot_artifacts(
    store: Path,
    expected_index_identity: object,
    requirements: Sequence[RetainedBotArtifactRequirement],
    catalog: LanguageEnvironmentCatalog,
    profile: ExecutionProfile,
) -> Mapping[str, str]:
    """Verify the store and organizer-final authority for selected artifacts."""

    index = verify_artifact_store(store)
    integrity = _object(index.get("integrity"), "artifact store integrity")
    if expected_index_identity != integrity.get("index_identity"):
        raise ValueError("Tournament artifact-store index identity mismatch")
    retained_manifests = load_retained_artifact_manifests(
        store, verified_index=index
    )
    retained_reports = load_retained_validation_reports(
        store, verified_index=index
    )
    platforms: dict[str, str] = {}
    for requirement in requirements:
        key = (requirement.artifact_digest, requirement.platform)
        retained = retained_manifests.get(key)
        if retained is None:
            raise ValueError(
                requirement.location + " is missing from the retained artifact store"
            )
        if canonical_artifact_identity(retained) != requirement.canonical_identity:
            raise ValueError(
                requirement.location + " does not match the retained Bot Artifact"
            )
        validate_bot_artifact_manifest(
            retained,
            str(requirement.canonical_identity.get("source_digest")),
            catalog,
            profile,
            requirement.location,
        )
        report = retained_reports.get(key)
        if report is None:
            raise ValueError(
                requirement.location + " is missing its final validation report"
            )
        validate_final_validation_report(report, retained, requirement.location)
        platforms[requirement.artifact_digest] = requirement.platform
    return MappingProxyType(dict(sorted(platforms.items())))


def validate_bot_artifact_manifest(
    manifest: Mapping[str, Any],
    selected_source_digest: str,
    catalog: LanguageEnvironmentCatalog,
    profile: ExecutionProfile,
    location: str,
) -> None:
    _exact_fields(
        manifest,
        {
            "bot_artifact_manifest_format_version",
            "status",
            "authority",
            "artifact_digest",
            "source_digest",
            "runtime_digest",
            "runtime",
            "build_toolchain",
            "language",
            "platform",
            "profile",
            "entrypoint",
            "build_identity",
            "validation_identity",
            "identities",
            "image",
            "retention",
        },
        location + ".bot_artifact_manifest",
    )
    expected_scalars = {
        "bot_artifact_manifest_format_version": "bot-artifact-manifest-v1",
        "status": "validated",
        "authority": "canonical",
        "platform": "linux/arm64",
        "profile": profile.version,
    }
    for field, expected in expected_scalars.items():
        if manifest.get(field) != expected:
            raise ValueError(location + "." + field + " is invalid")
    try:
        environment = catalog.environment_for_language(str(manifest.get("language")))
    except ValueError as error:
        raise ValueError(location + " language is not in the catalog: " + str(error)) from error
    for field in ("artifact_digest", "source_digest", "runtime_digest"):
        if not isinstance(manifest.get(field), str) or _DIGEST.fullmatch(
            str(manifest.get(field))
        ) is None:
            raise ValueError(location + "." + field + " is not immutable")
    if selected_source_digest != manifest["source_digest"]:
        raise ValueError(location + " selected source identity mismatch")
    entrypoint = json.loads(environment.assets["entrypoint"].content)["argv"]
    if manifest.get("entrypoint") != entrypoint:
        raise ValueError(location + " entrypoint does not match the catalog")
    identities = _object(manifest.get("identities"), location + ".identities")
    _exact_fields(
        identities,
        {
            "source",
            "image",
            "runtime",
            "build_toolchain",
            "build_toolchain_definition",
            "wrapper",
            "recipe",
            "entrypoint",
            "catalog",
            "language_environment",
            "suite",
            "platform",
            "profile",
            "core_tool",
            "builder_core_tool",
        },
        location + ".identities",
    )
    expected_identities = {
        "source": manifest["source_digest"],
        "image": manifest["artifact_digest"],
        "catalog": catalog.identity,
        "language_environment": environment.descriptor_identity,
        "build_toolchain_definition": environment.assets["build_toolchain"].identity,
        "profile": profile.identity,
        "wrapper": environment.assets["wrapper"].identity,
        "recipe": environment.assets["recipe"].identity,
        "entrypoint": environment.assets["entrypoint"].identity,
        "platform": environment.assets["platform"].identity,
        "suite": (
            str(json.loads(environment.assets["conformance"].content)["suite_version"])
            + "@"
            + environment.assets["conformance"].identity.split("@", 1)[1]
        ),
    }
    for field, expected in expected_identities.items():
        if identities.get(field) != expected:
            raise ValueError(location + " stale or mismatched " + field + " identity")
    for field in ("runtime", "build_toolchain", "core_tool", "builder_core_tool"):
        value = identities.get(field)
        if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
            raise ValueError(location + " missing " + field + " identity")
    runtime = _object(manifest.get("runtime"), location + ".runtime")
    _exact_fields(runtime, {"identity", "reference", "digest"}, location + ".runtime")
    runtime_definitions = json.loads(environment.assets["base_runtime"].content)
    pinned_platform = runtime_definitions["platforms"]["linux/arm64"]
    pinned = pinned_platform.get("execution_runtime", pinned_platform)
    runtime_digest = pinned["image"].rsplit("@", 1)[1]
    if runtime != {
        "identity": pinned["version"] + "@" + runtime_digest,
        "reference": pinned["image"],
        "digest": runtime_digest,
    } or manifest["runtime_digest"] != runtime_digest:
        raise ValueError(location + " runtime does not match the pinned catalog")
    if identities.get("runtime") != runtime["identity"]:
        raise ValueError(location + " runtime identity mismatch")
    build_toolchain = _object(
        manifest.get("build_toolchain"), location + ".build_toolchain"
    )
    _exact_fields(
        build_toolchain,
        {"identity", "reference", "digest"},
        location + ".build_toolchain",
    )
    pinned_build = pinned_platform.get("build_toolchain", pinned_platform)
    build_digest = pinned_build["image"].rsplit("@", 1)[1]
    if build_toolchain != {
        "identity": pinned_build["version"] + "@" + build_digest,
        "reference": pinned_build["image"],
        "digest": build_digest,
    }:
        raise ValueError(location + " build toolchain does not match the pinned catalog")
    if identities.get("build_toolchain") != build_toolchain["identity"]:
        raise ValueError(location + " build toolchain identity mismatch")
    image = _object(manifest.get("image"), location + ".image")
    _exact_fields(image, {"manifest_digest", "local_image_id"}, location + ".image")
    if image.get("manifest_digest") != manifest["artifact_digest"]:
        raise ValueError(location + " image manifest digest mismatch")
    for field in ("build_identity", "validation_identity"):
        value = manifest.get(field)
        if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
            raise ValueError(location + " missing " + field)


def canonical_artifact_identity(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    canonical = json.loads(json.dumps(manifest))
    canonical.pop("retention", None)
    image = canonical.get("image")
    if isinstance(image, dict):
        image.pop("local_image_id", None)
    return canonical


def validate_final_validation_report(
    report: Mapping[str, Any], manifest: Mapping[str, Any], location: str
) -> None:
    expected = {
        "validation_report_format_version": "validation-report-v1",
        "status": "passed",
        "mode": "organizer-final",
        "authority": "canonical",
        "advisory": False,
        "canonical_tournament_eligible": True,
        "platform": manifest["platform"],
        "profile": manifest["profile"],
    }
    for field, value in expected.items():
        if report.get(field) != value:
            raise ValueError(location + " final validation " + field + " is invalid")
    if report.get("identities") != manifest.get("identities"):
        raise ValueError(location + " final validation identities mismatch")
    validation_basis = {
        "format": "bot-artifact-certification-v1",
        "mode": "organizer-final",
        "authority": "canonical",
        "platform": manifest["platform"],
        "profile": manifest["profile"],
        "identities": manifest["identities"],
    }
    canonical = json.dumps(
        validation_basis, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected_identity = "validation-report-v1@sha256:" + hashlib.sha256(
        canonical
    ).hexdigest()
    if (
        report.get("validation_identity") != expected_identity
        or manifest.get("validation_identity") != expected_identity
    ):
        raise ValueError(location + " final validation identity mismatch")
    checks = _object(report.get("checks"), location + ".validation.checks")
    expected_checks = {
        "source_validation": "passed-by-frozen-bundle",
        "networkless_build": "passed-by-verified-current-builder-record",
        "image_identity": "passed",
        "readiness": "passed",
        "clean_shutdown": "passed",
        "protocol_transcripts": "passed",
        "same_seed_behavior": "passed",
        "timing_and_stream_limits": "passed",
        "resource_enforcement": "passed-through-profile",
        "isolation": "passed-through-profile",
        "diagnostics": "passed",
        "complete_smoke_match": "passed",
        "practice_match_result_gate": "not-applicable",
    }
    if checks != expected_checks:
        raise ValueError(location + " final validation checks are incomplete")


def _exact_fields(
    value: Mapping[str, Any], expected: set[str], location: str
) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unexpected = sorted(set(value) - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise ValueError(location + " fields are invalid: " + "; ".join(details))


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(field + " must be an object")
    return value
