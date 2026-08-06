"""Deterministic Tournament state reconstructed from canonical records.

The fold understands qualifying and standard Playoff Phase ``match_terminal``
records, phase transitions, Bracket Lock, and Tournament Champion declaration.
It is the semantic verification seam between byte-valid storage and
runner/projection behavior.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Optional

from .immutable import FrozenJsonDict, freeze_json
from .competition import (
    MatchOutcome,
    MatchResult,
    Phase,
    PlayoffStage,
    Series,
    Standing,
    calculate_qualifying_standings,
    create_playoff_bracket,
)
from .schedule import bot_positions
from .seeding import derive_bot_seed, derive_fixture_seed, derive_match_seed
from .storage import StoredCompetitionRecord


class TournamentStateError(ValueError):
    """A stored record cannot belong to the canonical Tournament history."""


_MATCH_TERMINAL_FIELDS = {
    "type",
    "phase",
    "fixture_id",
    "match_id",
    "match_ordinal",
    "team_ids",
    "outcome",
    "winner_team_id",
    "round_wins",
    "protocol_forfeit_team_id",
    "moves",
    "rounds",
    "faults",
    "match_seed",
    "bot_positions",
    "bot_visible_seeds",
    "artifact_digests",
}


@dataclass(frozen=True)
class QualifyingMatch:
    """The scheduler-selected next canonical qualifying Match."""

    fixture_id: str
    match_ordinal: int
    team_ids: tuple[str, str]
    fixture_seed: int


@dataclass(frozen=True)
class PlayoffMatch:
    """The scheduler-selected next canonical playoff Match."""

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
    stage: PlayoffStage
    team_ids: tuple[Optional[str], Optional[str]]
    fixture_seed: int


@dataclass(frozen=True)
class PendingSecurityRuling:
    """A suspected Security Violation awaiting an organizer ruling."""

    fixture_id: str
    match_id: str
    match_ordinal: int
    team_ids: tuple[str, str]
    suspected_team_id: str
    evidence_link: str


@dataclass(frozen=True)
class TournamentState:
    """Tournament state derived solely from a Manifest and its records."""

    qualifying_series: tuple[Series, ...]
    standings: tuple[Standing, ...]
    next_qualifying_match: Optional[QualifyingMatch]
    phase: Phase
    playoff_seeds: tuple[PlayoffSeed, ...]
    playoff_fixtures: tuple[PlayoffFixtureDefinition, ...]
    playoff_series: tuple[Series, ...]
    next_playoff_match: Optional[PlayoffMatch]
    bracket_locked: bool
    champion_team_id: Optional[str]
    ended_without_champion: bool
    disqualified_team_ids: tuple[str, ...] = ()
    pending_security_ruling: Optional[PendingSecurityRuling] = None
    pending_administrative_records: tuple[FrozenJsonDict, ...] = ()

    @property
    def qualifying_phase_complete(self) -> bool:
        return (
            all(series.is_complete for series in self.qualifying_series)
            and self.pending_security_ruling is None
            and not self.pending_administrative_records
        )

    @property
    def playoff_final_winner(self) -> Optional[str]:
        """Return the winner only when the canonical final Series is complete."""

        return _completed_final_winner(
            self.playoff_fixtures, list(self.playoff_series)
        )

    @property
    def is_complete(self) -> bool:
        return self.champion_team_id is not None or self.ended_without_champion


@dataclass(frozen=True)
class _FixtureDefinition:
    fixture_id: str
    team_ids: tuple[str, str]
    fixture_seed: int


def fold_tournament_state(
    manifest: Mapping[str, Any],
    records: Iterable[StoredCompetitionRecord],
) -> TournamentState:
    """Fold verified stored bytes into semantically verified Tournament state."""

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
    playoff_bracket_created = False
    playoff_seeds: tuple[PlayoffSeed, ...] = ()
    playoff_fixtures: tuple[PlayoffFixtureDefinition, ...] = ()
    playoff_series: list[Series] = []
    current_playoff_index = 0
    bracket_locked = False
    champion_team_id: Optional[str] = None
    ended_without_champion = False
    disqualified_team_ids: set[str] = set()
    pending_security_ruling: Optional[PendingSecurityRuling] = None
    pending_administrative_records: list[dict[str, Any]] = []

    for expected_sequence, stored in enumerate(records, start=1):
        if not isinstance(stored, StoredCompetitionRecord):
            raise TournamentStateError("Tournament history contains an invalid record")
        if stored.sequence != expected_sequence:
            raise TournamentStateError(
                "Competition Record sequence is not contiguous"
            )
        record = stored.record
        record_type = record.get("type")
        if (
            champion_team_id is not None
            and record_type == "tournament_champion_declared"
        ):
            raise TournamentStateError(
                "Tournament Champion was declared more than once"
            )
        if champion_team_id is not None or ended_without_champion:
            raise TournamentStateError(
                "A Competition Record cannot follow Tournament completion"
            )
        if pending_administrative_records:
            expected_administrative = pending_administrative_records[0]
            if record != expected_administrative:
                raise TournamentStateError(
                    "Confirmed Disqualification requires canonical Administrative "
                    "Series Wins in Fixture order"
                )
            fixture_id = expected_administrative["fixture_id"]
            fixture_index = fixture_indexes[fixture_id]
            series[fixture_index] = replace(
                series[fixture_index],
                administrative_winner_id=expected_administrative["winner_team_id"],
            )
            pending_administrative_records.pop(0)
            continue
        if record_type == "security_violation_suspected":
            if playoff_bracket_created:
                raise TournamentStateError(
                    "Playoff Security Violation integration is not supported"
                )
            if pending_security_ruling is not None:
                raise TournamentStateError(
                    "A Security Violation suspicion is already awaiting a ruling"
                )
            selected_index = _next_qualifying_fixture_index(
                series, disqualified_team_ids
            )
            if selected_index is None:
                raise TournamentStateError(
                    "A Security Violation suspicion cannot follow qualification"
                )
            fixture = fixtures[selected_index]
            match_ordinal = series[selected_index].match_count + 1
            pending_security_ruling = _pending_security_ruling(
                record, fixture, match_ordinal
            )
            continue
        if record_type == "security_violation_ruling":
            if pending_security_ruling is None:
                raise TournamentStateError(
                    "A Security Violation ruling has no pending suspicion"
                )
            decision = _validate_security_violation_ruling(
                record, pending_security_ruling
            )
            if decision == "confirmed":
                team_id = pending_security_ruling.suspected_team_id
                if team_id in disqualified_team_ids:
                    raise TournamentStateError(
                        "A Team cannot be disqualified more than once"
                    )
                disqualified_team_ids.add(team_id)
                pending_administrative_records = (
                    _administrative_records_for_disqualification(
                        fixtures,
                        team_id,
                        disqualified_team_ids,
                        pending_security_ruling.match_id,
                    )
                )
            pending_security_ruling = None
            continue
        if playoff_bracket_created:
            playoff_fixtures, playoff_series = _resolve_final_if_ready(
                playoff_fixtures, playoff_series, playoff_seeds
            )
        if record_type == "tournament_champion_declared":
            final_winner = _completed_final_winner(
                playoff_fixtures, playoff_series
            )
            if final_winner is not None:
                expected_champion = final_winner
                expected = build_tournament_champion_record(expected_champion)
            elif len(playoff_seeds) == 1 and not playoff_fixtures:
                expected_champion = playoff_seeds[0].team_id
                expected = build_sole_eligible_champion_record(
                    expected_champion
                )
            else:
                raise TournamentStateError(
                    "Tournament Champion was declared before the final completed"
                )
            if record != expected:
                raise TournamentStateError(
                    "Tournament Champion declaration is non-canonical"
                )
            champion_team_id = expected_champion
            continue
        if record_type == "tournament_ended_without_champion":
            if not playoff_bracket_created:
                raise TournamentStateError(
                    "Tournament ended without a champion before the playoff "
                    "field was recorded"
                )
            if playoff_seeds or playoff_fixtures or playoff_series:
                raise TournamentStateError(
                    "Tournament ended without a champion while eligible Teams remain"
                )
            if record != build_tournament_ended_without_champion_record():
                raise TournamentStateError(
                    "Tournament end without a champion is non-canonical"
                )
            ended_without_champion = True
            continue
        if record_type == "playoff_bracket_created":
            if (
                not all(item.is_complete for item in series)
                or pending_security_ruling is not None
                or pending_administrative_records
            ):
                raise TournamentStateError(
                    "Playoff bracket was created before the Qualifying Phase completed"
                )
            if playoff_bracket_created:
                raise TournamentStateError(
                    "Playoff bracket was created more than once"
                )
            standings = _calculate_standings(
                manifest,
                series,
                disqualified_team_ids=disqualified_team_ids,
            )
            expected = build_playoff_bracket_record(manifest, standings)
            if record != expected:
                raise TournamentStateError(
                    "Playoff bracket does not match final qualifying standings"
                )
            playoff_bracket_created = True
            playoff_seeds, playoff_fixtures = _playoff_values(expected)
            seed_by_team = {seed.team_id: seed.seed for seed in playoff_seeds}
            playoff_series = [
                Series(
                    fixture.team_ids[0],
                    fixture.team_ids[1],
                    Phase.PLAYOFF,
                    higher_seed_team_id=min(
                        (fixture.team_ids[0], fixture.team_ids[1]),
                        key=seed_by_team.__getitem__,
                    ),
                )
                for fixture in playoff_fixtures
                if fixture.team_ids[0] is not None
                and fixture.team_ids[1] is not None
            ]
            continue
        if record_type == "playoff_bracket_locked":
            if not playoff_bracket_created:
                raise TournamentStateError(
                    "Playoff bracket was locked before it was created"
                )
            if bracket_locked:
                raise TournamentStateError(
                    "Playoff bracket was locked more than once"
                )
            first_fixture = next(
                (
                    fixture
                    for fixture in playoff_fixtures
                    if fixture.team_ids[0] is not None
                    and fixture.team_ids[1] is not None
                ),
                None,
            )
            if first_fixture is None:
                raise TournamentStateError(
                    "Playoff Bracket Lock requires an actual playoff Match"
                )
            expected_lock = {
                "type": "playoff_bracket_locked",
                "phase": Phase.PLAYOFF.value,
                "fixture_id": first_fixture.fixture_id,
                "match_id": f"{first_fixture.fixture_id}-match-1",
            }
            if record != expected_lock:
                raise TournamentStateError("Playoff Bracket Lock is non-canonical")
            bracket_locked = True
            continue
        if record_type != "match_terminal":
            raise TournamentStateError(
                "Unsupported Competition Record type in qualifying state"
            )
        if playoff_bracket_created:
            if champion_team_id is not None:
                raise TournamentStateError(
                    "A playoff Match cannot follow Tournament completion"
                )
            if not bracket_locked:
                raise TournamentStateError(
                    "A playoff Match cannot precede Bracket Lock"
                )
            if current_playoff_index >= len(playoff_series):
                raise TournamentStateError("A playoff Match cannot follow the final")
            fixture_value = playoff_fixtures[current_playoff_index]
            assert fixture_value.team_ids[0] is not None
            assert fixture_value.team_ids[1] is not None
            fixture = _FixtureDefinition(
                fixture_value.fixture_id,
                (fixture_value.team_ids[0], fixture_value.team_ids[1]),
                fixture_value.fixture_seed,
            )
            current_series = playoff_series[current_playoff_index]
            match_ordinal = record.get("match_ordinal")
            expected_match_ordinal = current_series.match_count + 1
            if (
                not isinstance(match_ordinal, int)
                or isinstance(match_ordinal, bool)
                or match_ordinal != expected_match_ordinal
            ):
                raise TournamentStateError(
                    "Playoff Competition Record Match ordinal is duplicate, "
                    "gapped, or out of order"
                )
            _validate_match_identity(manifest, record, fixture, match_ordinal)
            _validate_competitive_details(manifest, record, fixture)
            result = _match_result(
                record, fixture, match_ordinal, phase=Phase.PLAYOFF
            )
            try:
                playoff_series[current_playoff_index] = current_series.record(result)
            except ValueError as error:
                raise TournamentStateError(str(error)) from error
            if playoff_series[current_playoff_index].is_complete:
                current_playoff_index += 1
            continue
        if pending_security_ruling is not None:
            raise TournamentStateError(
                "A Match cannot be committed while a Security Violation awaits ruling"
            )
        fixture_id = record.get("fixture_id")
        if not isinstance(fixture_id, str) or fixture_id not in fixture_indexes:
            raise TournamentStateError("Competition Record names an unknown Fixture")
        record_fixture_index = fixture_indexes[fixture_id]
        if series[record_fixture_index].is_complete:
            raise TournamentStateError(
                "Competition Record appears after a complete Series"
            )
        selected_index = _next_qualifying_fixture_index(
            series, disqualified_team_ids
        )
        if selected_index is None:
            raise TournamentStateError(
                "Competition Record appears after a complete Series"
            )
        if record_fixture_index != selected_index:
            raise TournamentStateError(
                "Competition Record violates canonical Fixture order"
            )

        fixture = fixtures[selected_index]
        current_series = series[selected_index]
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
        _validate_match_identity(manifest, record, fixture, match_ordinal)
        _validate_competitive_details(manifest, record, fixture)
        result = _match_result(record, fixture, match_ordinal)
        try:
            series[selected_index] = current_series.record(result)
        except ValueError as error:
            raise TournamentStateError(str(error)) from error

    next_match: Optional[QualifyingMatch]
    selected_index = _next_qualifying_fixture_index(series, disqualified_team_ids)
    if (
        selected_index is None
        or pending_security_ruling is not None
        or pending_administrative_records
    ):
        next_match = None
    else:
        fixture = fixtures[selected_index]
        next_match = QualifyingMatch(
            fixture_id=fixture.fixture_id,
            match_ordinal=series[selected_index].match_count + 1,
            team_ids=fixture.team_ids,
            fixture_seed=fixture.fixture_seed,
        )

    standings = _calculate_standings(
        manifest, series, disqualified_team_ids=disqualified_team_ids
    )
    playoff_fixtures, playoff_series = _resolve_final_if_ready(
        playoff_fixtures, playoff_series, playoff_seeds
    )
    next_playoff_match: Optional[PlayoffMatch] = None
    if playoff_bracket_created and current_playoff_index < len(playoff_series):
        fixture = playoff_fixtures[current_playoff_index]
        assert fixture.team_ids[0] is not None
        assert fixture.team_ids[1] is not None
        next_playoff_match = PlayoffMatch(
            fixture.fixture_id,
            playoff_series[current_playoff_index].match_count + 1,
            (fixture.team_ids[0], fixture.team_ids[1]),
            fixture.fixture_seed,
        )
    return TournamentState(
        tuple(series),
        standings,
        next_match,
        Phase.PLAYOFF if playoff_bracket_created else Phase.QUALIFYING,
        playoff_seeds,
        playoff_fixtures,
        tuple(playoff_series),
        next_playoff_match,
        bracket_locked,
        champion_team_id,
        ended_without_champion,
        tuple(sorted(disqualified_team_ids)),
        pending_security_ruling,
        tuple(_frozen_record(record) for record in pending_administrative_records),
    )


def build_tournament_champion_record(team_id: str) -> dict[str, Any]:
    """Create the sole canonical Tournament Champion declaration."""

    return {
        "type": "tournament_champion_declared",
        "phase": Phase.PLAYOFF.value,
        "fixture_id": "playoff-final",
        "team_id": team_id,
    }


def build_sole_eligible_champion_record(team_id: str) -> dict[str, Any]:
    """Declare a sole eligible Team champion without inventing a Fixture."""

    return {
        "type": "tournament_champion_declared",
        "phase": Phase.PLAYOFF.value,
        "fixture_id": None,
        "team_id": team_id,
        "reason_code": "sole_eligible_team",
    }


def build_tournament_ended_without_champion_record() -> dict[str, Any]:
    """End under the zero-eligible-Team rule, distinct from operator abort."""

    return {
        "type": "tournament_ended_without_champion",
        "phase": Phase.PLAYOFF.value,
        "reason_code": "no_eligible_teams",
    }


def _resolve_final_if_ready(
    fixtures: tuple[PlayoffFixtureDefinition, ...],
    series: list[Series],
    seeds: tuple[PlayoffSeed, ...],
) -> tuple[tuple[PlayoffFixtureDefinition, ...], list[Series]]:
    semifinals = tuple(
        fixture
        for fixture in fixtures
        if fixture.stage is PlayoffStage.SEMIFINAL
    )
    final = next(
        (
            fixture
            for fixture in fixtures
            if fixture.stage is PlayoffStage.FINAL
        ),
        None,
    )
    if (
        final is None
        or len(series) > len(semifinals)
        or len(series) != len(semifinals)
        or not all(item.is_complete for item in series)
    ):
        return fixtures, series
    winners = iter(item.winner for item in series)
    finalists = tuple(
        team_id if team_id is not None else next(winners)
        for team_id in final.team_ids
    )
    if finalists[0] is None or finalists[1] is None:
        return fixtures, series
    seed_by_team = {seed.team_id: seed.seed for seed in seeds}
    resolved_fixture = replace(final, team_ids=finalists)
    final_series = Series(
        finalists[0],
        finalists[1],
        Phase.PLAYOFF,
        higher_seed_team_id=min(finalists, key=seed_by_team.__getitem__),
    )
    final_index = fixtures.index(final)
    return (
        fixtures[:final_index] + (resolved_fixture,) + fixtures[final_index + 1 :],
        series + [final_series],
    )


def _completed_final_winner(
    fixtures: tuple[PlayoffFixtureDefinition, ...],
    series: list[Series],
) -> Optional[str]:
    if not fixtures or fixtures[-1].stage is not PlayoffStage.FINAL or not series:
        return None
    final_fixture = fixtures[-1]
    final_series = series[-1]
    if (
        None in final_fixture.team_ids
        or {final_series.team_one_id, final_series.team_two_id}
        != set(final_fixture.team_ids)
        or not final_series.is_complete
    ):
        return None
    return final_series.winner


def build_playoff_bracket_record(
    manifest: Mapping[str, Any], standings: tuple[Standing, ...]
) -> dict[str, Any]:
    """Create the canonical Playoff Phase transition from final standings."""

    try:
        tournament_seed = int(manifest["tournament_seed"])
    except (KeyError, TypeError, ValueError) as error:
        raise TournamentStateError(
            "Manifest contains an invalid Tournament Seed"
        ) from error
    bracket = create_playoff_bracket(standings)
    seeds = [
        {"seed": seeded.seed, "team_id": seeded.team_id}
        for seeded in bracket.seeds
    ]
    pairings = tuple(
        (
            f"playoff-semifinal-{index}",
            (fixture.team_one_id, fixture.team_two_id),
        )
        for index, fixture in enumerate(bracket.semifinals, start=1)
    )
    if bracket.final is not None:
        pairings += (
            (
                "playoff-final",
                (bracket.final.team_one_id, bracket.final.team_two_id),
            ),
        )
    return {
        "type": "playoff_bracket_created",
        "phase": Phase.PLAYOFF.value,
        "seeds": seeds,
        "fixtures": [
            {
                "fixture_id": fixture_id,
                "stage": (
                    PlayoffStage.FINAL.value
                    if fixture_id == "playoff-final"
                    else PlayoffStage.SEMIFINAL.value
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
            stage=PlayoffStage(value["stage"]),
            team_ids=(value["team_ids"][0], value["team_ids"][1]),
            fixture_seed=int(value["fixture_seed"]),
        )
        for value in record["fixtures"]
    )
    return seeds, fixtures


def build_security_violation_suspected_record(
    *,
    fixture_id: str,
    match_id: str,
    match_ordinal: int,
    team_ids: tuple[str, str],
    suspected_team_id: str,
    evidence_link: str,
) -> dict[str, Any]:
    """Build the minimum canonical fact needed to recover a pending ruling."""

    if suspected_team_id not in team_ids:
        raise ValueError("Suspected Team must compete in the canonical Match")
    if not isinstance(evidence_link, str) or not evidence_link:
        raise ValueError("A suspected Security Violation requires an evidence link")
    return {
        "type": "security_violation_suspected",
        "phase": Phase.QUALIFYING.value,
        "fixture_id": fixture_id,
        "match_id": match_id,
        "match_ordinal": match_ordinal,
        "team_ids": list(team_ids),
        "suspected_team_id": suspected_team_id,
        "evidence_link": evidence_link,
    }


def build_security_violation_ruling_record(
    pending: PendingSecurityRuling,
    *,
    decision: str,
    organizer_id: str,
    reason_code: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Build an attributable organizer ruling with a closed reason code."""

    allowed_reason = {
        "confirmed": "confirmed_prohibited_behavior",
        "rejected": "attribution_not_confirmed",
    }
    if decision not in allowed_reason:
        raise ValueError("Security Violation decision must be confirmed or rejected")
    if reason_code != allowed_reason[decision]:
        raise ValueError("Reason code is not valid for this Security Violation ruling")
    if not isinstance(organizer_id, str) or not organizer_id.strip():
        raise ValueError("Organizer identity is required")
    if note is not None and not isinstance(note, str):
        raise TypeError("Ruling note must be a string or None")
    return {
        "type": "security_violation_ruling",
        "phase": Phase.QUALIFYING.value,
        "fixture_id": pending.fixture_id,
        "match_id": pending.match_id,
        "suspected_team_id": pending.suspected_team_id,
        "decision": decision,
        "organizer_id": organizer_id,
        "reason_code": reason_code,
        "note": note,
    }


