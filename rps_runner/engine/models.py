from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class InfrastructureError(RuntimeError):
    """The runner could not create or operate the match infrastructure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.operational_telemetry: dict[str, object] = {}

    def retain_diagnostic(self, key: str, value: object) -> None:
        self.operational_telemetry[key] = value


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
    bot_a_seed: Optional[int] = None
    bot_b_seed: Optional[int] = None
    stdout_limit_bytes: int = 4_096

    def __post_init__(self) -> None:
        maximum_seed = 2**64 - 1
        for field_name in ("seed", "bot_a_seed", "bot_b_seed"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= maximum_seed
            ):
                raise ValueError(
                    f"{field_name} must be an unsigned 64-bit integer"
                )
        if (
            not isinstance(self.stdout_limit_bytes, int)
            or isinstance(self.stdout_limit_bytes, bool)
            or self.stdout_limit_bytes <= 0
        ):
            raise ValueError("stdout_limit_bytes must be a positive integer")

    def seed_for_bot_position(self, bot_position: str) -> int:
        """Return the bot-visible seed assigned to Bot Position ``a`` or ``b``."""

        if bot_position == "a":
            return self.seed if self.bot_a_seed is None else self.bot_a_seed
        if bot_position == "b":
            return self.seed if self.bot_b_seed is None else self.bot_b_seed
        raise ValueError(f"Unknown Bot Position: {bot_position!r}")
