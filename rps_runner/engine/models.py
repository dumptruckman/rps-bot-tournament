from __future__ import annotations

from dataclasses import dataclass


class InfrastructureError(RuntimeError):
    """The runner could not create or operate the match infrastructure."""


@dataclass(frozen=True)
class MatchConfig:
    bot_a: str
    bot_b: str
    rounds: int
    seed: int
    first_move_timeout_ms: int = 250
    move_timeout_ms: int = 50
    total_timeout_ms: int = 2000
    stderr_limit_bytes: int = 65_536