def _next_qualifying_fixture_index(
    series: list[Series], disqualified_team_ids: set[str]
) -> Optional[int]:
    for index, item in enumerate(series):
        if item.is_complete:
            continue
        if {item.team_one_id, item.team_two_id} & disqualified_team_ids:
            continue
        return index
    return None


def _frozen_record(record: dict[str, Any]) -> FrozenJsonDict:
    frozen = freeze_json(record)
    assert isinstance(frozen, FrozenJsonDict)
    return frozen


def _pending_security_ruling(
    record: Mapping[str, Any],
    fixture: _FixtureDefinition,
    match_ordinal: int,
) -> PendingSecurityRuling:
    expected_fields = {
        "type",
        "phase",
        "fixture_id",
        "match_id",
        "match_ordinal",
        "team_ids",
        "suspected_team_id",
        "evidence_link",
    }
    suspected_team_id = record.get("suspected_team_id")
    evidence_link = record.get("evidence_link")
    expected_match_id = f"{fixture.fixture_id}-match-{match_ordinal}"
    if (
        set(record) != expected_fields
        or record.get("phase") != Phase.QUALIFYING.value
        or record.get("fixture_id") != fixture.fixture_id
        or record.get("match_id") != expected_match_id
        or record.get("match_ordinal") != match_ordinal
        or record.get("team_ids") != list(fixture.team_ids)
        or suspected_team_id not in fixture.team_ids
        or not isinstance(evidence_link, str)
        or not evidence_link
    ):
        raise TournamentStateError(
            "Security Violation suspicion does not identify the next canonical Match"
        )
    return PendingSecurityRuling(
        fixture.fixture_id,
        expected_match_id,
        match_ordinal,
        fixture.team_ids,
        suspected_team_id,
        evidence_link,
    )


