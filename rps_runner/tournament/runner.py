"""Highest-level Tournament creation and Step Mode orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Optional, Union

from .competition import (
    MatchOutcome,
    MatchResult,
    Phase,
    Series,
    Standing,
    rank_standings,
)
from .locking import TournamentRunLock
from .match_executor import MatchExecutionRequest, MatchExecutionResult
from .schedule import (
    Fixture,
    FixtureBatch,
    bot_positions,
    build_qualifying_schedule,
)
from .seeding import (
    SEED_DERIVATION_VERSION,
    derive_bot_seed,
    derive_match_seed,
    derive_tiebreak_key,
)
from .storage import (
    StoredCompetitionRecord,
    append_competition_record,
    append_operational_telemetry,
    load_competition_records,
    load_manifest,
    load_scoreboard_projection,
    seal_manifest,
    write_scoreboard_projection,
)


PROTOCOL_VERSION = 1
RECORD_SCHEMA_VERSION = 1
SCOREBOARD_VERSION = 1
SCHEDULED_TURNS_PER_MATCH = 300
FIRST_MOVE_TIMEOUT_MS = 250
MOVE_TIMEOUT_MS = 50
TOTAL_TIMEOUT_MS = 2000
STDERR_LIMIT_BYTES = 65_536
_MAX_U64 = (1 << 64) - 1
_TEAM_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
_LANGUAGE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_DIGEST_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


@dataclass(frozen=True)
class BotArtifactManifest:
    artifact_digest: str
    language_id: str
    wrapper_version: str
    runtime_digest: str
    entrypoint: tuple[str, ...]


@dataclass(frozen=True)
class Team:
    team_id: str
    display_name: str
    bot_artifact: BotArtifactManifest


@dataclass
class TournamentRunner:
    tournament_directory: Path
    match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult]
    _manifest: dict[str, Any]

    @classmethod
    def create(
        cls,
        tournament_directory: Union[Path, str],
        *,
        tournament_id: str,
        tournament_seed: int,
        roster: Iterable[Team],
        match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult],
    ) -> "TournamentRunner":
        teams = tuple(roster)
        _validate_creation_inputs(tournament_id, tournament_seed, teams)
        schedule = build_qualifying_schedule(
            (team.team_id for team in teams), tournament_seed
        )
        canonical_roster = tuple(sorted(teams, key=lambda team: team.team_id))
        manifest = {
            "tournament_id": tournament_id,
            "tournament_seed": str(tournament_seed),
            "protocol_version": PROTOCOL_VERSION,
            "seed_derivation_version": SEED_DERIVATION_VERSION,
            "record_schema_version": RECORD_SCHEMA_VERSION,
            "scheduled_turns_per_match": SCHEDULED_TURNS_PER_MATCH,
            "match_limits": {
                "first_move_timeout_ms": FIRST_MOVE_TIMEOUT_MS,
                "move_timeout_ms": MOVE_TIMEOUT_MS,
                "total_timeout_ms": TOTAL_TIMEOUT_MS,
                "stderr_limit_bytes": STDERR_LIMIT_BYTES,
            },
            "series_format": "best_of_three",
            "roster": [_serialize_team(team) for team in canonical_roster],
            "tie_break_keys": {
                team.team_id: str(
                    derive_tiebreak_key(tournament_seed, team.team_id)
                )
                for team in canonical_roster
            },
            "qualifying_schedule": [
                _serialize_batch(batch) for batch in schedule
            ],
        }
        directory = Path(tournament_directory)
        directory.mkdir(parents=True, exist_ok=True)
        with TournamentRunLock(directory):
            seal_manifest(directory, manifest)
            write_scoreboard_projection(
                directory,
                _initial_projection(manifest),
            )
        return cls(directory, match_executor, manifest)

    @classmethod
    def open(
        cls,
        tournament_directory: Union[Path, str],
        *,
        match_executor: Callable[[MatchExecutionRequest], MatchExecutionResult],
    ) -> "TournamentRunner":
        directory = Path(tournament_directory)
        with TournamentRunLock(directory):
            stored = load_manifest(directory)
            load_competition_records(directory)
        return cls(directory, match_executor, stored.manifest)

    @property
    def status(self) -> str:
        projection = load_scoreboard_projection(self.tournament_directory)
        if projection is None:
            return "paused"
        return str(projection["status"])

    def play_next_match(self) -> Optional[StoredCompetitionRecord]:
        with TournamentRunLock(self.tournament_directory):
            records = load_competition_records(self.tournament_directory)
            selected = _select_next_match(self._manifest, records)
            if selected is None:
                return None
            fixture, match_ordinal = selected
            request = _build_match_request(
                self._manifest, fixture, match_ordinal
            )
            execution_result = self.match_executor(request)
            result = _normalize_executor_result(execution_result, fixture)
            if execution_result.operational_telemetry:
                append_operational_telemetry(
                    self.tournament_directory,
                    execution_result.operational_telemetry,
                )
            stored = append_competition_record(
                self.tournament_directory,
                _terminal_record(request, fixture, match_ordinal, result),
            )
            all_records = records + [stored]
            write_scoreboard_projection(
                self.tournament_directory,
                _projection_from_records(self._manifest, all_records),
            )
            return stored


def _validate_creation_inputs(
    tournament_id: str,
    tournament_seed: int,
    roster: tuple[Team, ...],
) -> None:
    if not isinstance(tournament_id, str) or not tournament_id.strip():
        raise ValueError("Tournament ID must be a non-empty string")
    if not isinstance(tournament_seed, int) or isinstance(tournament_seed, bool):
        raise TypeError("Tournament Seed must be an integer")
    if not 0 <= tournament_seed <= _MAX_U64:
        raise ValueError("Tournament Seed must be an unsigned 64-bit integer")
    if not 4 <= len(roster) <= 32:
        raise ValueError("Roster must contain between 4 and 32 Teams")
    team_ids = [team.team_id for team in roster]
    if len(team_ids) != len(set(team_ids)):
        raise ValueError("Team IDs must be unique within a Tournament")
    for team in roster:
        if _TEAM_ID_PATTERN.fullmatch(team.team_id) is None:
            raise ValueError(f"Malformed Team ID: {team.team_id!r}")
        if not isinstance(team.display_name, str) or not team.display_name.strip():
            raise ValueError("Team Display Name must be a non-empty string")
        _validate_artifact(team.bot_artifact)


def _validate_artifact(artifact: BotArtifactManifest) -> None:
    if not isinstance(artifact, BotArtifactManifest):
        raise ValueError("Every Team requires one Bot Artifact Manifest")
    if _DIGEST_PATTERN.fullmatch(artifact.artifact_digest) is None:
        raise ValueError("Bot Artifact digest must be a SHA-256 digest")
    if _LANGUAGE_ID_PATTERN.fullmatch(artifact.language_id) is None:
        raise ValueError("Bot Artifact language ID is invalid")
    if not artifact.wrapper_version.strip():
        raise ValueError("Bot Artifact wrapper version is required")
    if _DIGEST_PATTERN.fullmatch(artifact.runtime_digest) is None:
        raise ValueError("Bot Artifact runtime digest is invalid")
    if (
        not isinstance(artifact.entrypoint, tuple)
        or not artifact.entrypoint
        or any(
            not isinstance(argument, str) or not argument or "\x00" in argument
            for argument in artifact.entrypoint
        )
    ):
        raise ValueError("Bot Artifact entrypoint must be an argument array")


def _serialize_team(team: Team) -> dict[str, Any]:
    artifact = team.bot_artifact
    return {
        "team_id": team.team_id,
        "display_name": team.display_name,
        "bot_artifact": {
            "artifact_digest": artifact.artifact_digest,
            "language_id": artifact.language_id,
            "wrapper_version": artifact.wrapper_version,
            "runtime_digest": artifact.runtime_digest,
            "entrypoint": list(artifact.entrypoint),
        },
    }


def _serialize_fixture(fixture: Fixture) -> dict[str, Any]:
    return {
        "fixture_id": fixture.fixture_id,
        "ordinal": fixture.ordinal,
        "batch_ordinal": fixture.batch_ordinal,
        "team_ids": list(fixture.team_ids),
        "fixture_seed": str(fixture.fixture_seed),
    }


def _serialize_batch(batch: FixtureBatch) -> dict[str, Any]:
    return {
        "ordinal": batch.ordinal,
        "bye_team_id": batch.bye_team_id,
        "fixtures": [_serialize_fixture(fixture) for fixture in batch.fixtures],
    }


def _initial_projection(manifest: dict[str, Any]) -> dict[str, Any]:
    fixtures = [
        fixture
        for batch in manifest["qualifying_schedule"]
        for fixture in batch["fixtures"]
    ]
    return {
        "version": SCOREBOARD_VERSION,
        "tournament_id": manifest["tournament_id"],
        "status": "paused",
        "phase": "qualifying",
        "teams": [
            {
                "team_id": team["team_id"],
                "display_name": team["display_name"],
            }
            for team in manifest["roster"]
        ],
        "fixtures": [
            {
                "fixture_id": fixture["fixture_id"],
                "team_ids": fixture["team_ids"],
                "status": "scheduled",
                "matches": [],
            }
            for fixture in fixtures
        ],
        "standings": _standing_projection(manifest, {}),
        "champion": None,
    }


def _manifest_fixtures(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fixture
        for batch in manifest["qualifying_schedule"]
        for fixture in batch["fixtures"]
    ]


def _select_next_match(
    manifest: dict[str, Any],
    records: list[StoredCompetitionRecord],
) -> Optional[tuple[dict[str, Any], int]]:
    terminal_by_fixture: dict[str, list[dict[str, Any]]] = {}
    for stored in records:
        record = stored.record
        if record.get("type") == "match_terminal":
            terminal_by_fixture.setdefault(record["fixture_id"], []).append(
                record
            )

    for fixture in _manifest_fixtures(manifest):
        fixture_records = sorted(
            terminal_by_fixture.get(fixture["fixture_id"], ()),
            key=lambda record: record["match_ordinal"],
        )
        series = _series_from_records(fixture, fixture_records)
        if series.is_complete:
            continue
        return fixture, len(fixture_records) + 1
    return None


def _series_from_records(
    fixture: dict[str, Any], records: Iterable[dict[str, Any]]
) -> Series:
    team_one_id, team_two_id = fixture["team_ids"]
    series = Series(team_one_id, team_two_id, Phase.QUALIFYING)
    for record in records:
        series = series.record(_match_result_from_record(record))
    return series


def _match_result_from_record(record: dict[str, Any]) -> MatchResult:
    team_one_id, team_two_id = record["team_ids"]
    round_wins = record["round_wins"]
    completed_round_wins = (
        round_wins[team_one_id],
        round_wins[team_two_id],
    )
    outcome = MatchOutcome(record["outcome"])
    if outcome is MatchOutcome.DOUBLE_FORFEIT:
        return MatchResult.double_forfeit(team_one_id, team_two_id)
    if outcome is MatchOutcome.DRAW:
        return MatchResult.draw(
            team_one_id,
            team_two_id,
            round_wins=completed_round_wins,
        )
    faulting_team_id = record["protocol_forfeit_team_id"]
    if faulting_team_id is not None:
        return MatchResult.protocol_forfeit(
            team_one_id,
            team_two_id,
            faulting_team_id=faulting_team_id,
            completed_round_wins=completed_round_wins,
        )
    return MatchResult.win(
        team_one_id,
        team_two_id,
        record["winner_team_id"],
        round_wins=completed_round_wins,
    )


def _build_match_request(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    match_ordinal: int,
) -> MatchExecutionRequest:
    fixture_seed = int(fixture["fixture_seed"])
    match_seed = derive_match_seed(fixture_seed, match_ordinal)
    team_ids = tuple(fixture["team_ids"])
    assert len(team_ids) == 2
    positions = bot_positions(
        fixture_seed, match_ordinal, team_ids[0], team_ids[1]
    )
    artifacts = {
        team["team_id"]: _artifact_from_manifest(team["bot_artifact"])
        for team in manifest["roster"]
    }
    bot_seeds = {
        team_id: derive_bot_seed(match_seed, team_id) for team_id in team_ids
    }
    limits = manifest["match_limits"]
    return MatchExecutionRequest(
        tournament_id=manifest["tournament_id"],
        fixture_id=fixture["fixture_id"],
        series_id=f"{fixture['fixture_id']}-series",
        match_id=f"{fixture['fixture_id']}-match-{match_ordinal}",
        attempt_number=1,
        team_a_id=positions.team_a_id,
        team_b_id=positions.team_b_id,
        artifact_digest_a=artifacts[positions.team_a_id].artifact_digest,
        artifact_digest_b=artifacts[positions.team_b_id].artifact_digest,
        match_seed=match_seed,
        bot_visible_seed_a=bot_seeds[positions.team_a_id],
        bot_visible_seed_b=bot_seeds[positions.team_b_id],
        protocol_version=manifest["protocol_version"],
        scheduled_turns=manifest["scheduled_turns_per_match"],
        first_move_timeout_ms=limits["first_move_timeout_ms"],
        move_timeout_ms=limits["move_timeout_ms"],
        total_timeout_ms=limits["total_timeout_ms"],
        stderr_limit_bytes=limits["stderr_limit_bytes"],
    )


def _artifact_from_manifest(value: dict[str, Any]) -> BotArtifactManifest:
    return BotArtifactManifest(
        artifact_digest=value["artifact_digest"],
        language_id=value["language_id"],
        wrapper_version=value["wrapper_version"],
        runtime_digest=value["runtime_digest"],
        entrypoint=tuple(value["entrypoint"]),
    )


def _normalize_executor_result(
    execution_result: MatchExecutionResult,
    fixture: dict[str, Any],
) -> MatchResult:
    if not isinstance(execution_result, MatchExecutionResult):
        raise TypeError("Match executor must return a MatchExecutionResult")
    if execution_result.infrastructure_failure:
        raise RuntimeError("Infrastructure Failure did not produce a Match result")
    outcome = execution_result.competitive_outcome
    if not isinstance(outcome, dict):
        raise ValueError("Match executor returned no competitive outcome")

    team_one_id, team_two_id = fixture["team_ids"]
    score = outcome.get("score")
    faults = outcome.get("faults")
    if not isinstance(score, dict) or not isinstance(faults, dict):
        raise ValueError("Competitive outcome is missing score or fault facts")
    try:
        round_wins = (int(score[team_one_id]), int(score[team_two_id]))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Competitive score does not match Fixture Teams") from error

    outcome_kind = MatchOutcome(outcome.get("outcome"))
    if outcome_kind is MatchOutcome.DOUBLE_FORFEIT:
        return MatchResult.double_forfeit(team_one_id, team_two_id)
    if outcome_kind is MatchOutcome.DRAW:
        return MatchResult.draw(
            team_one_id, team_two_id, round_wins=round_wins
        )

    faulting_teams = [
        team_id
        for team_id in (team_one_id, team_two_id)
        if faults.get(team_id) is not None
    ]
    if len(faulting_teams) == 1:
        return MatchResult.protocol_forfeit(
            team_one_id,
            team_two_id,
            faulting_team_id=faulting_teams[0],
            completed_round_wins=round_wins,
        )
    if faulting_teams:
        raise ValueError("Two Team faults must be a Double Forfeit")
    winner_team_id = outcome.get("winner_team_id")
    if not isinstance(winner_team_id, str):
        raise ValueError("Winning Match outcome requires a Team winner")
    return MatchResult.win(
        team_one_id,
        team_two_id,
        winner_team_id,
        round_wins=round_wins,
    )


def _terminal_record(
    request: MatchExecutionRequest,
    fixture: dict[str, Any],
    match_ordinal: int,
    result: MatchResult,
) -> dict[str, Any]:
    team_one_id, team_two_id = fixture["team_ids"]
    return {
        "type": "match_terminal",
        "phase": "qualifying",
        "fixture_id": request.fixture_id,
        "match_id": request.match_id,
        "match_ordinal": match_ordinal,
        "team_ids": [team_one_id, team_two_id],
        "outcome": result.outcome.value,
        "winner_team_id": result.winner,
        "round_wins": result.round_wins,
        "protocol_forfeit_team_id": result.protocol_forfeit_team_id,
        "match_seed": str(request.match_seed),
        "bot_positions": {
            "a": request.team_a_id,
            "b": request.team_b_id,
        },
        "bot_visible_seeds": {
            request.team_a_id: str(request.bot_visible_seed_a),
            request.team_b_id: str(request.bot_visible_seed_b),
        },
        "artifact_digests": {
            request.team_a_id: request.artifact_digest_a,
            request.team_b_id: request.artifact_digest_b,
        },
    }


def _projection_from_records(
    manifest: dict[str, Any], records: list[StoredCompetitionRecord]
) -> dict[str, Any]:
    projection = _initial_projection(manifest)
    terminal_by_fixture: dict[str, list[dict[str, Any]]] = {}
    for stored in records:
        if stored.record.get("type") == "match_terminal":
            terminal_by_fixture.setdefault(
                stored.record["fixture_id"], []
            ).append(stored.record)

    for fixture_projection, fixture in zip(
        projection["fixtures"], _manifest_fixtures(manifest)
    ):
        fixture_records = sorted(
            terminal_by_fixture.get(fixture["fixture_id"], ()),
            key=lambda record: record["match_ordinal"],
        )
        if not fixture_records:
            continue
        series = _series_from_records(fixture, fixture_records)
        fixture_projection["status"] = (
            "complete" if series.is_complete else "in_progress"
        )
        fixture_projection["matches"] = [
            {
                "match_id": record["match_id"],
                "outcome": record["outcome"],
                "winner_team_id": record["winner_team_id"],
            }
            for record in fixture_records
        ]
    projection["standings"] = _standing_projection(
        manifest, terminal_by_fixture
    )
    return projection


def _standing_projection(
    manifest: dict[str, Any],
    terminal_by_fixture: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    counters = {
        team["team_id"]: {
            "standing_points": 0,
            "series_wins": 0,
            "match_wins": 0,
            "match_losses": 0,
            "round_wins": 0,
            "round_losses": 0,
            "protocol_fault_forfeits": 0,
        }
        for team in manifest["roster"]
    }
    complete_series: list[Series] = []
    for fixture in _manifest_fixtures(manifest):
        fixture_records = sorted(
            terminal_by_fixture.get(fixture["fixture_id"], ()),
            key=lambda record: record["match_ordinal"],
        )
        if not fixture_records:
            continue
        series = _series_from_records(fixture, fixture_records)
        for record in fixture_records:
            result = _match_result_from_record(record)
            for team_id, round_wins in result.round_wins.items():
                opponent = (
                    result.team_b_id
                    if team_id == result.team_a_id
                    else result.team_a_id
                )
                counters[team_id]["round_wins"] += round_wins
                counters[team_id]["round_losses"] += result.round_wins[opponent]
            if result.winner is not None:
                loser = (
                    result.team_b_id
                    if result.winner == result.team_a_id
                    else result.team_a_id
                )
                counters[result.winner]["match_wins"] += 1
                counters[loser]["match_losses"] += 1
            if result.protocol_forfeit_team_id is not None:
                counters[result.protocol_forfeit_team_id][
                    "protocol_fault_forfeits"
                ] += 1
        if series.is_complete:
            complete_series.append(series)
            for team_id, points in series.standing_points.items():
                counters[team_id]["standing_points"] += points
            if series.winner is not None:
                counters[series.winner]["series_wins"] += 1

    standings = rank_standings(
        (
            Standing(
                team_id=team_id,
                tie_break_key=int(manifest["tie_break_keys"][team_id]),
                **values,
            )
            for team_id, values in counters.items()
        ),
        complete_series,
    )
    return [
        {
            "team_id": standing.team_id,
            "standing_points": standing.standing_points,
            "series_wins": standing.series_wins,
            "match_differential": standing.match_differential,
            "round_differential": standing.round_differential,
            "protocol_fault_forfeits": standing.protocol_fault_forfeits,
            "tie_break_key": str(standing.tie_break_key),
        }
        for standing in standings
    ]
