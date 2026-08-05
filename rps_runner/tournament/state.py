"""Deterministic Tournament state reconstructed from canonical records.

The fold understands qualifying ``match_terminal`` records and the canonical
transition into the Playoff Phase. It is the semantic verification seam between
byte-valid storage and runner/projection behavior.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Optional

from .competition import (
    MatchOutcome,
    MatchResult,
    Phase,
    Series,
    Standing,
    calculate_qualifying_standings,
)
from .seeding import derive_fixture_seed
from .storage import StoredCompetitionRecord


class TournamentStateError(ValueError):
    """A stored record cannot belong to the canonical Tournament history."""


@dataclass(frozen=True)
class QualifyingMatch:
    """The scheduler-selected next canonical qualifying Match."""

    fixture_id: str
    match_ordinal: int
    team_ids: tuple[str, str]
    fixture_seed: int


@dataclass(frozen=True)
class PlayoffSeed:
    seed: int
    team_id: str


@dataclass(frozen=True)
class PlayoffFixtureDefinition:
    fixture_id: str
    stage: str
    team_ids: tuple[Optional[str], Optional[str]]
    fixture_seed: int


@dataclass(frozen=True)
class TournamentState:
    """Tournament state derived solely from a Manifest and its records."""

    qualifying_series: tuple[Series, ...]
    standings: tuple[Standing, ...]
    next_qualifying_match: Optional[QualifyingMatch]
    phase: Phase
    playoff_seeds: tuple[PlayoffSeed, ...]
    playoff_fixtures: tuple[PlayoffFixtureDefinition, ...]

    @property
    def qualification_complete(self) -> bool:
        return self.next_qualifying_match is None


@dataclass(frozen=True)
class _FixtureDefinition:
    fixture_id: str
    team_ids: tuple[str, str]
    fixture_seed: int


def fold_tournament_state(
    manifest: Mapping[str, Any],
    records: Iterable[StoredCompetitionRecord],
) -> TournamentState:
    """Fold verified stored bytes into semantically verified qualification state."""

    fixtures = _qualifying_fixtures(manifest)
    fixture_indexes = {
        fixture.fixture_id: index for index, fixture in enumerate(fixtures)
    }
    if len(fixture_indexes) != len(fixtures):
        raise TournamentStateError("Manifest contains a duplicate Fixture ID")

    series = [
        Series(
            fixture.team_ids[0],
            fixture.team_ids[1],
            Phase.QUALIFYING,
        )
        for fixture in fixtures
    ]
    current_fixture_index = 0
    playoff_bracket_created = False
    playoff_seeds: tuple[PlayoffSeed, ...] = ()
    playoff_fixtures: tuple[PlayoffFixtureDefinition, ...] = ()

    for expected_sequence, stored in enumerate(records, start=1):
        if not isinstance(stored, StoredCompetitionRecord):
            raise TournamentStateError("Tournament history contains an invalid record")
        if stored.sequence != expected_sequence:
            raise TournamentStateError(
                "Competition Record sequence is not contiguous"
            )
        record = stored.record
        record_type = record.get("type")
        if record_type == "playoff_bracket_created":
            if current_fixture_index != len(fixtures):
                raise TournamentStateError(
                    "Playoff bracket was created before qualification completed"
                )
            if playoff_bracket_created:
                raise TournamentStateError(
                    "Playoff bracket was created more than once"
                )
            standings = _calculate_standings(manifest, series)
            expected = build_playoff_bracket_record(manifest, standings)
            if record != expected:
                raise TournamentStateError(
                    "Playoff bracket does not match final qualifying standings"
                )
            playoff_bracket_created = True
            playoff_seeds, playoff_fixtures = _playoff_values(expected)
            continue
        if record_type != "match_terminal":
            raise TournamentStateError(
                "Unsupported Competition Record type in qualifying state"
            )
        if playoff_bracket_created:
            raise TournamentStateError(
                "A qualifying Match cannot follow the Playoff Phase transition"
            )
        fixture_id = record.get("fixture_id")
        if not isinstance(fixture_id, str) or fixture_id not in fixture_indexes:
            raise TournamentStateError("Competition Record names an unknown Fixture")
        record_fixture_index = fixture_indexes[fixture_id]

        if record_fixture_index < current_fixture_index:
            raise TournamentStateError(
                "Competition Record appears after a complete Series"
            )
        if record_fixture_index != current_fixture_index:
            raise TournamentStateError(
                "Competition Record violates canonical Fixture order"
            )

        fixture = fixtures[current_fixture_index]
        current_series = series[current_fixture_index]
        match_ordinal = record.get("match_ordinal")
        expected_match_ordinal = current_series.match_count + 1
        if (
            not isinstance(match_ordinal, int)
            or isinstance(match_ordinal, bool)
            or match_ordinal != expected_match_ordinal
        ):
            raise TournamentStateError(
                "Competition Record Match ordinal is duplicate, gapped, or out of order"
            )
        result = _match_result(record, fixture, match_ordinal)
        try:
            series[current_fixture_index] = current_series.record(result)
        except ValueError as error:
            raise TournamentStateError(str(error)) from error

        if series[current_fixture_index].is_complete:
            current_fixture_index += 1

    next_match: Optional[QualifyingMatch]
    if current_fixture_index == len(fixtures):
        next_match = None
    else:
        fixture = fixtures[current_fixture_index]
        next_match = QualifyingMatch(
            fixture_id=fixture.fixture_id,
            match_ordinal=series[current_fixture_index].match_count + 1,
            team_ids=fixture.team_ids,
            fixture_seed=fixture.fixture_seed,
        )

    standings = _calculate_standings(manifest, series)
    return TournamentState(
        tuple(series),
        standings,
        next_match,
        Phase.PLAYOFF if playoff_bracket_created else Phase.QUALIFYING,
        playoff_seeds,
        playoff_fixtures,
    )


def build_playoff_bracket_record(
    manifest: Mapping[str, Any], standings: tuple[Standing, ...]
) -> dict[str, Any]:
    """Create the canonical Playoff Phase transition from final standings."""

    if len(standings) < 4:
        raise TournamentStateError(
            "A standard playoff bracket requires four eligible Teams"
        )
    try:
        tournament_seed = int(manifest["tournament_seed"])
    except (KeyError, TypeError, ValueError) as error:
        raise TournamentStateError(
            "Manifest contains an invalid Tournament Seed"
        ) from error
    seeds = [
        {"seed": seed, "team_id": standing.team_id}
        for seed, standing in enumerate(standings[:4], start=1)
    ]
    pairings: tuple[tuple[str, tuple[Optional[str], Optional[str]]], ...] = (
        (
            "playoff-semifinal-1",
            (seeds[0]["team_id"], seeds[3]["team_id"]),
        ),
        (
            "playoff-semifinal-2",
            (seeds[1]["team_id"], seeds[2]["team_id"]),
        ),
        ("playoff-final", (None, None)),
    )
    return {
        "type": "playoff_bracket_created",
        "phase": Phase.PLAYOFF.value,
        "seeds": seeds,
        "fixtures": [
            {
                "fixture_id": fixture_id,
                "stage": (
                    "final" if fixture_id == "playoff-final" else "semifinal"
                ),
                "team_ids": list(team_ids),
                "fixture_seed": str(
                    derive_fixture_seed(tournament_seed, fixture_id)
                ),
            }
            for fixture_id, team_ids in pairings
        ],
    }


def _playoff_values(
    record: Mapping[str, Any],
) -> tuple[tuple[PlayoffSeed, ...], tuple[PlayoffFixtureDefinition, ...]]:
    seeds = tuple(
        PlayoffSeed(seed=value["seed"], team_id=value["team_id"])
        for value in record["seeds"]
    )
    fixtures = tuple(
        PlayoffFixtureDefinition(
            fixture_id=value["fixture_id"],
            stage=value["stage"],
            team_ids=(value["team_ids"][0], value["team_ids"][1]),
            fixture_seed=int(value["fixture_seed"]),
        )
        for value in record["fixtures"]
    )
    return seeds, fixtures


def _calculate_standings(
    manifest: Mapping[str, Any], series: Iterable[Series]
) -> tuple[Standing, ...]:
    team_ids = _team_ids(manifest)
    tie_break_keys = _tie_break_keys(manifest, team_ids)
    try:
        return calculate_qualifying_standings(team_ids, series, tie_break_keys)
    except (KeyError, TypeError, ValueError) as error:
        raise TournamentStateError(
            "Manifest and qualifying records cannot produce standings"
        ) from error


def _qualifying_fixtures(
    manifest: Mapping[str, Any],
) -> tuple[_FixtureDefinition, ...]:
    batches = manifest.get("qualifying_schedule")
    if not isinstance(batches, (list, tuple)):
        raise TournamentStateError("Manifest has no qualifying schedule")
    fixtures: list[_FixtureDefinition] = []
    for batch in batches:
        if not isinstance(batch, Mapping):
            raise TournamentStateError("Manifest contains an invalid Fixture Batch")
        batch_fixtures = batch.get("fixtures")
        if not isinstance(batch_fixtures, (list, tuple)):
            raise TournamentStateError("Manifest contains an invalid Fixture Batch")
        for value in batch_fixtures:
            if not isinstance(value, Mapping):
                raise TournamentStateError("Manifest contains an invalid Fixture")
            fixture_id = value.get("fixture_id")
            raw_team_ids = value.get("team_ids")
            raw_fixture_seed = value.get("fixture_seed")
            if (
                not isinstance(fixture_id, str)
                or not fixture_id
                or not isinstance(raw_team_ids, (list, tuple))
                or len(raw_team_ids) != 2
                or any(not isinstance(team_id, str) for team_id in raw_team_ids)
            ):
                raise TournamentStateError("Manifest contains an invalid Fixture")
            try:
                fixture_seed = int(raw_fixture_seed)
            except (TypeError, ValueError) as error:
                raise TournamentStateError(
                    "Manifest contains an invalid Fixture Seed"
                ) from error
            fixtures.append(
                _FixtureDefinition(
                    fixture_id,
                    (raw_team_ids[0], raw_team_ids[1]),
                    fixture_seed,
                )
            )
    return tuple(fixtures)


def _team_ids(manifest: Mapping[str, Any]) -> tuple[str, ...]:
    roster = manifest.get("roster")
    if not isinstance(roster, (list, tuple)):
        raise TournamentStateError("Manifest has no canonical roster")
    team_ids: list[str] = []
    for team in roster:
        if not isinstance(team, Mapping) or not isinstance(team.get("team_id"), str):
            raise TournamentStateError("Manifest contains an invalid Team")
        team_ids.append(team["team_id"])
    if len(team_ids) != len(set(team_ids)):
        raise TournamentStateError("Manifest contains a duplicate Team ID")
    return tuple(team_ids)


def _tie_break_keys(
    manifest: Mapping[str, Any], team_ids: tuple[str, ...]
) -> dict[str, int]:
    values = manifest.get("tie_break_keys")
    if not isinstance(values, Mapping) or set(values) != set(team_ids):
        raise TournamentStateError("Manifest Tie-break Keys do not match its roster")
    try:
        return {team_id: int(values[team_id]) for team_id in team_ids}
    except (TypeError, ValueError) as error:
        raise TournamentStateError("Manifest contains an invalid Tie-break Key") from error


def _match_result(
    record: Mapping[str, Any],
    fixture: _FixtureDefinition,
    match_ordinal: int,
) -> MatchResult:
    if record.get("phase") != Phase.QUALIFYING.value:
        raise TournamentStateError("Qualifying Match has an invalid phase")
    if record.get("match_id") != (
        f"{fixture.fixture_id}-match-{match_ordinal}"
    ):
        raise TournamentStateError("Qualifying Match has a non-canonical Match ID")
    raw_team_ids = record.get("team_ids")
    if not isinstance(raw_team_ids, (list, tuple)) or tuple(raw_team_ids) != fixture.team_ids:
        raise TournamentStateError("Qualifying Match Teams do not match its Fixture")
    round_wins = record.get("round_wins")
    if not isinstance(round_wins, Mapping):
        raise TournamentStateError("Qualifying Match has invalid Round wins")
    try:
        completed_round_wins = tuple(round_wins[team_id] for team_id in fixture.team_ids)
    except KeyError as error:
        raise TournamentStateError("Qualifying Match has invalid Round wins") from error
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in completed_round_wins
    ):
        raise TournamentStateError("Qualifying Match has invalid Round wins")

    try:
        outcome = MatchOutcome(record.get("outcome"))
        if outcome is MatchOutcome.DOUBLE_FORFEIT:
            return MatchResult.double_forfeit(
                *fixture.team_ids,
                completed_round_wins=completed_round_wins,
            )
        if outcome is MatchOutcome.DRAW:
            if record.get("winner_team_id") is not None:
                raise TournamentStateError("Drawn Match cannot name a winner")
            return MatchResult.draw(
                *fixture.team_ids,
                round_wins=completed_round_wins,
            )
        faulting_team_id = record.get("protocol_forfeit_team_id")
        if faulting_team_id is not None:
            return MatchResult.protocol_forfeit(
                *fixture.team_ids,
                faulting_team_id=faulting_team_id,
                completed_round_wins=completed_round_wins,
            )
        winner = record.get("winner_team_id")
        if not isinstance(winner, str):
            raise TournamentStateError("Winning Match must name its winner")
        return MatchResult.win(
            *fixture.team_ids,
            winner,
            round_wins=completed_round_wins,
        )
    except (TypeError, ValueError) as error:
        if isinstance(error, TournamentStateError):
            raise
        raise TournamentStateError("Qualifying Match outcome is invalid") from error