def _validate_security_violation_ruling(
    record: Mapping[str, Any], pending: PendingSecurityRuling
) -> str:
    decision = record.get("decision")
    reason_code = record.get("reason_code")
    organizer_id = record.get("organizer_id")
    note = record.get("note")
    if decision not in {"confirmed", "rejected"}:
        raise TournamentStateError("Security Violation ruling has an invalid decision")
    try:
        expected = build_security_violation_ruling_record(
            pending,
            decision=decision,
            organizer_id=organizer_id,
            reason_code=reason_code,
            note=note,
        )
    except (TypeError, ValueError) as error:
        raise TournamentStateError(str(error)) from error
    if record != expected:
        raise TournamentStateError(
            "Security Violation ruling does not resolve the pending suspicion"
        )
    return decision


def _administrative_records_for_disqualification(
    fixtures: tuple[_FixtureDefinition, ...],
    disqualified_team_id: str,
    disqualified_team_ids: set[str],
    ruling_match_id: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for fixture in fixtures:
        if disqualified_team_id not in fixture.team_ids:
            continue
        winner = next(
            team_id
            for team_id in fixture.team_ids
            if team_id != disqualified_team_id
        )
        if winner in disqualified_team_ids:
            continue
        records.append(
            {
                "type": "administrative_series_win",
                "phase": Phase.QUALIFYING.value,
                "fixture_id": fixture.fixture_id,
                "team_ids": list(fixture.team_ids),
                "winner_team_id": winner,
                "disqualified_team_id": disqualified_team_id,
                "reason_code": "opponent_disqualified",
                "ruling_match_id": ruling_match_id,
            }
        )
    return records


def _calculate_standings(
    manifest: Mapping[str, Any],
    series: Iterable[Series],
    *,
    disqualified_team_ids: Iterable[str] = (),
) -> tuple[Standing, ...]:
    team_ids = _team_ids(manifest)
    tie_break_keys = _tie_break_keys(manifest, team_ids)
    try:
        return calculate_qualifying_standings(
            team_ids,
            series,
            tie_break_keys,
            disqualified_team_ids=disqualified_team_ids,
        )
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
    *,
    phase: Phase = Phase.QUALIFYING,
) -> MatchResult:
    if record.get("phase") != phase.value:
        raise TournamentStateError("Match has an invalid phase")
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
            if (
                record.get("winner_team_id") is not None
                or record.get("protocol_forfeit_team_id") is not None
            ):
                raise TournamentStateError(
                    "Qualifying Match has contradictory outcome fields"
                )
            return MatchResult.double_forfeit(
                *fixture.team_ids,
                completed_round_wins=completed_round_wins,
            )
        if outcome is MatchOutcome.DRAW:
            if (
                record.get("winner_team_id") is not None
                or record.get("protocol_forfeit_team_id") is not None
            ):
                raise TournamentStateError(
                    "Qualifying Match has contradictory outcome fields"
                )
            return MatchResult.draw(
                *fixture.team_ids,
                round_wins=completed_round_wins,
            )
        faulting_team_id = record.get("protocol_forfeit_team_id")
        if faulting_team_id is not None:
            expected_winner = next(
                (
                    team_id
                    for team_id in fixture.team_ids
                    if team_id != faulting_team_id
                ),
                None,
            )
            if record.get("winner_team_id") != expected_winner:
                raise TournamentStateError(
                    "Qualifying Match has contradictory outcome fields"
                )
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


