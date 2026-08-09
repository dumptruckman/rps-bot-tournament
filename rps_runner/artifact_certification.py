from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Mapping

from rps_runner.artifact_builder import (
    _core_tool_identity as _builder_core_tool_identity,
    build_artifact_candidate,
)
from rps_runner.engine import ContainerOperations
from rps_runner.engine.container_session import CONTAINER_ISOLATION_PROFILE_VERSION
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import (
    LanguageEnvironmentCatalog,
    SourceValidationError,
    freeze_source_bundle,
    load_frozen_source_bundle,
    validate_source,
)
from rps_runner.tournament.match_executor import (
    ContainerMatchExecutor,
    MatchExecutionRequest,
)


CERTIFICATION_FORMAT_VERSION = "bot-artifact-certification-v1"
MANIFEST_FORMAT_VERSION = "bot-artifact-manifest-v1"
REPORT_FORMAT_VERSION = "validation-report-v1"
SUITE_VERSION = "python-artifact-conformance-v1"
CORE_TOOL_VERSION = "rps-core-tool-v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTITY = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")
_PLATFORMS = frozenset({"linux/amd64", "linux/arm64"})
CERTIFICATION_MODES = (
    "participant-local",
    "github-advisory",
    "organizer-final",
)
_MODES = frozenset(CERTIFICATION_MODES)


class CertificationFailure(ValueError):
    """A candidate failed compatibility validation without a Match outcome."""


@dataclass(frozen=True)
class CertificationInputs:
    mode: str
    platform: str
    profile: str

    def validate(self) -> None:
        if self.mode not in _MODES:
            raise CertificationFailure(
                "validation mode must be participant-local, github-advisory, "
                "or organizer-final"
            )
        if self.platform not in _PLATFORMS:
            raise CertificationFailure(
                "platform must be 'linux/amd64' or 'linux/arm64'"
            )
        if self.profile != CONTAINER_ISOLATION_PROFILE_VERSION:
            raise CertificationFailure(
                "wrong-profile candidate: expected "
                + repr(CONTAINER_ISOLATION_PROFILE_VERSION)
            )
        required_platform = {
            "github-advisory": "linux/amd64",
            "organizer-final": "linux/arm64",
        }.get(self.mode)
        if required_platform is not None and self.platform != required_platform:
            raise CertificationFailure(
                self.mode + " requires platform " + repr(required_platform)
            )

    @property
    def authority(self) -> str:
        return "canonical" if self.mode == "organizer-final" else "advisory"


