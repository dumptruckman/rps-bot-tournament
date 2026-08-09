"""Validate a reviewable artifact plan into sealed Tournament inputs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from rps_runner.execution_profile import ExecutionProfile, INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import LanguageEnvironmentCatalog

from .execution_inputs import TournamentExecutionInputs
from .retained_artifacts import (
    RetainedBotArtifactRequirement,
    canonical_artifact_identity,
    validate_bot_artifact_manifest,
    verify_retained_bot_artifacts,
)
from .runner import (
    BotArtifactManifest,
    ContainerTournamentIdentity,
    MatchLimits,
    Team,
    TournamentConfig,
)


PLAN_FORMAT_VERSION = "tournament-plan-v1"
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_RESOURCE_FIELDS = frozenset(
    key
    for key in INITIAL_EXECUTION_PROFILE.as_mapping()
    if key not in {"version", "recommended_match_parallelism"}
)


@dataclass(frozen=True)
class ValidatedTournamentPlan:
    tournament_seed: int
    roster: tuple[Team, ...]
    config: TournamentConfig
    execution_inputs: TournamentExecutionInputs


def read_tournament_plan(path: Path) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Tournament plan must be an existing non-symlink file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Tournament plan is corrupt or unreadable: " + str(error))
    if not isinstance(value, dict):
        raise ValueError("Tournament plan must be a JSON object")
    return value


def validate_tournament_plan(
    plan_path: Path,
    artifact_store: Path,
    catalog: LanguageEnvironmentCatalog,
) -> ValidatedTournamentPlan:
    plan = read_tournament_plan(plan_path)
    _exact_fields(
        plan,
        {
            "tournament_plan_format_version",
            "status",
            "tournament_seed",
            "execution",
            "catalog",
            "execution_profile",
            "global_resources",
            "artifact_store",
            "teams",
        },
        "Tournament plan",
    )
    if plan.get("tournament_plan_format_version") != PLAN_FORMAT_VERSION:
        raise ValueError("Tournament plan format is unsupported")
    if plan.get("status") != "draft":
        raise ValueError("Tournament plan must be an unsealed draft")

    catalog_record = _object(plan.get("catalog"), "catalog")
    _exact_fields(catalog_record, {"version", "identity"}, "catalog")
    if (
        catalog_record.get("version") != catalog.version
        or catalog_record.get("identity") != catalog.identity
    ):
        raise ValueError("Tournament plan uses a stale or mismatched catalog")
    environment = catalog.environment("python")

    execution = _object(plan.get("execution"), "execution")
    _exact_fields(execution, {"mode", "parallelism"}, "execution")
    mode = execution.get("mode")
    parallelism = execution.get("parallelism")
    if mode not in ("step", "continuous"):
        raise ValueError("Tournament plan execution mode is invalid")
    _positive_integer(parallelism, "execution.parallelism")

    profile_record = _object(plan.get("execution_profile"), "execution_profile")
    _exact_fields(
        profile_record, {"version", "identity"}, "execution_profile"
    )
    resources = _object(plan.get("global_resources"), "global_resources")
    if set(resources) != _RESOURCE_FIELDS:
        raise ValueError("Tournament plan global resources are incomplete")
    profile = ExecutionProfile(
        version=_string(profile_record.get("version"), "execution_profile.version"),
        recommended_match_parallelism=(
            INITIAL_EXECUTION_PROFILE.recommended_match_parallelism
        ),
        **resources,
    )
    if profile.version != INITIAL_EXECUTION_PROFILE.version:
        raise ValueError("Tournament plan execution profile version is unsupported")
    for field in _RESOURCE_FIELDS:
        value = getattr(profile, field)
        if field.endswith("_seconds"):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(field + " must be finite and positive")
        elif not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(field + " must be a positive integer")
    if profile_record.get("identity") != profile.identity:
        raise ValueError("Tournament plan execution profile identity is stale")

    plan_store = _object(plan.get("artifact_store"), "artifact_store")
    _exact_fields(plan_store, {"index_identity"}, "artifact_store")
    index_identity = plan_store.get("index_identity")

    team_values = plan.get("teams")
    if not isinstance(team_values, list) or not 4 <= len(team_values) <= 32:
        raise ValueError("Tournament plan must contain four through thirty-two Teams")
    roster: list[Team] = []
    retained_requirements: list[RetainedBotArtifactRequirement] = []
    for ordinal, value in enumerate(team_values):
        location = f"teams[{ordinal}]"
        team = _object(value, location)
        _exact_fields(
            team,
            {
                "team_id",
                "display_name",
                "roster_ready",
                "selected_source",
                "bot_artifact_manifest",
                "canonical_artifact_identity",
                "artifact_store_reference",
            },
            location,
        )
        if team.get("roster_ready") is not True:
            raise ValueError(location + " is not roster-ready")
        team_id = _string(team.get("team_id"), location + ".team_id")
        display_name = _string(
            team.get("display_name"), location + ".display_name"
        )
        selected_source = _object(
            team.get("selected_source"), location + ".selected_source"
        )
        _validate_selected_source(selected_source, location)
        manifest = _object(
            team.get("bot_artifact_manifest"),
            location + ".bot_artifact_manifest",
        )
        repair = selected_source.get("repair")
        if isinstance(repair, dict) and repair.get(
            "final_validation_identity"
        ) != manifest.get("validation_identity"):
            raise ValueError(location + " compatibility repair validation mismatch")
        canonical = canonical_artifact_identity(manifest)
        if team.get("canonical_artifact_identity") != canonical:
            raise ValueError(location + " canonical Bot Artifact identity mismatch")
        validate_bot_artifact_manifest(
            manifest,
            str(selected_source.get("source_digest")),
            catalog,
            environment,
            profile,
            location,
        )
        digest = str(manifest["artifact_digest"])
        platform = str(manifest["platform"])
        reference = _object(
            team.get("artifact_store_reference"),
            location + ".artifact_store_reference",
        )
        if reference != {
            "index_identity": index_identity,
            "artifact_digest": digest,
            "platform": platform,
        }:
            raise ValueError(location + " artifact-store reference mismatch")
        identities = _object(manifest["identities"], location + ".identities")
        roster.append(
            Team(
                team_id,
                display_name,
                BotArtifactManifest(
                    artifact_digest=digest,
                    language_id=str(manifest["language"]),
                    wrapper_version=str(identities["wrapper"]),
                    runtime_digest=str(manifest["runtime_digest"]),
                    entrypoint=tuple(manifest["entrypoint"]),
                    canonical_identity=canonical,
                ),
            )
        )
        retained_requirements.append(
            RetainedBotArtifactRequirement(location, digest, platform, canonical)
        )

    platforms = verify_retained_bot_artifacts(
        artifact_store,
        index_identity,
        retained_requirements,
        catalog,
        profile,
    )

    selected_platforms = set(platforms.values())
    if selected_platforms != {"linux/arm64"}:
        raise ValueError("Official Tournament requires organizer-final linux/arm64 images")
    tournament_seed = plan.get("tournament_seed")
    if (
        not isinstance(tournament_seed, int)
        or isinstance(tournament_seed, bool)
        or not 0 <= tournament_seed < 1 << 64
    ):
        raise ValueError("Tournament Seed must be an unsigned 64-bit integer")

    match_limits = MatchLimits(
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
    execution_inputs = TournamentExecutionInputs(
        platforms,
        profile.startup_timeout_seconds,
        profile.shutdown_timeout_seconds,
    )
    return ValidatedTournamentPlan(
        tournament_seed=tournament_seed,
        roster=tuple(roster),
        config=TournamentConfig(
            execution_mode=str(mode),
            match_limits=match_limits,
            continuous_parallelism=int(parallelism),
            execution_profile_version=profile.version,
            container_identity=ContainerTournamentIdentity(
                execution_profile_identity=profile.identity,
                catalog_version=catalog.version,
                catalog_identity=catalog.identity,
                artifact_store_index_identity=str(index_identity),
                target_platform="linux/arm64",
                startup_timeout_seconds=profile.startup_timeout_seconds,
                shutdown_timeout_seconds=profile.shutdown_timeout_seconds,
            ),
        ),
        execution_inputs=execution_inputs,
    )


def validate_sealed_tournament_artifacts(
    manifest: Mapping[str, Any],
    artifact_store: Path,
    catalog: LanguageEnvironmentCatalog,
) -> TournamentExecutionInputs:
    """Verify archived execution inputs directly against a sealed Tournament."""

    if manifest.get("executor_kind") != "container":
        raise ValueError("Sealed Tournament is not an official container Tournament")
    if (
        manifest.get("catalog_version") != catalog.version
        or manifest.get("catalog_identity") != catalog.identity
    ):
        raise ValueError("Sealed Tournament catalog identity mismatch")
    target_platform = manifest.get("target_platform")
    if target_platform != "linux/arm64":
        raise ValueError("Sealed Tournament target platform is invalid")

    limits = _object(manifest.get("match_limits"), "sealed match_limits")
    profile_values: dict[str, Any] = {}
    for field in _RESOURCE_FIELDS:
        if field in ("startup_timeout_seconds", "shutdown_timeout_seconds"):
            profile_values[field] = manifest.get(field)
        else:
            profile_values[field] = limits.get(field)
    try:
        profile = ExecutionProfile(
            version=_string(
                manifest.get("execution_profile_version"),
                "sealed execution_profile_version",
            ),
            recommended_match_parallelism=(
                INITIAL_EXECUTION_PROFILE.recommended_match_parallelism
            ),
            **profile_values,
        )
    except TypeError as error:
        raise ValueError("Sealed Tournament execution profile is incomplete") from error
    if manifest.get("execution_profile_identity") != profile.identity:
        raise ValueError("Sealed Tournament execution-profile identity mismatch")

    roster = manifest.get("roster")
    if not isinstance(roster, list) or not roster:
        raise ValueError("Sealed Tournament roster is invalid")
    retained_requirements: list[RetainedBotArtifactRequirement] = []
    for ordinal, team_value in enumerate(roster):
        location = f"sealed roster[{ordinal}]"
        team = _object(team_value, location)
        canonical = _object(team.get("bot_artifact"), location + ".bot_artifact")
        digest = _string(canonical.get("artifact_digest"), location + ".digest")
        platform = _string(canonical.get("platform"), location + ".platform")
        if platform != target_platform:
            raise ValueError(location + " platform does not match the sealed target")
        retained_requirements.append(
            RetainedBotArtifactRequirement(location, digest, platform, canonical)
        )
    platforms = verify_retained_bot_artifacts(
        artifact_store,
        manifest.get("artifact_store_index_identity"),
        retained_requirements,
        catalog,
        profile,
    )
    return TournamentExecutionInputs(
        platforms,
        profile.startup_timeout_seconds,
        profile.shutdown_timeout_seconds,
    )


def _validate_selected_source(
    selected_source: Mapping[str, Any], location: str
) -> None:
    if set(selected_source) not in ({"source_digest"}, {"source_digest", "repair"}):
        raise ValueError(location + ".selected_source fields are invalid")
    source_digest = selected_source.get("source_digest")
    if not isinstance(source_digest, str) or _DIGEST.fullmatch(source_digest) is None:
        raise ValueError(location + " selected source digest is invalid")
    repair = selected_source.get("repair")
    if repair is None:
        return
    repair_record = _object(repair, location + ".selected_source.repair")
    _exact_fields(
        repair_record,
        {
            "original_source_digest",
            "replacement_source_digest",
            "diff",
            "diff_digest",
            "explanation",
            "final_validation_identity",
        },
        location + ".selected_source.repair",
    )
    for field in ("original_source_digest", "replacement_source_digest", "diff_digest"):
        value = repair_record.get(field)
        if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
            raise ValueError(location + " compatibility repair identity is invalid")
    for field in ("diff", "explanation", "final_validation_identity"):
        _string(repair_record.get(field), location + ".selected_source.repair." + field)
    expected_diff_digest = "sha256:" + hashlib.sha256(
        str(repair_record["diff"]).encode("utf-8")
    ).hexdigest()
    if repair_record["diff_digest"] != expected_diff_digest:
        raise ValueError(location + " compatibility repair diff mismatch")
    if repair_record["replacement_source_digest"] != source_digest:
        raise ValueError(location + " compatibility repair replacement mismatch")


def _exact_fields(
    value: Mapping[str, Any], expected: set[str] | frozenset[str], location: str
) -> None:
    if set(value) != set(expected):
        missing = sorted(set(expected) - set(value))
        unexpected = sorted(set(value) - set(expected))
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


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must be a non-empty string")
    return value


def _positive_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(field + " must be a positive integer")
    return value
