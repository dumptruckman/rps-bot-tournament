from __future__ import annotations

from typing import Protocol

from rps_runner.engine.models import MatchConfig


class BotArtifactDisconnected(Exception):
    """The Bot Artifact closed its request transport."""


class BotSession(Protocol):
    """Runtime-neutral lifecycle and byte transport for one Bot Artifact."""

    bot_position: str
    artifact_reference: str

    @property
    def output_descriptor(self) -> int:
        """Return a descriptor the Match Runner can monitor for output."""

    def start(self) -> None:
        """Start the Bot Artifact and prepare its protocol transport."""

    def send(self, request: bytes) -> None:
        """Send one complete Turn request to the Bot Artifact."""

    def read_output(self, maximum_bytes: int) -> bytes:
        """Read up to ``maximum_bytes`` from the Bot Artifact's output."""

    def disconnection_fault(
        self, turn: int, default_detail: str
    ) -> dict[str, object]:
        """Classify a closed output stream using attributable runtime evidence."""

    def terminate(self) -> None:
        """Ask a faulty Bot Artifact to terminate without blocking."""

    def stop(self) -> None:
        """Begin a graceful stop without blocking."""

    def force_stop(self) -> None:
        """Wait through the grace period and force-stop a survivor."""

    def finish_stop(self) -> None:
        """Reap the stopped Bot Artifact and release session resources."""

    def stderr_text(self) -> str:
        """Return the bounded Bot Artifact diagnostic output."""

    @property
    def stderr_truncated(self) -> bool:
        """Report whether diagnostic output exceeded its capture limit."""

    def operational_telemetry(self) -> dict[str, object]:
        """Return runtime observations excluded from competitive results."""


class BotSessionFactory(Protocol):
    def __call__(
        self,
        bot_position: str,
        artifact_reference: str,
        config: MatchConfig,
    ) -> BotSession:
        """Create an unstarted Bot session for one Bot Position."""
