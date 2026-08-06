"""Organizer-facing demo CLI for the Tournament Runner."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import hashlib
from pathlib import Path
import shlex
import sys
from typing import Optional, TextIO

from rps_runner.cli import unsigned_64_bit_integer
from rps_runner.engine import InfrastructureError
from rps_runner.tournament.match_executor import (
    LocalMatchExecutor,
    MatchExecutionRequest,
    MatchExecutionResult,
)
from rps_runner.tournament.runner import (
    BotArtifactManifest,
    Team,
    TournamentRunner,
    tournament_manifest_incompatibilities,
)
from rps_runner.tournament.state import NO_ELIGIBLE_TEAMS_REASON
from rps_runner.tournament.storage import (
    StorageError,
    StoredCompetitionRecord,
    load_scoreboard_projection,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ERROR_EXIT_CODE = 2
_ARTIFACT_DIGEST_DOMAIN = b"rps-tournament/demo-bot-artifact/v1\0"
_DEMO_TOURNAMENT_ID = "bundled-bots-demo"
_DEMO_TEAMS = (
    ("copycat-alpha", "Copycat Alpha", "copycat_bot.py"),
    ("copycat-beta", "Copycat Beta", "copycat_bot.py"),
    ("random-alpha", "Random Alpha", "random_bot.py"),
    ("random-beta", "Random Beta", "random_bot.py"),
)


class DemoTournamentCompatibilityError(RuntimeError):
    """An existing sealed Tournament is not the fixed bundled demo."""

    def __init__(self, incompatible_fields: list[str]):
        self.incompatible_fields = tuple(incompatible_fields)
        super().__init__(
            "Existing Tournament is incompatible with the bundled demo: "
            + ", ".join(incompatible_fields)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-tournament",
        description="Run organizer-facing Tournament commands",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="create or resume the bundled four-Team demo Tournament"
    )
    demo.add_argument("--directory", required=True, type=Path)
    demo.add_argument("--seed", required=True, type=unsigned_64_bit_integer)
    execution_scope = demo.add_mutually_exclusive_group()
    execution_scope.add_argument(
        "--all-qualification",
        dest="execution_scope",
        action="store_const",
        const="qualification",
        default="next_match",
    )
    execution_scope.add_argument(
        "--all",
        dest="execution_scope",
        action="store_const",
        const="tournament",
        help="run every remaining Match through Tournament Champion declaration",
    )
    return parser


def main(
    arguments: Optional[list[str]] = None,
    *,
    match_executor: Optional[
        Callable[[MatchExecutionRequest], MatchExecutionResult]
    ] = None,
    project_root: Path = PROJECT_ROOT,
    python_executable: Optional[Path] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    options = build_parser().parse_args(arguments)
    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    directory = options.directory.expanduser().resolve()
    executable = (
        python_executable or Path(sys.executable)
    ).expanduser().absolute()
    resolved_project_root = project_root.expanduser().resolve()

    try:
        executor = match_executor or LocalMatchExecutor(
            _demo_artifact_command_resolver(resolved_project_root, executable)
        ).execute
        if directory.exists():
            runner = TournamentRunner.open(
                directory,
                match_executor=executor,
                artifact_digest_verifier=_demo_artifact_digest_verifier(
                    resolved_project_root
                ),
                sealed_manifest_verifier=lambda manifest: _verify_demo_manifest(
                    manifest,
                    tournament_seed=options.seed,
                    project_root=resolved_project_root,
                    python_executable=executable,
                ),
            )
            disposition = "resumed"
        else:
            roster = _demo_roster(resolved_project_root, executable)
            runner = TournamentRunner.create(
                directory,
                tournament_id=_DEMO_TOURNAMENT_ID,
                tournament_seed=options.seed,
                roster=roster,
                match_executor=executor,
            )
            disposition = "created"
        committed_records: list[StoredCompetitionRecord] = []
        while True:
            projection = load_scoreboard_projection(directory)
            if (
                options.execution_scope == "qualification"
                and projection is not None
                and projection["phase"] != "qualifying"
            ):
                break
            committed = runner.play_next_match()
            if committed is None:
                break
            committed_records.append(committed)
            if options.execution_scope == "next_match":
                break
        _print_summary(
            directory,
            disposition=disposition,
            committed_records=committed_records,
            output=output,
        )
    except (OSError, RuntimeError, StorageError, TypeError, ValueError) as error:
        print(f"rps-tournament: {error}", file=error_output)
        return ERROR_EXIT_CODE
    return 0


def _demo_roster(
    project_root: Path, python_executable: Path
) -> tuple[Team, ...]:
    bots_directory = project_root / "bots"
    wrapper = bots_directory / "python_wrapper.py"
    runtime_digest = _sha256_file(python_executable)
    teams: list[Team] = []
    for team_id, display_name, bot_filename in _DEMO_TEAMS:
        bot_path = bots_directory / bot_filename
        artifact_digest = _bot_artifact_digest(wrapper, bot_path)
        teams.append(
            Team(
                team_id,
                display_name,
                BotArtifactManifest(
                    artifact_digest=artifact_digest,
                    language_id="python",
                    wrapper_version="python-wrapper-1",
                    runtime_digest=runtime_digest,
                    entrypoint=("python3", bot_filename),
                ),
            )
        )
    return tuple(teams)


def _bot_artifact_digest(wrapper: Path, strategy: Path) -> str:
    digest = hashlib.sha256(_ARTIFACT_DIGEST_DOMAIN)
    for logical_name, path in (
        ("python_wrapper.py", wrapper),
        ("strategy.py", strategy),
    ):
        name = logical_name.encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _demo_artifact_digest_verifier(
    project_root: Path,
) -> Callable[[str, str], bool]:
    def verify(team_id: str, artifact_digest: str) -> bool:
        try:
            bot_filename = _demo_bot_filename(team_id)
        except KeyError:
            return False
        bots_directory = project_root / "bots"
        return artifact_digest == _bot_artifact_digest(
            bots_directory / "python_wrapper.py",
            bots_directory / bot_filename,
        )

    return verify


def _demo_artifact_command_resolver(
    project_root: Path, python_executable: Path
) -> Callable[[str, str], str]:
    verify_digest = _demo_artifact_digest_verifier(project_root)

    def resolve(team_id: str, artifact_digest: str) -> str:
        try:
            bot_filename = _demo_bot_filename(team_id)
        except KeyError as error:
            raise InfrastructureError(
                f"no local command resolves Team {team_id}"
            ) from error
        if not verify_digest(team_id, artifact_digest):
            raise InfrastructureError(
                f"Bot Artifact digest verification failed for {team_id}"
            )
        return shlex.join(
            [str(python_executable), str(project_root / "bots" / bot_filename)]
        )

    return resolve


def _demo_bot_filename(team_id: str) -> str:
    for candidate_team_id, _display_name, bot_filename in _DEMO_TEAMS:
        if candidate_team_id == team_id:
            return bot_filename
    raise KeyError(team_id)


def _verify_demo_manifest(
    manifest: dict[str, object],
    *,
    tournament_seed: int,
    project_root: Path,
    python_executable: Path,
) -> None:
    incompatible_fields = tournament_manifest_incompatibilities(
        manifest,
        tournament_id=_DEMO_TOURNAMENT_ID,
        tournament_seed=tournament_seed,
        roster=_demo_roster(project_root, python_executable),
    )
    if incompatible_fields:
        raise DemoTournamentCompatibilityError(list(incompatible_fields))


def _print_summary(
    directory: Path,
    *,
    disposition: str,
    committed_records: list[StoredCompetitionRecord],
    output: TextIO,
) -> None:
    projection = load_scoreboard_projection(directory)
    if projection is None:
        raise RuntimeError("Scoreboard Projection is missing")

    print(f"Tournament: {disposition}", file=output)
    for stored in committed_records:
        record = stored.record
        print(f"Committed Match: {record['match_id']}", file=output)
        print(f"  Teams: {' vs '.join(record['team_ids'])}", file=output)
        winner = record["winner_team_id"]
        outcome = record["outcome"]
        if winner is not None:
            outcome = f"{outcome} ({winner})"
        print(f"  Outcome: {outcome}", file=output)
        print(f"  Match Seed: {record['match_seed']}", file=output)

    fixtures = projection["fixtures"]
    complete = sum(fixture["status"] == "complete" for fixture in fixtures)
    in_progress = sum(
        fixture["status"] == "in_progress" for fixture in fixtures
    )
    skipped = sum(fixture["status"] == "skipped" for fixture in fixtures)
    scheduled = sum(fixture["status"] == "scheduled" for fixture in fixtures)
    print(
        f"Qualifying Fixtures: {complete}/{len(fixtures)} complete, "
        f"{in_progress} in progress, {scheduled} scheduled, {skipped} skipped",
        file=output,
    )
    print("Standings:", file=output)
    for rank, standing in enumerate(projection["standings"], start=1):
        print(
            f"  {rank}. {standing['team_id']} — "
            f"{standing['standing_points']} Standing Points, "
            f"{standing['series_wins']} Series wins, "
            f"Match diff {standing['match_differential']}, "
            f"Round diff {standing['round_differential']}",
            file=output,
        )
    bracket = projection.get("bracket")
    if bracket is not None:
        playoff_fixtures = bracket["fixtures"]
        playoff_complete = sum(
            fixture["status"] == "complete" for fixture in playoff_fixtures
        )
        playoff_in_progress = sum(
            fixture["status"] == "in_progress" for fixture in playoff_fixtures
        )
        playoff_scheduled = (
            len(playoff_fixtures) - playoff_complete - playoff_in_progress
        )
        print(
            f"Playoff Fixtures: {playoff_complete}/{len(playoff_fixtures)} "
            f"complete, {playoff_in_progress} in progress, "
            f"{playoff_scheduled} scheduled",
            file=output,
        )
    print("Artifacts:", file=output)
    print(f"  Sealed Manifest: {directory / 'manifest.json'}", file=output)
    print(f"  Competition Records: {directory / 'records'}", file=output)
    print(f"  Operational Telemetry: {directory / 'telemetry'}", file=output)
    print(f"  Scoreboard Projection: {directory / 'scoreboard.json'}", file=output)
    if complete + skipped == len(fixtures):
        print("Qualification has no unresolved Match.", file=output)
    champion = projection["champion"]
    if projection.get("completion_reason") == NO_ELIGIBLE_TEAMS_REASON:
        print(
            "Tournament ended without a Tournament Champion: "
            "no eligible Teams remain.",
            file=output,
        )
    elif champion is None:
        print("No Tournament Champion has been declared.", file=output)
    else:
        print(f"Tournament Champion: {champion}", file=output)


if __name__ == "__main__":
    raise SystemExit(main())
