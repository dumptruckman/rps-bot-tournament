"""Build organizer-selected Team sources into a reviewable Tournament plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, TextIO

from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import certify_artifact_candidate
from rps_runner.artifact_store import ArtifactSelection, preserve_artifact_set
from rps_runner.batch_execution import (
    BatchExecutor,
    BatchOperations,
    TeamWorkflowStatus,
)
from rps_runner.batch_projection import (
    ExecutionMode,
    project_batch_report,
    project_tournament_plan,
)
from rps_runner.batch_team_sources import load_team_sources
from rps_runner.cli import unsigned_64_bit_integer
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import freeze_source_bundle, load_catalog


ERROR_EXIT_CODE = 2

DEFAULT_OPERATIONS = BatchOperations(
    freeze_source_bundle,
    build_artifact_candidate,
    certify_artifact_candidate,
    preserve_artifact_set,
)


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-batch-plan",
        description=(
            "Build and validate organizer-selected local Team sources, preserve "
            "their Bot Artifacts, and write a draft JSON Tournament plan"
        ),
    )
    parser.add_argument("--teams", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--tournament-seed", required=True, type=unsigned_64_bit_integer
    )
    parser.add_argument(
        "--execution-mode",
        choices=(ExecutionMode.STEP.value, ExecutionMode.CONTINUOUS.value),
        type=ExecutionMode,
        default=ExecutionMode.CONTINUOUS,
    )
    parser.add_argument(
        "--parallelism",
        type=_positive_integer,
        help="planned Match parallelism (defaults to four in Continuous Mode)",
    )
    parser.add_argument(
        "--jobs",
        required=True,
        type=_positive_integer,
        help="maximum concurrently active Team build/validation workflows",
    )
    parser.add_argument(
        "--retain-practice-images",
        action="store_true",
        help="retain conformance practice images for organizer readiness evidence",
    )
    return parser


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main(
    arguments: Optional[list[str]] = None,
    *,
    operations: BatchOperations = DEFAULT_OPERATIONS,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    options = build_parser().parse_args(arguments)
    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    try:
        teams = load_team_sources(options.teams)
        catalog = load_catalog(options.catalog)
        destination = options.output.expanduser().resolve()
        if destination.exists() or destination.is_symlink():
            raise ValueError(
                "output destination already exists and will not be replaced"
            )
        destination.mkdir(parents=True)
        team_directory = destination / "teams"
        team_directory.mkdir()

        results = BatchExecutor(
            catalog,
            catalog.environment(options.environment),
            operations,
            options.retain_practice_images,
        ).execute(teams, team_directory, options.jobs)
        report = project_batch_report(results, options.jobs)
        _write_json(destination / "batch-report.json", report)
        if report["status"] != "passed":
            print(
                "rps-batch-plan: one or more Team workflows failed; "
                "see batch-report.json",
                file=error_output,
            )
            return ERROR_EXIT_CODE

        selections = []
        seen_artifacts: set[str] = set()
        for result in sorted(results, key=lambda item: item.team.team_id):
            assert result.status is TeamWorkflowStatus.VALIDATED
            assert result.candidate is not None
            assert result.certification is not None
            assert result.artifact_manifest is not None
            artifact_digest = result.artifact_manifest.artifact_digest
            if artifact_digest not in seen_artifacts:
                selections.append(
                    ArtifactSelection(result.candidate, result.certification)
                )
                seen_artifacts.add(artifact_digest)
        store_index = operations.preserve(destination / "artifact-store", selections)
        parallelism = options.parallelism or (
            INITIAL_EXECUTION_PROFILE.recommended_match_parallelism
            if options.execution_mode is ExecutionMode.CONTINUOUS
            else 1
        )
        plan = project_tournament_plan(
            results,
            store_index,
            catalog,
            options.tournament_seed,
            options.execution_mode,
            parallelism,
        )
        _write_json(destination / "tournament-plan.json", plan)
        print(json.dumps(plan, indent=2, sort_keys=True), file=output)
        return 0
    except (KeyError, OSError, TypeError, ValueError) as error:
        print("rps-batch-plan: " + str(error), file=error_output)
        return ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