def _validate_match_identity(
    manifest: Mapping[str, Any],
    record: Mapping[str, Any],
    fixture: _FixtureDefinition,
    match_ordinal: int,
) -> None:
    match_seed = derive_match_seed(fixture.fixture_seed, match_ordinal)
    if record.get("match_seed") != str(match_seed):
        raise TournamentStateError("Qualifying Match has a non-canonical Match Seed")

    positions = bot_positions(
        fixture.fixture_seed,
        match_ordinal,
        fixture.team_ids[0],
        fixture.team_ids[1],
    )
    expected_positions = {
        "a": positions.team_a_id,
        "b": positions.team_b_id,
    }
    if record.get("bot_positions") != expected_positions:
        raise TournamentStateError("Qualifying Match has non-canonical Bot Positions")

    expected_bot_seeds = {
        team_id: str(derive_bot_seed(match_seed, team_id))
        for team_id in fixture.team_ids
    }
    if record.get("bot_visible_seeds") != expected_bot_seeds:
        raise TournamentStateError(
            "Qualifying Match has non-canonical bot-visible Seeds"
        )

    artifacts = _artifact_digests(manifest)
    expected_artifacts = {
        team_id: artifacts[team_id] for team_id in fixture.team_ids
    }
    if record.get("artifact_digests") != expected_artifacts:
        raise TournamentStateError(
            "Qualifying Match has non-canonical Bot Artifact digests"
        )


