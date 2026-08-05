"""Exclusive operational run locking for a Tournament directory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import socket
from types import TracebackType
from typing import Optional, Type, Union
import uuid


LOCK_FILENAME = ".tournament-run.lock"


@dataclass(frozen=True)
class LockOwner:
    """Diagnostics identifying one Tournament run-lock holder."""

    token: str
    pid: int
    hostname: str


class TournamentRunLockError(RuntimeError):
    """Base error for Tournament run-lock acquisition or release."""


class TournamentRunLockHeldError(TournamentRunLockError):
    """Another owner already holds the Tournament run lock."""

    def __init__(self, lock_path: Path, owner: Optional[LockOwner]):
        self.lock_path = lock_path
        self.owner = owner
        details = "owner diagnostics unavailable"
        if owner is not None:
            details = (
                f"pid={owner.pid}, hostname={owner.hostname}, "
                f"token={owner.token}"
            )
        super().__init__(f"Tournament run lock is already held: {details}")


class TournamentRunLockOwnershipError(TournamentRunLockError):
    """The on-disk lock no longer belongs to the releasing holder."""

    def __init__(
        self,
        lock_path: Path,
        expected_owner: LockOwner,
        observed_owner: Optional[LockOwner],
    ):
        self.lock_path = lock_path
        self.expected_owner = expected_owner
        self.observed_owner = observed_owner
        super().__init__(
            "Tournament run lock ownership changed; the lock was preserved "
            "for operator intervention"
        )


class TournamentRunLock:
    """An exclusive context-managed lock for one Tournament directory."""

    def __init__(self, tournament_directory: Union[str, os.PathLike[str]]):
        self.tournament_directory = Path(tournament_directory)
        self.lock_path = self.tournament_directory / LOCK_FILENAME
        self.owner = LockOwner(
            token=str(uuid.uuid4()),
            pid=os.getpid(),
            hostname=socket.gethostname(),
        )

    def __enter__(self) -> "TournamentRunLock":
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            raise TournamentRunLockHeldError(
                self.lock_path, _read_owner(self.lock_path)
            ) from None
        try:
            record = json.dumps(
                asdict(self.owner), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            os.write(descriptor, record)
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            self.lock_path.unlink()
            raise
        os.close(descriptor)
        return self

    def __exit__(
        self,
        exception_type: Optional[Type[BaseException]],
        exception: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> bool:
        observed_owner = _read_owner(self.lock_path)
        if (
            observed_owner is None
            or observed_owner.token != self.owner.token
        ):
            raise TournamentRunLockOwnershipError(
                self.lock_path, self.owner, observed_owner
            )
        self.lock_path.unlink()
        return False


def _read_owner(lock_path: Path) -> Optional[LockOwner]:
    try:
        record = json.loads(lock_path.read_text(encoding="utf-8"))
        return LockOwner(
            token=record["token"],
            pid=record["pid"],
            hostname=record["hostname"],
        )
    except (KeyError, OSError, TypeError, ValueError):
        return None
