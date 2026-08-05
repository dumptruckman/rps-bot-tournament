"""Canonical deterministic qualifying schedule generation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from .seeding import (
    derive_fixture_seed,
    derive_position_value,
    derive_schedule_value,
)


@dataclass(frozen=True)
class BotPositions:
    """The internal Team assignment to Bot Positions ``a`` and ``b``."""

    team_a_id: str
    team_b_id: str


@dataclass(frozen=True)
class Fixture:
    """One qualifying Fixture in canonical result order."""

    fixture_id: str
    ordinal: int
    batch_ordinal: int
    team_ids: tuple[str, str]
    fixture_seed: int


@dataclass(frozen=True)
class FixtureBatch:
    """An ordered batch in which each Team appears at most once."""

    ordinal: int
    fixtures: tuple[Fixture, ...]
    bye_team_id: Optional[str]


def bot_positions(
    fixture_seed: int,
    match_ordinal: int,
    team_one_id: str,
    team_two_id: str,
) -> BotPositions:
    """Assign Teams to Bot Positions for one best-of-three Series Match."""
    if match_ordinal not in (1, 2, 3):
        raise ValueError("match_ordinal must be between 1 and 3")
    if match_ordinal == 2:
        first_match = bot_positions(
            fixture_seed, 1, team_one_id, team_two_id
        )
        return BotPositions(
            team_a_id=first_match.team_b_id,
            team_b_id=first_match.team_a_id,
        )

    value = derive_position_value(fixture_seed, match_ordinal)
    if value % 2 == 0:
        return BotPositions(team_a_id=team_one_id, team_b_id=team_two_id)
    return BotPositions(team_a_id=team_two_id, team_b_id=team_one_id)


def shuffle_team_ids(
    team_ids: Iterable[str], tournament_seed: int
) -> tuple[str, ...]:
    """Return canonical Team IDs in deterministic Tournament-seeded order."""
    canonical_team_ids = tuple(sorted(team_ids))
    return tuple(
        sorted(
            canonical_team_ids,
            key=lambda team_id: (
                derive_schedule_value(tournament_seed, team_id),
                team_id,
            ),
        )
    )


def build_qualifying_schedule(
    team_ids: Iterable[str], tournament_seed: int
) -> tuple[FixtureBatch, ...]:
    """Build the canonical circle-method qualifying schedule."""
    roster = tuple(team_ids)
    if not 4 <= len(roster) <= 32:
        raise ValueError(
            "qualifying roster must contain between 4 and 32 Teams"
        )
    if len(set(roster)) != len(roster):
        raise ValueError("qualifying roster Team IDs must be unique")

    rotating: list[Optional[str]] = list(
        shuffle_team_ids(roster, tournament_seed)
    )
    if len(rotating) % 2:
        rotating.append(None)
    batch_count = len(rotating) - 1
    fixture_ordinal = 1
    batches: list[FixtureBatch] = []

    for batch_ordinal in range(1, batch_count + 1):
        fixtures: list[Fixture] = []
        bye_team_id: Optional[str] = None
        for pair_index in range(len(rotating) // 2):
            team_one = rotating[pair_index]
            team_two = rotating[-1 - pair_index]
            if team_one is None or team_two is None:
                bye_team_id = team_two if team_one is None else team_one
                continue
            fixture_id = f"qualifying-{fixture_ordinal:04d}"
            fixtures.append(
                Fixture(
                    fixture_id=fixture_id,
                    ordinal=fixture_ordinal,
                    batch_ordinal=batch_ordinal,
                    team_ids=(team_one, team_two),
                    fixture_seed=derive_fixture_seed(
                        tournament_seed, fixture_id
                    ),
                )
            )
            fixture_ordinal += 1
        batches.append(
            FixtureBatch(
                ordinal=batch_ordinal,
                fixtures=tuple(fixtures),
                bye_team_id=bye_team_id,
            )
        )
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]

    return tuple(batches)
