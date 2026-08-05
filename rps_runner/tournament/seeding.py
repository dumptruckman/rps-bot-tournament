"""Versioned deterministic derivations for Tournament seeds and ordering."""

from __future__ import annotations

import hashlib
import hmac


SEED_DERIVATION_VERSION = 1
_DOMAIN = "rps-tournament/seed/v1"
_MAX_U64 = (1 << 64) - 1

FIXTURE_SEED_LABEL = "fixture-seed"
MATCH_SEED_LABEL = "match-seed"
BOT_VISIBLE_SEED_LABEL = "bot-visible-seed"
SCHEDULE_SHUFFLE_LABEL = "schedule-shuffle"
BOT_POSITION_LABEL = "bot-position"
TIEBREAK_KEY_LABEL = "tie-break-key"


def derive_u64(
    parent_seed: int, child_type: str, canonical_identifier: str
) -> int:
    """Derive one unsigned 64-bit value using seed derivation version 1."""
    if not isinstance(parent_seed, int) or isinstance(parent_seed, bool):
        raise TypeError("parent_seed must be an integer")
    if not 0 <= parent_seed <= _MAX_U64:
        raise ValueError("parent_seed must be an unsigned 64-bit integer")
    if not isinstance(child_type, str):
        raise TypeError("child_type must be a string")
    if not isinstance(canonical_identifier, str):
        raise TypeError("canonical_identifier must be a string")

    message = b"".join(
        _frame_utf8(component)
        for component in (_DOMAIN, child_type, canonical_identifier)
    )
    digest = hmac.new(
        parent_seed.to_bytes(8, "big"), message, hashlib.sha256
    ).digest()
    return int.from_bytes(digest[:8], "big")


def derive_fixture_seed(tournament_seed: int, fixture_id: str) -> int:
    """Derive the Fixture Seed for a canonical Fixture ID."""
    return derive_u64(tournament_seed, FIXTURE_SEED_LABEL, fixture_id)


def derive_match_seed(fixture_seed: int, match_ordinal: int) -> int:
    """Derive the Match Seed for a one-based Match ordinal."""
    if match_ordinal not in (1, 2, 3):
        raise ValueError("match_ordinal must be between 1 and 3")
    return derive_u64(fixture_seed, MATCH_SEED_LABEL, str(match_ordinal))


def derive_bot_seed(match_seed: int, team_id: str) -> int:
    """Derive a Team-specific bot-visible seed independent of Bot Position."""
    return derive_u64(match_seed, BOT_VISIBLE_SEED_LABEL, team_id)


def derive_schedule_value(tournament_seed: int, team_id: str) -> int:
    """Derive a Team's deterministic schedule-shuffle value."""
    return derive_u64(tournament_seed, SCHEDULE_SHUFFLE_LABEL, team_id)


def derive_position_value(fixture_seed: int, match_ordinal: int) -> int:
    """Derive an independent Bot Position assignment value for a Match."""
    if match_ordinal not in (1, 3):
        raise ValueError("position values are derived only for Match 1 or 3")
    return derive_u64(fixture_seed, BOT_POSITION_LABEL, str(match_ordinal))


def derive_tiebreak_key(tournament_seed: int, team_id: str) -> int:
    """Derive a Team's final qualifying Tie-break Key."""
    return derive_u64(tournament_seed, TIEBREAK_KEY_LABEL, team_id)


def _frame_utf8(component: str) -> bytes:
    encoded = component.encode("utf-8")
    return len(encoded).to_bytes(4, "big") + encoded
