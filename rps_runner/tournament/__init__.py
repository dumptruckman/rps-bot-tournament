"""Deterministic Tournament scheduling and competitive rules."""

from .schedule import (
    BotPositions,
    Fixture,
    FixtureBatch,
    bot_positions,
    build_qualifying_schedule,
    shuffle_team_ids,
)
from .seeding import (
    SEED_DERIVATION_VERSION,
    derive_bot_seed,
    derive_fixture_seed,
    derive_match_seed,
    derive_position_value,
    derive_schedule_value,
    derive_tiebreak_key,
    derive_u64,
)

__all__ = [
    "BotPositions",
    "Fixture",
    "FixtureBatch",
    "SEED_DERIVATION_VERSION",
    "bot_positions",
    "build_qualifying_schedule",
    "derive_bot_seed",
    "derive_fixture_seed",
    "derive_match_seed",
    "derive_position_value",
    "derive_schedule_value",
    "derive_tiebreak_key",
    "derive_u64",
    "shuffle_team_ids",
]
