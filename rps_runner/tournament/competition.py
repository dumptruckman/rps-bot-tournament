"""Pure competition rules for Series, standings, and playoffs.

This module deliberately has no runner or persistence dependencies.  Its
immutable values form the boundary between normalized Match results and the
Tournament state machine.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from fractions import Fraction
from typing import Optional


class Phase(str, Enum):
    QUALIFYING = "qualifying"
    PLAYOFF = "playoff"


class MatchOutcome(str, Enum):
    WIN = "win"
    DRAW = "draw"
    DOUBLE_FORFEIT = "double_forfeit"


@dataclass(frozen=True)
class MatchResult:
    team_one_id: str
    team_two_id: str
    outcome: MatchOutcome
    winner: Optional[str] = None
    team_one_round_wins: int = 0
    team_two_round_wins: int = 0
    protocol_forfeit_team_id: Optional[str] = None

    @classmethod
    def win(
        cls,
        team_one_id: str,
        team_two_id: str,
        winner: str,
        *,
        round_wins: tuple[int, int] = (0, 0),
    ) -> "MatchResult":
        if winner not in (team_one_id, team_two_id):
            raise ValueError("Match winner must compete in the Match")
        return cls(
            team_one_id,
            team_two_id,
            MatchOutcome.WIN,
            winner,
            round_wins[0],
            round_wins[1],
        )

    @classmethod
    def draw(
        cls,
        team_one_id: str,
        team_two_id: str,
        *,
        round_wins: tuple[int, int] = (0, 0),
    ) -> "MatchResult":
        return cls(
            team_one_id,
            team_two_id,
            MatchOutcome.DRAW,
            team_one_round_wins=round_wins[0],
            team_two_round_wins=round_wins[1],
        )

    @classmethod
    def double_forfeit(
        cls,
        team_one_id: str,
        team_two_id: str,
        *,
        completed_round_wins: tuple[int, int] = (0, 0),
    ) -> "MatchResult":
        return cls(
            team_one_id,
            team_two_id,
            MatchOutcome.DOUBLE_FORFEIT,
            team_one_round_wins=completed_round_wins[0],
            team_two_round_wins=completed_round_wins[1],
        )

    @classmethod
    def protocol_forfeit(
        cls,
        team_one_id: str,
        team_two_id: str,
        *,
        faulting_team_id: str,
        completed_round_wins: tuple[int, int] = (0, 0),
    ) -> "MatchResult":
        if faulting_team_id not in (team_one_id, team_two_id):
            raise ValueError("Faulting Team must compete in the Match")
        winner = team_two_id if faulting_team_id == team_one_id else team_one_id
        return cls(
            team_one_id,
            team_two_id,
            MatchOutcome.WIN,
            winner,
            completed_round_wins[0],
            completed_round_wins[1],
            faulting_team_id,
        )

    @property
    def round_wins(self) -> dict[str, int]:
        return {
            self.team_one_id: self.team_one_round_wins,
            self.team_two_id: self.team_two_round_wins,
        }


@dataclass(frozen=True)
class Series:
    team_one_id: str
    team_two_id: str
    phase: Phase
    higher_seed_team_id: Optional[str] = None
    matches: tuple[MatchResult, ...] = ()
    administrative_winner_id: Optional[str] = None

    @classmethod
    def administrative_win(
        cls,
        team_one_id: str,
        team_two_id: str,
        phase: Phase,
        *,
        winner: str,
        higher_seed_team_id: Optional[str] = None,
    ) -> "Series":
        if winner not in (team_one_id, team_two_id):
            raise ValueError("Administrative winner must compete in the Series")
        return cls(
            team_one_id,
            team_two_id,
            phase,
            higher_seed_team_id=higher_seed_team_id,
            administrative_winner_id=winner,
        )

    def record(self, result: MatchResult) -> "Series":
        if self.is_complete:
            raise ValueError("Series is already complete")
        if (result.team_one_id, result.team_two_id) != (
            self.team_one_id,
            self.team_two_id,
        ):
            raise ValueError("Match Teams must match Series Teams")
        return replace(self, matches=self.matches + (result,))

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def series_points(self) -> dict[str, Fraction]:
        points = {self.team_one_id: Fraction(0), self.team_two_id: Fraction(0)}
        for match in self.matches:
            if match.outcome is MatchOutcome.DRAW:
                points[self.team_one_id] += Fraction(1, 2)
                points[self.team_two_id] += Fraction(1, 2)
            elif match.outcome is MatchOutcome.WIN:
                assert match.winner is not None
                points[match.winner] += Fraction(1)
        return points

    @property
    def is_complete(self) -> bool:
        if self.administrative_winner_id is not None:
            return True
        if len(self.matches) == 3:
            return True
        if len(self.matches) < 2:
            return False
        winner = self.matches[0].winner
        return winner is not None and all(
            match.winner == winner for match in self.matches
        )

    @property
    def winner(self) -> Optional[str]:
        if not self.is_complete:
            return None
        if self.administrative_winner_id is not None:
            return self.administrative_winner_id
        points = self.series_points
        if points[self.team_one_id] == points[self.team_two_id]:
            if self.phase is Phase.PLAYOFF:
                if self.higher_seed_team_id not in (
                    self.team_one_id,
                    self.team_two_id,
                ):
                    raise ValueError(
                        "A playoff Series requires its higher-seeded Team"
                    )
                return self.higher_seed_team_id
            return None
        return max(points, key=points.__getitem__)

    @property
    def standing_points(self) -> dict[str, int]:
        if not self.is_complete:
            raise ValueError("Standing Points require a complete Series")
        winner = self.winner
        if winner is None:
            return {self.team_one_id: 1, self.team_two_id: 1}
        loser = (
            self.team_two_id if winner == self.team_one_id else self.team_one_id
        )
        return {winner: 3, loser: 0}


@dataclass(frozen=True)
class Standing:
    team_id: str
    standing_points: int
    series_wins: int
    match_wins: int
    match_losses: int
    round_wins: int
    round_losses: int
    protocol_fault_forfeits: int
    tie_break_key: int

    @property
    def match_differential(self) -> int:
        return self.match_wins - self.match_losses

    @property
    def round_differential(self) -> int:
        return self.round_wins - self.round_losses


def calculate_qualifying_standings(
    team_ids: Sequence[str],
    series_results: Iterable[Series],
    tie_break_keys: Mapping[str, int],
    *,
    disqualified_team_ids: Iterable[str] = (),
) -> tuple[Standing, ...]:
    """Calculate and rank eligible Teams from qualifying Series facts.

    Played facts remain in ``series_results``.  When a Team is disqualified,
    its Fixtures are instead represented competitively by one Administrative
    Series Win per eligible opponent, so played lower-level statistics are not
    folded into standings.
    """

    disqualified = frozenset(disqualified_team_ids)
    eligible = [team_id for team_id in team_ids if team_id not in disqualified]
    counters = {
        team_id: {
            "standing_points": 3 * len(disqualified),
            "series_wins": len(disqualified),
            "match_wins": 0,
            "match_losses": 0,
            "round_wins": 0,
            "round_losses": 0,
            "protocol_fault_forfeits": 0,
        }
        for team_id in eligible
    }

    head_to_head: list[Series] = []
    for series in series_results:
        if series.phase is not Phase.QUALIFYING:
            raise ValueError("Only qualifying Series enter qualifying standings")
        competitors = {series.team_one_id, series.team_two_id}
        if competitors & disqualified:
            continue
        if not competitors <= counters.keys():
            raise ValueError("Series contains a Team outside the qualifying roster")

        if series.is_complete:
            points = series.standing_points
            for team_id in competitors:
                counters[team_id]["standing_points"] += points[team_id]
            assert series.winner is not None or points[series.team_one_id] == 1
            if series.winner is not None:
                counters[series.winner]["series_wins"] += 1
            head_to_head.append(series)

        if series.administrative_winner_id is not None:
            continue
        for match in series.matches:
            for team_id, round_wins in match.round_wins.items():
                counters[team_id]["round_wins"] += round_wins
                opponent = (
                    match.team_two_id
                    if team_id == match.team_one_id
                    else match.team_one_id
                )
                counters[team_id]["round_losses"] += match.round_wins[opponent]
            if match.winner is not None:
                loser = (
                    match.team_two_id
                    if match.winner == match.team_one_id
                    else match.team_one_id
                )
                counters[match.winner]["match_wins"] += 1
                counters[loser]["match_losses"] += 1
            if match.protocol_forfeit_team_id is not None:
                counters[match.protocol_forfeit_team_id][
                    "protocol_fault_forfeits"
                ] += 1

    unranked = [
        Standing(
            team_id=team_id,
            tie_break_key=tie_break_keys[team_id],
            **counters[team_id],
        )
        for team_id in eligible
    ]
    return rank_standings(unranked, head_to_head)


def rank_standings(
    standings: Iterable[Standing],
    head_to_head_series: Iterable[Series] = (),
) -> tuple[Standing, ...]:
    """Apply the seven accepted qualifying tie-breakers in order."""

    records = tuple(standings)
    head_to_head = tuple(head_to_head_series)
    primary_groups: dict[tuple[int, int], list[Standing]] = {}
    for standing in records:
        primary_groups.setdefault(
            (standing.standing_points, standing.series_wins), []
        ).append(standing)

    ranked: list[Standing] = []
    for primary_key in sorted(primary_groups, reverse=True):
        group = primary_groups[primary_key]
        if len(group) == 2:
            direct_winner = _head_to_head_winner(
                group[0].team_id, group[1].team_id, head_to_head
            )
            if direct_winner is not None:
                ranked.extend(
                    sorted(
                        group,
                        key=lambda item: item.team_id != direct_winner,
                    )
                )
                continue
        ranked.extend(
            sorted(
                group,
                key=lambda item: (
                    -item.match_differential,
                    -item.round_differential,
                    item.protocol_fault_forfeits,
                    item.tie_break_key,
                ),
            )
        )
    return tuple(ranked)


def _head_to_head_winner(
    first_team_id: str,
    second_team_id: str,
    series_results: Iterable[Series],
) -> Optional[str]:
    pair = {first_team_id, second_team_id}
    for series in series_results:
        if {series.team_one_id, series.team_two_id} == pair:
            return series.winner
    return None


class PlayoffStage(str, Enum):
    SEMIFINAL = "semifinal"
    FINAL = "final"


@dataclass(frozen=True)
class SeededTeam:
    seed: int
    team_id: str


@dataclass(frozen=True)
class PlayoffFixture:
    stage: PlayoffStage
    team_one_id: Optional[str]
    team_two_id: Optional[str]
    started: bool = False
    winner_id: Optional[str] = None
    administrative: bool = False

    @property
    def competitors(self) -> tuple[str, ...]:
        return tuple(
            team_id
            for team_id in (self.team_one_id, self.team_two_id)
            if team_id is not None
        )

    @property
    def loser_id(self) -> Optional[str]:
        if self.winner_id is None:
            return None
        return next(
            (
                team_id
                for team_id in self.competitors
                if team_id != self.winner_id
            ),
            None,
        )


@dataclass(frozen=True)
class PlayoffBracket:
    qualifying_standings: tuple[Standing, ...]
    seeds: tuple[SeededTeam, ...]
    semifinals: tuple[PlayoffFixture, ...]
    final: Optional[PlayoffFixture]
    disqualified_team_ids: frozenset[str] = frozenset()
    locked: bool = False
    champion: Optional[str] = None
    aborted: bool = False

    def start_semifinal(self, index: int) -> "PlayoffBracket":
        fixture = self.semifinals[index]
        if fixture.winner_id is not None:
            raise ValueError("Semifinal is already complete")
        updated = replace(fixture, started=True)
        return replace(
            self,
            semifinals=_replace_at(self.semifinals, index, updated),
            locked=True,
        )

    def complete_semifinal(
        self, index: int, winner_id: str
    ) -> "PlayoffBracket":
        fixture = self.semifinals[index]
        if not fixture.started:
            raise ValueError("Semifinal has not started")
        if winner_id not in fixture.competitors:
            raise ValueError("Semifinal winner must compete in the Series")
        return self._award_semifinal(index, winner_id, administrative=False)

    def start_final(self) -> "PlayoffBracket":
        if self.final is None or len(self.final.competitors) != 2:
            raise ValueError("Final is not ready to start")
        if self.final.winner_id is not None:
            raise ValueError("Final is already complete")
        return replace(self, final=replace(self.final, started=True), locked=True)

    def complete_final(self, winner_id: str) -> "PlayoffBracket":
        if self.final is None or not self.final.started:
            raise ValueError("Final has not started")
        if winner_id not in self.final.competitors:
            raise ValueError("Final winner must compete in the Series")
        return replace(
            self,
            final=replace(self.final, winner_id=winner_id),
            champion=winner_id,
        )

    def disqualify(self, team_id: str) -> "PlayoffBracket":
        disqualified = self.disqualified_team_ids | {team_id}
        if not self.locked:
            return _build_playoff_bracket(
                self.qualifying_standings, disqualified
            )

        # An uncompleted locked-bracket Series is decided administratively.
        for index, semifinal in enumerate(self.semifinals):
            if semifinal.winner_id is None and team_id in semifinal.competitors:
                opponent = next(
                    item for item in semifinal.competitors if item != team_id
                )
                awarded = self._award_semifinal(
                    index, opponent, administrative=True
                )
                return replace(
                    awarded, disqualified_team_ids=disqualified
                )

        # A Team that advanced is replaced by the Team it most recently
        # eliminated while its next Series has not begun.
        if self.final is not None and not self.final.started:
            for semifinal in self.semifinals:
                if semifinal.winner_id == team_id:
                    reinstated = semifinal.loser_id
                    assert reinstated is not None
                    return replace(
                        self,
                        final=_replace_fixture_team(
                            self.final, team_id, reinstated
                        ),
                        disqualified_team_ids=disqualified,
                    )

        if self.final is not None and team_id in self.final.competitors:
            opponent = next(
                (
                    item
                    for item in self.final.competitors
                    if item != team_id
                ),
                None,
            )
            if opponent is not None:
                return replace(
                    self,
                    final=replace(
                        self.final,
                        winner_id=opponent,
                        administrative=True,
                    ),
                    disqualified_team_ids=disqualified,
                    champion=opponent,
                )
            return replace(
                self,
                final=_replace_fixture_team(self.final, team_id, None),
                disqualified_team_ids=disqualified,
            )

        return replace(self, disqualified_team_ids=disqualified)

    def _award_semifinal(
        self, index: int, winner_id: str, *, administrative: bool
    ) -> "PlayoffBracket":
        fixture = replace(
            self.semifinals[index],
            winner_id=winner_id,
            administrative=administrative,
        )
        semifinals = _replace_at(self.semifinals, index, fixture)
        assert self.final is not None
        if len(semifinals) == 1:
            final = replace(self.final, team_two_id=winner_id)
        elif index == 0:
            final = replace(self.final, team_one_id=winner_id)
        else:
            final = replace(self.final, team_two_id=winner_id)

        champion = self.champion
        if all(item.winner_id is not None for item in semifinals):
            if len(final.competitors) == 1:
                champion = final.competitors[0]
        return replace(
            self,
            semifinals=semifinals,
            final=final,
            locked=True,
            champion=champion,
        )


def create_playoff_bracket(
    qualifying_standings: Iterable[Standing],
    *,
    eligible_team_ids: Optional[Iterable[str]] = None,
) -> PlayoffBracket:
    ranked = rank_standings(qualifying_standings)
    if eligible_team_ids is None:
        disqualified: frozenset[str] = frozenset()
    else:
        eligible = frozenset(eligible_team_ids)
        disqualified = frozenset(
            standing.team_id
            for standing in ranked
            if standing.team_id not in eligible
        )
    return _build_playoff_bracket(ranked, disqualified)


def _build_playoff_bracket(
    qualifying_standings: tuple[Standing, ...],
    disqualified_team_ids: frozenset[str],
) -> PlayoffBracket:
    field = tuple(
        standing
        for standing in qualifying_standings
        if standing.team_id not in disqualified_team_ids
    )[:4]
    seeds = tuple(
        SeededTeam(seed=index, team_id=standing.team_id)
        for index, standing in enumerate(field, start=1)
    )
    team_ids = tuple(seed.team_id for seed in seeds)

    if len(team_ids) >= 4:
        semifinals = (
            PlayoffFixture(PlayoffStage.SEMIFINAL, team_ids[0], team_ids[3]),
            PlayoffFixture(PlayoffStage.SEMIFINAL, team_ids[1], team_ids[2]),
        )
        final: Optional[PlayoffFixture] = PlayoffFixture(
            PlayoffStage.FINAL, None, None
        )
        champion = None
        aborted = False
    elif len(team_ids) == 3:
        semifinals = (
            PlayoffFixture(PlayoffStage.SEMIFINAL, team_ids[1], team_ids[2]),
        )
        final = PlayoffFixture(PlayoffStage.FINAL, team_ids[0], None)
        champion = None
        aborted = False
    elif len(team_ids) == 2:
        semifinals = ()
        final = PlayoffFixture(PlayoffStage.FINAL, team_ids[0], team_ids[1])
        champion = None
        aborted = False
    elif len(team_ids) == 1:
        semifinals = ()
        final = None
        champion = team_ids[0]
        aborted = False
    else:
        semifinals = ()
        final = None
        champion = None
        aborted = True

    return PlayoffBracket(
        qualifying_standings=qualifying_standings,
        seeds=seeds,
        semifinals=semifinals,
        final=final,
        disqualified_team_ids=disqualified_team_ids,
        champion=champion,
        aborted=aborted,
    )


def _replace_at(
    fixtures: tuple[PlayoffFixture, ...],
    index: int,
    replacement: PlayoffFixture,
) -> tuple[PlayoffFixture, ...]:
    return fixtures[:index] + (replacement,) + fixtures[index + 1 :]


def _replace_fixture_team(
    fixture: PlayoffFixture,
    old_team_id: str,
    new_team_id: Optional[str],
) -> PlayoffFixture:
    if fixture.team_one_id == old_team_id:
        return replace(fixture, team_one_id=new_team_id)
    if fixture.team_two_id == old_team_id:
        return replace(fixture, team_two_id=new_team_id)
    return fixture
