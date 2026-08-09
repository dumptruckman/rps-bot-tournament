from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class ExecutionProfile:
    """Ceilings shared by every Bot Position and Language Environment."""

    version: str
    first_move_timeout_ms: int
    move_timeout_ms: int
    total_timeout_ms: int
    cpu_limit_ms: int
    cpu_quota_millis_per_second: int
    memory_limit_bytes: int
    process_limit: int
    open_file_limit: int
    filesystem_write_limit_bytes: int
    stdout_limit_bytes: int
    stderr_limit_bytes: int
    startup_timeout_seconds: float
    shutdown_timeout_seconds: float
    recommended_match_parallelism: int

    def as_mapping(self) -> Mapping[str, Any]:
        return asdict(self)

    @property
    def identity(self) -> str:
        canonical = json.dumps(
            self.as_mapping(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.version + "@sha256:" + hashlib.sha256(canonical).hexdigest()


INITIAL_EXECUTION_PROFILE = ExecutionProfile(
    version="docker-execution-v1",
    first_move_timeout_ms=250,
    move_timeout_ms=50,
    total_timeout_ms=2_000,
    cpu_limit_ms=2_000,
    cpu_quota_millis_per_second=1_000,
    memory_limit_bytes=268_435_456,
    process_limit=64,
    open_file_limit=64,
    filesystem_write_limit_bytes=16_777_216,
    stdout_limit_bytes=4_096,
    stderr_limit_bytes=65_536,
    startup_timeout_seconds=10.0,
    shutdown_timeout_seconds=3.0,
    recommended_match_parallelism=4,
)
