"""Validated operational inputs for an official Tournament execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
import re
from types import MappingProxyType


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OFFICIAL_PLATFORM = "linux/arm64"


@dataclass(frozen=True)
class TournamentExecutionInputs:
    """Immutable image-selection and lifecycle inputs derived before execution."""

    platform_by_digest: Mapping[str, str]
    startup_timeout_seconds: float
    shutdown_timeout_seconds: float

    def __post_init__(self) -> None:
        if not isinstance(self.platform_by_digest, Mapping):
            raise ValueError("Tournament execution platform mapping is invalid")
        platforms = dict(self.platform_by_digest)
        if not platforms:
            raise ValueError("Tournament execution requires selected Bot Artifacts")
        for digest, platform in platforms.items():
            if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
                raise ValueError("Tournament execution artifact digest is invalid")
            if platform != _OFFICIAL_PLATFORM:
                raise ValueError("Tournament execution platform is invalid")
        for field in ("startup_timeout_seconds", "shutdown_timeout_seconds"):
            value = getattr(self, field)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(field + " must be finite and positive")
        object.__setattr__(
            self,
            "platform_by_digest",
            MappingProxyType(dict(sorted(platforms.items()))),
        )
