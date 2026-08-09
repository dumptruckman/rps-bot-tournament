"""Stable JSON projections for batch reports and draft Tournament plans."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping, Sequence

from rps_runner.batch_execution import TeamWorkflowResult, TeamWorkflowStatus
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE


PLAN_FORMAT_VERSION = "tournament-plan-v1"
BATCH_REPORT_FORMAT_VERSION = "artifact-batch-report-v1"


class ExecutionMode(str, Enum):
    STEP = "step"
    CONTINUOUS = "continuous"


def project_batch_report(
    results: Sequence[TeamWorkflowResult], jobs: int
) -> Mapping[str, Any]:
    ordered = sorted(results, key=lambda result: result.team.team_id)
    return {
        "batch_report_format_version": BATCH_REPORT_FORMAT_VERSION,
        "operational_limit": jobs,
        "status": (
            "passed"
            if all(result.status is TeamWorkflowStatus.VALIDATED for result in ordered)
            else "failed"
        ),
        "teams": [
            {
                "team_id": str(result.team.team_id),
                "status": result.status.value,
                **({"error": result.error} if result.error else {}),
            }
            for result in ordered
        ],
    }


def project_tournament_plan(
    results: Sequence[TeamWorkflowResult],
    store_index: Mapping[str, Any],
    catalog: object,
    tournament_seed: int,
    execution_mode: ExecutionMode,
    parallelism: int,
) -> Mapping[str, Any]:
    index_identity = store_index["integrity"]["index_identity"]
    profile_values = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
    profile_values.pop("version")
    profile_values.pop("recommended_match_parallelism")
    teams = []
    for result in sorted(results, key=lambda item: item.team.team_id):
        assert result.artifact_manifest is not None
        assert result.selected_source is not None
        selected_source: dict[str, Any] = {
            "source_digest": result.selected_source.source_digest
        }
        if result.selected_source.repair is not None:
            selected_source["repair"] = (
                result.selected_source.repair.retained_evidence()
            )
        manifest = result.artifact_manifest
        teams.append(
            {
                "team_id": str(result.team.team_id),
                "display_name": str(result.team.display_name),
                "roster_ready": True,
                "selected_source": selected_source,
                "bot_artifact_manifest": manifest.as_mapping(),
                "canonical_artifact_identity": (
                    manifest.canonical_identity().as_mapping()
                ),
                "artifact_store_reference": {
                    "index_identity": index_identity,
                    "artifact_digest": manifest.artifact_digest,
                    "platform": manifest.platform,
                },
            }
        )
    return {
        "tournament_plan_format_version": PLAN_FORMAT_VERSION,
        "status": "draft",
        "tournament_seed": tournament_seed,
        "execution": {"mode": execution_mode.value, "parallelism": parallelism},
        "catalog": {"version": catalog.version, "identity": catalog.identity},
        "execution_profile": {
            "version": INITIAL_EXECUTION_PROFILE.version,
            "identity": INITIAL_EXECUTION_PROFILE.identity,
        },
        "global_resources": profile_values,
        "artifact_store": {"index_identity": index_identity},
        "teams": teams,
    }