def _read_object(path: Path, description: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CertificationFailure("could not read " + description + ": " + str(error))
    if not isinstance(value, dict):
        raise CertificationFailure(description + " must be a JSON object")
    return value


def _identity(version: str, value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return version + "@sha256:" + hashlib.sha256(canonical).hexdigest()


def _core_tool_identity() -> str:
    digest = hashlib.sha256()
    package = Path(__file__).resolve().parent
    names = (
        "artifact_builder.py",
        "artifact_certification.py",
        "artifact_cli.py",
        "certification_cli.py",
        "language_environment.py",
    )
    for name in names:
        content = (package / name).read_bytes()
        digest.update(name.encode() + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return CORE_TOOL_VERSION + "@sha256:" + digest.hexdigest()


def _candidate_manifest(candidate: Path) -> Mapping[str, Any]:
    if candidate.is_symlink() or not candidate.is_dir():
        raise CertificationFailure("candidate must be an existing non-symlink directory")
    manifest = _read_object(candidate / "artifact-candidate.json", "candidate manifest")
    if manifest.get("artifact_candidate_format_version") != "artifact-candidate-v1":
        raise CertificationFailure("candidate manifest format is unsupported")
    if manifest.get("status") != "suite-candidate":
        raise CertificationFailure("candidate has already changed from suite-candidate status")
    return manifest


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CertificationFailure(field + " must be an immutable sha256 digest")
    return value


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CertificationFailure(field + " must be an object")
    return value


def _verify_candidate_identities(
    manifest: Mapping[str, Any], catalog: LanguageEnvironmentCatalog, inputs: CertificationInputs
) -> None:
    if manifest.get("language") != "python":
        raise CertificationFailure("only Python Bot Artifact candidates are supported")
    if manifest.get("platform") != inputs.platform:
        raise CertificationFailure(
            "wrong-platform candidate: manifest says "
            + repr(manifest.get("platform"))
            + "; requested "
            + repr(inputs.platform)
        )
    _require_digest(manifest.get("source_digest"), "source_digest")
    artifact_digest = _require_digest(manifest.get("artifact_digest"), "artifact_digest")
    runtime_digest = _require_digest(manifest.get("runtime_digest"), "runtime_digest")
    build_identity = manifest.get("build_identity")
    if not isinstance(build_identity, str) or _IDENTITY.fullmatch(build_identity) is None:
        raise CertificationFailure("build_identity is missing or invalid")
    image = _mapping(manifest.get("image"), "image")
    retention = _mapping(manifest.get("retention"), "retention")
    runtime = _mapping(manifest.get("runtime"), "runtime")
    runtime_identity = runtime.get("identity")
    if not isinstance(runtime_identity, str) or _IDENTITY.fullmatch(runtime_identity) is None:
        raise CertificationFailure("runtime.identity is missing or invalid")
    local_image_id = _require_digest(
        image.get("local_image_id"), "image.local_image_id"
    )
    for field, observed in (
        ("image.manifest_digest", image.get("manifest_digest")),
        ("retention.authority", retention.get("authority")),
    ):
        if observed != artifact_digest:
            raise CertificationFailure("digest-mismatched candidate: " + field)
    if runtime.get("digest") != runtime_digest:
        raise CertificationFailure("digest-mismatched candidate: runtime.digest")
    if retention.get("local_image_id") != local_image_id:
        raise CertificationFailure("digest-mismatched candidate: retention.local_image_id")
    reference = retention.get("local_image_reference")
    if not isinstance(reference, str) or not reference:
        raise CertificationFailure("candidate image is missing from its active Docker context")
    identities = _mapping(manifest.get("identities"), "identities")
    environment = catalog.environment("python")
    expected = {
        "catalog": catalog.identity,
        "entrypoint": environment.assets["entrypoint"].identity,
        "language_environment": environment.descriptor_identity,
        "platform": environment.assets["platform"].identity,
        "recipe": environment.assets["recipe"].identity,
        "suite_candidate": environment.assets["conformance"].identity,
        "wrapper": environment.assets["wrapper"].identity,
    }
    for key, value in expected.items():
        if identities.get(key) != value:
            raise CertificationFailure(
                "stale-catalog candidate: identity " + repr(key) + " does not match"
            )
    core = identities.get("core_tool")
    if core != _builder_core_tool_identity():
        raise CertificationFailure(
            "candidate was not produced by the current trusted core builder"
        )

    runtime_definition = json.loads(environment.assets["base_runtime"].content)
    platforms = runtime_definition.get("platforms")
    pinned = platforms.get(inputs.platform) if isinstance(platforms, dict) else None
    pinned_reference = pinned.get("image") if isinstance(pinned, dict) else None
    pinned_version = pinned.get("version") if isinstance(pinned, dict) else None
    if (
        not isinstance(pinned_reference, str)
        or "@" not in pinned_reference
        or not isinstance(pinned_version, str)
    ):
        raise CertificationFailure("catalog has no immutable runtime for requested platform")
    pinned_digest = pinned_reference.rsplit("@", 1)[1]
    if (
        runtime.get("reference") != pinned_reference
        or runtime_digest != pinned_digest
        or runtime_identity != pinned_version + "@" + pinned_digest
    ):
        raise CertificationFailure("stale-catalog candidate: pinned runtime does not match")

    build_inputs = {
        "artifact_digest": artifact_digest,
        "identities": identities,
        "language": "python",
        "platform": inputs.platform,
        "runtime_identity": runtime_identity,
        "source_digest": manifest["source_digest"],
    }
    expected_build_identity = _identity("build-v1", build_inputs)
    if build_identity != expected_build_identity:
        raise CertificationFailure(
            "digest-mismatched candidate: build identity does not match frozen inputs"
        )


def _verify_frozen_source(
    candidate: Path,
    candidate_manifest: Mapping[str, Any],
    catalog: LanguageEnvironmentCatalog,
) -> None:
    bundle = load_frozen_source_bundle(candidate, catalog)
    if bundle.environment.name != "python":
        raise CertificationFailure("candidate source uses the wrong Language Environment")
    if bundle.manifest.get("source_digest") != candidate_manifest.get("source_digest"):
        raise CertificationFailure(
            "digest-mismatched candidate: frozen source and build record differ"
        )


def _inspect_image(reference: str) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            ["docker", "image", "inspect", reference],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CertificationFailure("could not inspect candidate image: " + str(error))
    diagnostics = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise CertificationFailure(
            "candidate image is missing from the active Docker context: " + diagnostics.strip()
        )
    try:
        value = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CertificationFailure("Docker returned invalid image inspection: " + str(error))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise CertificationFailure("Docker image inspection did not resolve exactly one image")
    return value[0]


def _verify_image(manifest: Mapping[str, Any], inputs: CertificationInputs) -> None:
    retention = _mapping(manifest["retention"], "retention")
    details = _inspect_image(str(retention["local_image_id"]))
    observed_platform = str(details.get("Os", "")) + "/" + str(details.get("Architecture", ""))
    if observed_platform != inputs.platform:
        raise CertificationFailure(
            "wrong-platform image: observed " + repr(observed_platform)
        )
    if details.get("Id") != retention.get("local_image_id"):
        raise CertificationFailure("digest-mismatched candidate: local image ID changed")
    config = _mapping(details.get("Config"), "Docker image Config")
    if config.get("Entrypoint") != manifest.get("entrypoint"):
        raise CertificationFailure("candidate image entrypoint does not match the catalog")


def _conformance_match_request(
    artifact_digest_a: str,
    artifact_digest_b: str,
    seed: int,
    attempt: int,
    *,
    team_b_id: str = "candidate-b",
) -> MatchExecutionRequest:
    profile = INITIAL_EXECUTION_PROFILE
    return MatchExecutionRequest(
        tournament_id="artifact-conformance",
        fixture_id="smoke-fixture",
        series_id="smoke-series",
        match_id="smoke-match-" + str(attempt),
        attempt_number=1,
        team_a_id="candidate-a",
        team_b_id=team_b_id,
        artifact_digest_a=artifact_digest_a,
        artifact_digest_b=artifact_digest_b,
        match_seed=seed,
        bot_visible_seed_a=seed,
        bot_visible_seed_b=seed,
        protocol_version=1,
        scheduled_turns=300,
        first_move_timeout_ms=profile.first_move_timeout_ms,
        move_timeout_ms=profile.move_timeout_ms,
        total_timeout_ms=profile.total_timeout_ms,
        stderr_limit_bytes=profile.stderr_limit_bytes,
        stdout_limit_bytes=profile.stdout_limit_bytes,
        cpu_limit_ms=profile.cpu_limit_ms,
        cpu_quota_millis_per_second=profile.cpu_quota_millis_per_second,
        memory_limit_bytes=profile.memory_limit_bytes,
        process_limit=profile.process_limit,
        open_file_limit=profile.open_file_limit,
        filesystem_write_limit_bytes=profile.filesystem_write_limit_bytes,
        network_access_allowed=False,
    )


def _conformance_definition(
    catalog: LanguageEnvironmentCatalog,
) -> Mapping[str, Any]:
    asset = catalog.environment("python").assets["conformance"]
    try:
        value = json.loads(asset.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CertificationFailure("conformance definition is invalid: " + str(error))
    if not isinstance(value, dict):
        raise CertificationFailure("conformance definition must be a JSON object")
    return value


def _practice_sources(catalog: LanguageEnvironmentCatalog) -> Mapping[str, str]:
    practices = _conformance_definition(catalog).get("practice_artifacts")
    expected = {"fixed-move", "random", "copycat", "protocol-test"}
    if (
        not isinstance(practices, dict)
        or set(practices) != expected
        or any(not isinstance(source, str) or not source for source in practices.values())
    ):
        raise CertificationFailure(
            "conformance definition must bundle fixed-move, random, copycat, "
            "and protocol-test practice Bot Artifacts"
        )
    return practices


def _diagnostic_fixture_report(
    catalog: LanguageEnvironmentCatalog,
) -> Mapping[str, Mapping[str, str]]:
    fixtures = _conformance_definition(catalog).get("diagnostic_fixtures")
    expected = {
        "syntax-build": "Python source syntax or networkless Docker build failed",
        "import-time": "strategy import exited before wrapper readiness",
        "nondeterministic": "repeated same-seed transcript differed",
        "protocol-fault": "invalid protocol move and Turn were reported",
        "slow-response": "response-time limit and Turn were reported",
        "memory": "container OOM/resource fault was reported",
        "process": "container process-limit/resource fault was reported",
        "filesystem": "writable-filesystem/resource fault was reported",
        "premature-output": "output before the first request was reported",
    }
    if not isinstance(fixtures, list) or set(fixtures) != set(expected):
        raise CertificationFailure(
            "conformance definition does not declare the complete diagnostic fixture set"
        )
    return {
        name: {"status": "covered", "actionable_diagnostic": expected[name]}
        for name in fixtures
    }


def _fixture_sources(catalog: LanguageEnvironmentCatalog) -> Mapping[str, str]:
    sources = _conformance_definition(catalog).get("fixture_sources")
    expected = set(_diagnostic_fixture_report(catalog))
    if (
        not isinstance(sources, dict)
        or set(sources) != expected
        or any(not isinstance(source, str) or not source for source in sources.values())
    ):
        raise CertificationFailure(
            "conformance definition does not bundle every diagnostic fixture source"
        )
    return sources


def _make_tree_writable(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    root.chmod(0o755)


def _build_practice_artifacts(
    catalog: LanguageEnvironmentCatalog, platform: str, work: Path
) -> Mapping[str, Mapping[str, Any]]:
    environment = catalog.environment("python")
    built: dict[str, Mapping[str, Any]] = {}
    for name, strategy in _practice_sources(catalog).items():
        source = work / (name + "-source")
        source.mkdir()
        (source / "strategy.py").write_text(strategy)
        bundle = work / (name + "-bundle")
        freeze_source_bundle(source, bundle, catalog, environment)
        candidate = work / (name + "-candidate")
        built[name] = build_artifact_candidate(
            bundle, candidate, catalog, platform
        )
    return built


def _build_diagnostic_artifacts(
    catalog: LanguageEnvironmentCatalog, platform: str, work: Path
) -> Mapping[str, Mapping[str, Any]]:
    environment = catalog.environment("python")
    sources = _fixture_sources(catalog)
    syntax_source = work / "syntax-build-source"
    syntax_source.mkdir()
    (syntax_source / "strategy.py").write_text(sources["syntax-build"])
    try:
        validate_source(syntax_source, environment)
    except SourceValidationError as error:
        if "Python source is not valid syntax" not in str(error):
            raise CertificationFailure(
                "syntax/build fixture produced an unactionable diagnostic: " + str(error)
            )
    else:
        raise CertificationFailure("syntax/build fixture unexpectedly passed source validation")

    built: dict[str, Mapping[str, Any]] = {}
    for name, strategy in sources.items():
        if name == "syntax-build":
            continue
        source = work / (name + "-source")
        source.mkdir()
        (source / "strategy.py").write_text(strategy)
        bundle = work / (name + "-bundle")
        freeze_source_bundle(source, bundle, catalog, environment)
        candidate = work / (name + "-candidate")
        built[name] = build_artifact_candidate(
            bundle, candidate, catalog, platform
        )
    return built


def _execute_conforming_match(
    executor: ContainerMatchExecutor,
    request: MatchExecutionRequest,
    description: str,
) -> Mapping[str, Any]:
    result = executor.execute(request)
    if result.infrastructure_failure:
        failure = result.operational_telemetry.get("infrastructure_failure", {})
        message = (
            failure.get("message", "unknown infrastructure failure")
            if isinstance(failure, dict)
            else failure
        )
        raise CertificationFailure(
            description + " launch/readiness/lifecycle conformance failed: " + str(message)
        )
    if (
        result.suspected_security_violation_team_ids
        or result.suspected_security_violation_team_id
    ):
        raise CertificationFailure(description + " produced security evidence")
    outcome = result.competitive_outcome
    if outcome is None:
        raise CertificationFailure(description + " produced no outcome")
    faults = outcome.get("faults")
    if isinstance(faults, dict) and any(
        fault is not None for fault in faults.values()
    ):
        raise CertificationFailure(
            description
            + " protocol/timing/stream/resource conformance failed: "
            + json.dumps(faults, sort_keys=True)
        )
    return json.loads(json.dumps(outcome))


def _deterministic_transcript(outcome: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status": outcome.get("status"),
        "winner_team_id": outcome.get("winner_team_id"),
        "score": outcome.get("score"),
        "moves": outcome.get("moves"),
        "rounds": outcome.get("rounds"),
        "faults": outcome.get("faults"),
    }


def _fixture_fault(
    outcome: Mapping[str, Any], team_id: str
) -> Mapping[str, Any] | None:
    faults = outcome.get("faults")
    fault = faults.get(team_id) if isinstance(faults, dict) else None
    return fault if isinstance(fault, dict) else None


def _run_diagnostic_artifacts(
    executor: ContainerMatchExecutor,
    fixtures: Mapping[str, Mapping[str, Any]],
    fixed_move: Mapping[str, Any],
) -> Mapping[str, Mapping[str, str]]:
    fixed_digest = str(fixed_move["artifact_digest"])
    reports: dict[str, Mapping[str, str]] = {
        "syntax-build": {
            "status": "passed",
            "actionable_diagnostic": "Python source is not valid syntax",
        }
    }
    expected_faults = {
        "import-time": {"unexpected_exit"},
        "protocol-fault": {"invalid_response"},
        "slow-response": {"timeout"},
        "memory": {"resource_oom", "unexpected_exit"},
        "premature-output": {"unexpected_output"},
    }
    attempt = 20
    for name, accepted_kinds in expected_faults.items():
        fixture_digest = str(fixtures[name]["artifact_digest"])
        outcome = _execute_fixture_match(
            executor,
            _conformance_match_request(
                fixture_digest, fixed_digest, 9000 + attempt, attempt
            ),
            name,
        )
        fault = _fixture_fault(outcome, "candidate-a")
        kind = fault.get("kind") if fault is not None else None
        if kind not in accepted_kinds:
            raise CertificationFailure(
                name + " fixture did not produce its actionable fault; observed " + repr(kind)
            )
        reports[name] = {
            "status": "passed",
            "actionable_diagnostic": str(kind) + " at Turn " + str(fault.get("turn")),
        }
        attempt += 1

    for name in ("process", "filesystem"):
        fixture_digest = str(fixtures[name]["artifact_digest"])
        outcome = _execute_fixture_match(
            executor,
            _conformance_match_request(
                fixture_digest, fixed_digest, 9000 + attempt, attempt
            ),
            name,
        )
        fault = _fixture_fault(outcome, "candidate-a")
        if fault is not None:
            raise CertificationFailure(
                name
                + " enforcement fixture failed: "
                + str(fault.get("kind"))
                + " at Turn "
                + str(fault.get("turn"))
            )
        reports[name] = {
            "status": "passed",
            "actionable_diagnostic": name + " limit was enforced",
        }
        attempt += 1

    nondeterministic_digest = str(fixtures["nondeterministic"]["artifact_digest"])
    nondeterministic_outcomes = [
        _execute_fixture_match(
            executor,
            _conformance_match_request(
                nondeterministic_digest,
                fixed_digest,
                424242,
                attempt + offset,
            ),
            "nondeterministic",
        )
        for offset in (0, 1)
    ]
    moves = [
        outcome.get("moves", {}).get("candidate-a")
        if isinstance(outcome.get("moves"), dict)
        else None
        for outcome in nondeterministic_outcomes
    ]
    if moves[0] == moves[1]:
        raise CertificationFailure(
            "nondeterministic fixture did not produce differing same-seed transcripts"
        )
    reports["nondeterministic"] = {
        "status": "passed",
        "actionable_diagnostic": "repeated same-seed transcript differed",
    }
    return reports


def _execute_fixture_match(
    executor: ContainerMatchExecutor,
    request: MatchExecutionRequest,
    description: str,
) -> Mapping[str, Any]:
    result = executor.execute(request)
    if result.infrastructure_failure:
        raise CertificationFailure(description + " fixture caused Infrastructure Failure")
    if result.competitive_outcome is None:
        raise CertificationFailure(description + " fixture produced no Match outcome")
    return json.loads(json.dumps(result.competitive_outcome))


def _run_smoke_matches(
    manifest: Mapping[str, Any], catalog: LanguageEnvironmentCatalog, platform: str
) -> Mapping[str, Any]:
    digest = str(manifest["artifact_digest"])
    reference = str(_mapping(manifest["retention"], "retention")["local_image_id"])
    with tempfile.TemporaryDirectory(prefix="rps-conformance-") as work_name:
        work = Path(work_name)
        practice_candidates: Mapping[str, Mapping[str, Any]] = {}
        diagnostic_candidates: Mapping[str, Mapping[str, Any]] = {}
        try:
            practice_candidates = _build_practice_artifacts(catalog, platform, work)
            diagnostic_candidates = _build_diagnostic_artifacts(
                catalog, platform, work
            )
            references = {digest: reference}
            references.update(
                {
                    str(candidate["artifact_digest"]): str(
                        _mapping(candidate["retention"], "retention")["local_image_id"]
                    )
                    for candidate in practice_candidates.values()
                }
            )
            references.update(
                {
                    str(candidate["artifact_digest"]): str(
                        _mapping(candidate["retention"], "retention")["local_image_id"]
                    )
                    for candidate in diagnostic_candidates.values()
                }
            )
            executor = ContainerMatchExecutor(
                lambda _team_id, requested: references[requested],
                operations=ContainerOperations(),
            )
            outcomes = [
                _execute_conforming_match(
                    executor,
                    _conformance_match_request(digest, digest, 8675309, attempt),
                    "same-seed smoke Match",
                )
                for attempt in (1, 2)
            ]
            if _deterministic_transcript(outcomes[0]) != _deterministic_transcript(
                outcomes[1]
            ):
                raise CertificationFailure(
                    "repeated same-seed behavior was nondeterministic"
                )
            practices = {}
            for index, (name, practice) in enumerate(
                sorted(practice_candidates.items()), start=3
            ):
                practice_digest = str(practice["artifact_digest"])
                outcome = _execute_conforming_match(
                    executor,
                    _conformance_match_request(
                        digest,
                        practice_digest,
                        8675309 + index,
                        index,
                        team_b_id="practice-" + name,
                    ),
                    name + " practice Match",
                )
                practices[name] = {
                    "status": "passed",
                    "artifact_digest": practice_digest,
                    "outcome_observed_not_gated": outcome,
                }
            diagnostic_reports = _run_diagnostic_artifacts(
                executor,
                diagnostic_candidates,
                practice_candidates["fixed-move"],
            )
            return {
                "attempts": 2,
                "same_seed_repeated": True,
                "scheduled_turns": 300,
                "outcome_observed_not_gated": outcomes[0],
                "practice_artifacts": practices,
                "diagnostic_fixtures": diagnostic_reports,
            }
        finally:
            for practice in (
                *practice_candidates.values(),
                *diagnostic_candidates.values(),
            ):
                reference_to_remove = _mapping(
                    practice["retention"], "retention"
                ).get("local_image_reference")
                if isinstance(reference_to_remove, str):
                    subprocess.run(
                        ["docker", "image", "rm", reference_to_remove],
                        capture_output=True,
                        timeout=10,
                    )
            _make_tree_writable(work)


def certify_artifact_candidate(
    candidate: Path,
    destination: Path,
    catalog: LanguageEnvironmentCatalog,
    inputs: CertificationInputs,
) -> Mapping[str, Any]:
    inputs.validate()
    if destination.exists() or destination.is_symlink():
        raise CertificationFailure("output destination already exists and will not be replaced")
    candidate_manifest = _candidate_manifest(candidate)
    _verify_candidate_identities(candidate_manifest, catalog, inputs)
    _verify_frozen_source(candidate, candidate_manifest, catalog)
    _verify_image(candidate_manifest, inputs)
    smoke = _run_smoke_matches(candidate_manifest, catalog, inputs.platform)
    diagnostic_fixtures = smoke["diagnostic_fixtures"]
    candidate_identities = _mapping(candidate_manifest["identities"], "identities")
    identities = {
        "source": candidate_manifest["source_digest"],
        "image": candidate_manifest["artifact_digest"],
        "runtime": candidate_manifest["runtime"]["identity"],
        "wrapper": candidate_identities["wrapper"],
        "recipe": candidate_identities["recipe"],
        "entrypoint": candidate_identities["entrypoint"],
        "catalog": candidate_identities["catalog"],
        "suite": SUITE_VERSION + "@" + str(candidate_identities["suite_candidate"]).split("@", 1)[1],
        "platform": candidate_identities["platform"],
        "profile": INITIAL_EXECUTION_PROFILE.identity,
        "core_tool": _core_tool_identity(),
        "builder_core_tool": candidate_identities["core_tool"],
    }
    validation_basis = {
        "format": CERTIFICATION_FORMAT_VERSION,
        "mode": inputs.mode,
        "authority": inputs.authority,
        "platform": inputs.platform,
        "profile": inputs.profile,
        "identities": identities,
    }
    validation_identity = _identity(REPORT_FORMAT_VERSION, validation_basis)
    report = {
        "validation_report_format_version": REPORT_FORMAT_VERSION,
        "status": "passed",
        "mode": inputs.mode,
        "authority": inputs.authority,
        "advisory": inputs.authority == "advisory",
        "canonical_tournament_eligible": inputs.authority == "canonical",
        "platform": inputs.platform,
        "profile": inputs.profile,
        "validation_identity": validation_identity,
        "identities": identities,
        "checks": {
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
        },
        "smoke_match": smoke,
        "diagnostic_fixtures": diagnostic_fixtures,
        "host_process_evidence": "insufficient for official validation",
        "notice": (
            "GitHub/AMD64 and participant-local results are advisory and cannot "
            "be accepted as the canonical ARM64 Tournament Bot Artifact."
            if inputs.authority == "advisory"
            else "Organizer-final ARM64 validation is canonical."
        ),
    }
    artifact_manifest = {
        "bot_artifact_manifest_format_version": MANIFEST_FORMAT_VERSION,
        "status": "validated",
        "authority": inputs.authority,
        "artifact_digest": candidate_manifest["artifact_digest"],
        "source_digest": candidate_manifest["source_digest"],
        "runtime_digest": candidate_manifest["runtime_digest"],
        "runtime": candidate_manifest["runtime"],
        "language": "python",
        "platform": inputs.platform,
        "profile": inputs.profile,
        "entrypoint": candidate_manifest["entrypoint"],
        "build_identity": candidate_manifest["build_identity"],
        "validation_identity": validation_identity,
        "identities": identities,
        "image": candidate_manifest["image"],
        "retention": candidate_manifest["retention"],
    }
    staging = Path(tempfile.mkdtemp(prefix="rps-certified-", dir=str(destination.parent)))
    try:
        (staging / "bot-artifact-manifest.json").write_text(json.dumps(artifact_manifest, indent=2, sort_keys=True) + "\n")
        (staging / "validation-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        for path in staging.iterdir():
            path.chmod(0o444)
        staging.chmod(0o555)
        os.replace(staging, destination)
    except BaseException:
        if staging.exists():
            staging.chmod(0o755)
            for path in staging.iterdir():
                path.chmod(0o644)
            shutil.rmtree(staging)
        raise
    return {"manifest": artifact_manifest, "report": report}
