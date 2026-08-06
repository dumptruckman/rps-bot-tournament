"""Reproducible capacity workloads and non-binding benchmark reports."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import time
from typing import Optional, TextIO

from .match_executor import MatchExecutionRequest, MatchExecutionResult
from .runner import BotArtifactManifest, Team, TournamentConfig, TournamentRunner
from .state import fold_tournament_state
from .storage import (
    append_operational_telemetry,
    load_competition_records,
    load_manifest,
    load_scoreboard_projection,
)


MAXIMUM_TEAMS = 32
MAXIMUM_QUALIFYING_FIXTURES = 496
MAXIMUM_PLAYOFF_FIXTURES = 3
MAXIMUM_MATCHES = 1_497
MAXIMUM_ROUNDS = 449_100
CONTINUOUS_OBJECTIVE_SECONDS = 20 * 60
STEP_OBJECTIVE_SECONDS = 3


@dataclass(frozen=True)
class BenchmarkReport:
    """One operational measurement against a non-binding objective."""

    name: str
    workload: str
    elapsed_seconds: float
    objective_seconds: float

    @property
    def met_objective(self) -> bool:
        return self.elapsed_seconds <= self.objective_seconds

    @property
    def process_exit_code(self) -> int:
        """An objective miss is report data, never a process failure."""

        return 0


def maximum_capacity_roster() -> tuple[Team, ...]:
    """Build the deterministic maximum roster without live processes."""

    return tuple(
        Team(
            team_id=f"team-{ordinal:02d}",
            display_name=f"Capacity Team {ordinal:02d}",
            bot_artifact=BotArtifactManifest(
                artifact_digest=f"{ordinal:064x}",
                language_id="capacity-benchmark",
                wrapper_version="conforming-draw-v1",
                runtime_digest=f"{ordinal + MAXIMUM_TEAMS:064x}",
                entrypoint=("capacity-benchmark", f"team-{ordinal:02d}"),
            ),
        )
        for ordinal in range(1, MAXIMUM_TEAMS + 1)
    )


def conforming_draw_result(
    request: MatchExecutionRequest,
) -> MatchExecutionResult:
    """Complete all scheduled Rounds without live Bot Artifact processes."""

    round_moves = {request.team_a_id: "R", request.team_b_id: "R"}
    return MatchExecutionResult(
        infrastructure_failure=False,
        competitive_outcome={
            "outcome": "draw",
            "winner_team_id": None,
            "score": {
                request.team_a_id: 0,
                request.team_b_id: 0,
                "draws": request.scheduled_turns,
            },
            "moves": {
                request.team_a_id: "R" * request.scheduled_turns,
                request.team_b_id: "R" * request.scheduled_turns,
            },
            "rounds": [
                {
                    "turn": turn,
                    "moves": round_moves,
                    "winner_team_id": None,
                }
                for turn in range(request.scheduled_turns)
            ],
            "faults": {request.team_a_id: None, request.team_b_id: None},
        },
        operational_telemetry={},
    )


def print_report(report: BenchmarkReport, *, output: TextIO) -> None:
    """Print a stable human-readable operational benchmark report."""

    print(f"Benchmark: {report.name}", file=output)
    print(f"Workload: {report.workload}", file=output)
    print(f"Elapsed: {report.elapsed_seconds:.3f} seconds", file=output)
    print(f"Objective: {report.objective_seconds:.3f} seconds", file=output)
    result = "MET" if report.met_objective else "EXCEEDED (non-binding)"
    print(f"Result: {result}", file=output)


def run_step_preflight(
    tournament_directory: Path,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkReport:
    """Measure one public Step Mode Match through Scoreboard Projection update."""

    runner = TournamentRunner.create(
        tournament_directory,
        tournament_id="capacity-step-preflight",
        tournament_seed=20_260_806,
        roster=maximum_capacity_roster()[:4],
        config=TournamentConfig(execution_mode="step"),
        match_executor=conforming_draw_result,
    )
    started = clock()
    committed = runner.play_next_match()
    projection = load_scoreboard_projection(tournament_directory)
    elapsed = clock() - started
    _record_benchmark_telemetry(
        tournament_directory,
        name="step",
        elapsed_seconds=elapsed,
        objective_seconds=STEP_OBJECTIVE_SECONDS,
    )
    if committed is None or committed.record["type"] != "match_terminal":
        raise RuntimeError("Step preflight did not commit a terminal Match")
    if len(committed.record["rounds"]) != 300:
        raise RuntimeError("Step preflight did not complete 300 Rounds")
    if projection is None or projection["status"] != "paused":
        raise RuntimeError(
            "Step preflight did not publish a paused Scoreboard Projection"
        )
    return BenchmarkReport(
        name="Step Mode preflight",
        workload=(
            "one conforming Match through terminal commit and "
            "Scoreboard Projection update"
        ),
        elapsed_seconds=elapsed,
        objective_seconds=STEP_OBJECTIVE_SECONDS,
    )


def run_continuous_capacity(
    tournament_directory: Path,
    *,
    parallelism: int = 16,
    clock: Callable[[], float] = time.perf_counter,
) -> BenchmarkReport:
    """Run and verify the public maximum Continuous Mode workload."""

    started = clock()
    runner = TournamentRunner.create(
        tournament_directory,
        tournament_id="maximum-capacity-benchmark",
        tournament_seed=20_260_806,
        roster=maximum_capacity_roster(),
        config=TournamentConfig(
            execution_mode="continuous",
            continuous_parallelism=parallelism,
        ),
        match_executor=conforming_draw_result,
    )
    runner.start()
    projection = load_scoreboard_projection(tournament_directory)
    elapsed = clock() - started
    _record_benchmark_telemetry(
        tournament_directory,
        name="continuous",
        elapsed_seconds=elapsed,
        objective_seconds=CONTINUOUS_OBJECTIVE_SECONDS,
    )
    _verify_maximum_capacity(tournament_directory, projection)
    return BenchmarkReport(
        name="Continuous Mode capacity",
        workload="32 Teams; 499 Fixtures; 1,497 Matches; 449,100 Rounds",
        elapsed_seconds=elapsed,
        objective_seconds=CONTINUOUS_OBJECTIVE_SECONDS,
    )


def _verify_maximum_capacity(
    tournament_directory: Path, projection: Optional[dict[str, object]]
) -> None:
    manifest = load_manifest(tournament_directory).manifest
    records = load_competition_records(tournament_directory)
    state = fold_tournament_state(manifest, records)
    qualifying_fixtures = sum(
        len(batch["fixtures"]) for batch in manifest["qualifying_schedule"]
    )
    terminal_records = [
        stored for stored in records if stored.record["type"] == "match_terminal"
    ]
    scheduled_rounds = (
        len(terminal_records) * manifest["scheduled_turns_per_match"]
    )
    completed_rounds = sum(
        len(stored.record["rounds"]) for stored in terminal_records
    )
    checks = {
        "qualifying Fixtures": (
            qualifying_fixtures,
            MAXIMUM_QUALIFYING_FIXTURES,
        ),
        "playoff Fixtures": (
            len(state.playoff_fixtures),
            MAXIMUM_PLAYOFF_FIXTURES,
        ),
        "Matches": (len(terminal_records), MAXIMUM_MATCHES),
        "scheduled Rounds": (scheduled_rounds, MAXIMUM_ROUNDS),
        "completed Rounds": (completed_rounds, MAXIMUM_ROUNDS),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise RuntimeError(
                f"Capacity verification expected {expected} {label}, found {actual}"
            )
    if not state.is_complete or state.champion_team_id is None:
        raise RuntimeError(
            "Capacity Tournament did not declare a Tournament Champion"
        )
    if (
        projection is None
        or projection.get("status") != "complete"
        or projection.get("champion") != state.champion_team_id
    ):
        raise RuntimeError(
            "Capacity Scoreboard Projection does not show canonical completion"
        )


def _record_benchmark_telemetry(
    tournament_directory: Path,
    *,
    name: str,
    elapsed_seconds: float,
    objective_seconds: float,
) -> None:
    append_operational_telemetry(
        tournament_directory,
        {
            "type": "capacity_benchmark",
            "tournament_id": load_manifest(tournament_directory).manifest[
                "tournament_id"
            ],
            "benchmark": name,
            "elapsed_seconds": elapsed_seconds,
            "objective_seconds": objective_seconds,
            "objective_met": elapsed_seconds <= objective_seconds,
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run opt-in Tournament capacity and preflight benchmarks"
    )
    commands = parser.add_subparsers(dest="benchmark", required=True)
    for name in ("continuous", "step"):
        command = commands.add_parser(name)
        command.add_argument(
            "--directory",
            type=Path,
            help="preserve the generated Tournament store at this empty path",
        )
        if name == "continuous":
            command.add_argument("--parallelism", type=int, default=16)
    return parser


def main(
    arguments: Optional[list[str]] = None,
    *,
    output: Optional[TextIO] = None,
) -> int:
    options = build_parser().parse_args(arguments)
    stream = output or sys.stdout
    if options.directory is not None:
        directory = options.directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        report = _run_selected_benchmark(options, directory)
    else:
        with tempfile.TemporaryDirectory(
            prefix="rps-tournament-capacity-"
        ) as temporary_directory:
            report = _run_selected_benchmark(options, Path(temporary_directory))
    print_report(report, output=stream)
    return report.process_exit_code


def _run_selected_benchmark(
    options: argparse.Namespace, directory: Path
) -> BenchmarkReport:
    if options.benchmark == "continuous":
        return run_continuous_capacity(
            directory, parallelism=options.parallelism
        )
    return run_step_preflight(directory)


if __name__ == "__main__":
    raise SystemExit(main())