def _artifact_digests(manifest: Mapping[str, Any]) -> dict[str, str]:
    roster = manifest.get("roster")
    if not isinstance(roster, (list, tuple)):
        raise TournamentStateError("Manifest has no canonical roster")
    artifacts: dict[str, str] = {}
    for team in roster:
        if not isinstance(team, Mapping):
            raise TournamentStateError("Manifest contains an invalid Team")
        team_id = team.get("team_id")
        bot_artifact = team.get("bot_artifact")
        if (
            not isinstance(team_id, str)
            or not isinstance(bot_artifact, Mapping)
            or not isinstance(bot_artifact.get("artifact_digest"), str)
        ):
            raise TournamentStateError("Manifest contains an invalid Bot Artifact")
        artifacts[team_id] = bot_artifact["artifact_digest"]
    return artifacts


def _validate_competitive_details(
    manifest: Mapping[str, Any],
    record: Mapping[str, Any],
    fixture: _FixtureDefinition,
) -> None:
    if set(record) != _MATCH_TERMINAL_FIELDS:
        raise TournamentStateError(
            "Qualifying Match has non-canonical Competition Record fields"
        )
    team_ids = set(fixture.team_ids)
    moves = record.get("moves")
    if (
        not isinstance(moves, Mapping)
        or set(moves) != team_ids
        or any(
            not isinstance(value, str)
            or any(move not in "RPS" for move in value)
            for value in moves.values()
        )
    ):
        raise TournamentStateError("Qualifying Match has invalid completed moves")

    rounds = record.get("rounds")
    if not isinstance(rounds, (list, tuple)):
        raise TournamentStateError("Qualifying Match has invalid completed Rounds")
    if any(len(moves[team_id]) != len(rounds) for team_id in team_ids):
        raise TournamentStateError("Qualifying Match has invalid completed moves")
    calculated_round_wins = {team_id: 0 for team_id in fixture.team_ids}
    for expected_turn, round_record in enumerate(rounds):
        if not isinstance(round_record, Mapping):
            raise TournamentStateError("Qualifying Match has invalid completed Rounds")
        round_moves = round_record.get("moves")
        if (
            set(round_record) != {"turn", "moves", "winner_team_id"}
            or not isinstance(round_record.get("turn"), int)
            or isinstance(round_record.get("turn"), bool)
            or round_record.get("turn") != expected_turn
            or not isinstance(round_moves, Mapping)
            or set(round_moves) != team_ids
            or any(
                round_moves.get(team_id) not in {"R", "P", "S"}
                for team_id in team_ids
            )
            or any(
                expected_turn >= len(moves[team_id])
                or moves[team_id][expected_turn] != round_moves[team_id]
                for team_id in team_ids
            )
            or round_record.get("winner_team_id")
            != _round_winner(fixture.team_ids, round_moves)
        ):
            raise TournamentStateError("Qualifying Match has invalid completed Rounds")
        winner_team_id = round_record.get("winner_team_id")
        if winner_team_id is not None:
            calculated_round_wins[winner_team_id] += 1

    if record.get("round_wins") != calculated_round_wins:
        raise TournamentStateError("Qualifying Match has invalid Round wins")

    faults = record.get("faults")
    if not isinstance(faults, Mapping) or set(faults) != team_ids:
        raise TournamentStateError("Qualifying Match has invalid normalized faults")
    normalized_faults: dict[str, Optional[Mapping[str, Any]]] = {}
    for team_id in fixture.team_ids:
        fault = faults[team_id]
        if fault is None:
            normalized_faults[team_id] = None
            continue
        if (
            not isinstance(fault, Mapping)
            or set(fault) != {"kind", "turn"}
            or not isinstance(fault.get("kind"), str)
            or not fault.get("kind")
            or not isinstance(fault.get("turn"), int)
            or isinstance(fault.get("turn"), bool)
            or fault["turn"] < 0
        ):
            raise TournamentStateError("Qualifying Match has invalid normalized faults")
        normalized_faults[team_id] = fault

    outcome = record.get("outcome")
    faulting_team_id = record.get("protocol_forfeit_team_id")
    present_faults = [
        team_id for team_id, fault in normalized_faults.items() if fault is not None
    ]
    if outcome == MatchOutcome.DOUBLE_FORFEIT.value:
        fault_turns = {
            fault["turn"]
            for fault in normalized_faults.values()
            if fault is not None
        }
        valid_faults = len(present_faults) == 2 and len(fault_turns) == 1
    elif faulting_team_id is not None:
        valid_faults = present_faults == [faulting_team_id]
    else:
        valid_faults = not present_faults
    if not valid_faults:
        raise TournamentStateError(
            "Qualifying Match has contradictory normalized faults"
        )
    if present_faults and any(
        normalized_faults[team_id]["turn"] != len(rounds)
        for team_id in present_faults
    ):
        raise TournamentStateError(
            "Qualifying Match has contradictory normalized faults"
        )

    scheduled_turns = manifest.get("scheduled_turns_per_match")
    if (
        not isinstance(scheduled_turns, int)
        or isinstance(scheduled_turns, bool)
        or scheduled_turns <= 0
    ):
        raise TournamentStateError(
            "Manifest contains invalid scheduled Turns per Match"
        )
    if (
        (not present_faults and len(rounds) != scheduled_turns)
        or (present_faults and len(rounds) >= scheduled_turns)
    ):
        raise TournamentStateError(
            "Qualifying Match has an invalid number of completed Rounds"
        )

    winner_team_id = record.get("winner_team_id")
    if (
        outcome == MatchOutcome.DRAW.value
        and len(set(calculated_round_wins.values())) != 1
    ):
        raise TournamentStateError(
            "Qualifying Match has contradictory outcome fields"
        )
    if (
        outcome == MatchOutcome.WIN.value
        and faulting_team_id is None
        and winner_team_id in team_ids
        and calculated_round_wins[winner_team_id]
        <= calculated_round_wins[
            next(team_id for team_id in fixture.team_ids if team_id != winner_team_id)
        ]
    ):
        raise TournamentStateError(
            "Qualifying Match has contradictory outcome fields"
        )


def _round_winner(
    team_ids: tuple[str, str], moves: Mapping[str, Any]
) -> Optional[str]:
    team_one_move = moves[team_ids[0]]
    team_two_move = moves[team_ids[1]]
    if team_one_move == team_two_move:
        return None
    if (team_one_move, team_two_move) in {("R", "S"), ("S", "P"), ("P", "R")}:
        return team_ids[0]
    return team_ids[1]
