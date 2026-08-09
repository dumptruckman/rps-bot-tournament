from __future__ import annotations

from dataclasses import dataclass, field
import os
import shlex
import signal
import subprocess
import threading
import time
from typing import BinaryIO, Optional, cast

from rps_runner.engine.bot_session import BotArtifactDisconnected
from rps_runner.engine.models import InfrastructureError, MatchConfig


TERMINATION_GRACE_NS = 200_000_000
FINAL_WAIT_SECONDS = 1


@dataclass
class StderrCapture:
    stream: BinaryIO
    limit: int
    captured: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    thread: Optional[threading.Thread] = None

    def start(self) -> None:
        thread = threading.Thread(target=self._drain, daemon=True)
        self.thread = thread
        thread.start()

    def _drain(self) -> None:
        while True:
            chunk = self.stream.read(8192)
            if not chunk:
                return
            available = max(0, self.limit - len(self.captured))
            self.captured.extend(chunk[:available])
            if len(chunk) > available:
                self.truncated = True

    def finish(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=1)

    def text(self) -> str:
        return bytes(self.captured).decode("utf-8", errors="replace")


@dataclass
class HostProcessBotSession:
    """Explicitly insecure host-process implementation of a Bot session."""

    bot_position: str
    artifact_reference: str
    config: MatchConfig
    process: Optional[subprocess.Popen[bytes]] = None
    stderr: Optional[StderrCapture] = None
    stop_deadline_ns: Optional[int] = None

    @property
    def output_descriptor(self) -> int:
        process = self._started_process()
        assert process.stdout is not None
        return process.stdout.fileno()

    def start(self) -> None:
        try:
            arguments = shlex.split(self.artifact_reference)
        except ValueError as error:
            raise InfrastructureError(
                f"Could not parse bot {self.bot_position} command: {error}"
            ) from error
        if not arguments:
            raise InfrastructureError(
                f"Could not start bot {self.bot_position}: command is empty"
            )

        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("RPS_")
        }
        environment.update(
            {
                "RPS_PROTOCOL_VERSION": "1",
                "RPS_ROUNDS": str(self.config.rounds),
                "RPS_SEED": str(
                    self.config.seed_for_bot_position(self.bot_position)
                ),
            }
        )
        try:
            process = subprocess.Popen(
                arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
        except OSError as error:
            raise InfrastructureError(
                "Could not start bot "
                f"{self.bot_position} ({self.artifact_reference!r}): {error}"
            ) from error

        self.process = process
        assert process.stderr is not None
        self.stderr = StderrCapture(
            cast(BinaryIO, process.stderr), self.config.stderr_limit_bytes
        )
        self.stderr.start()

    def send(self, request: bytes) -> None:
        process = self._started_process()
        assert process.stdin is not None
        try:
            process.stdin.write(request)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self.terminate()
            raise BotArtifactDisconnected from error

    def read_output(self, maximum_bytes: int) -> bytes:
        try:
            return os.read(self.output_descriptor, maximum_bytes)
        except OSError as error:
            raise InfrastructureError(
                f"Could not read bot {self.bot_position} output: {error}"
            ) from error

    def disconnection_fault(
        self, turn: int, default_detail: str
    ) -> dict[str, object]:
        return {"kind": "unexpected_exit", "turn": turn, "detail": default_detail}

    def terminate(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            try:
                process.send_signal(signal.SIGTERM)
            except OSError:
                pass

    def stop(self) -> None:
        process = self.process
        if process is None:
            return

        self._close_input(process)
        self._signal_if_running(process, signal.SIGTERM)
        self.stop_deadline_ns = time.monotonic_ns() + TERMINATION_GRACE_NS

    def force_stop(self) -> None:
        process = self.process
        if process is None:
            return

        deadline_ns = self.stop_deadline_ns
        if deadline_ns is None:
            self.stop()
            assert self.stop_deadline_ns is not None
            deadline_ns = self.stop_deadline_ns
        self._wait_until(process, deadline_ns)
        self._signal_if_running(process, signal.SIGKILL)

    def finish_stop(self) -> None:
        process = self.process
        if process is None:
            return
        self._reap(process)

    def stderr_text(self) -> str:
        return "" if self.stderr is None else self.stderr.text()

    @property
    def stderr_truncated(self) -> bool:
        return False if self.stderr is None else self.stderr.truncated

    def operational_telemetry(self) -> dict[str, object]:
        return {}

    def _started_process(self) -> subprocess.Popen[bytes]:
        if self.process is None:
            raise InfrastructureError(
                f"Bot {self.bot_position} session has not been started"
            )
        return self.process

    def _close_input(self, process: subprocess.Popen[bytes]) -> None:
        if process.stdin is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass

    def _signal_if_running(
        self,
        process: subprocess.Popen[bytes],
        requested_signal: signal.Signals,
    ) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, requested_signal)
        except OSError:
            try:
                process.send_signal(requested_signal)
            except OSError:
                pass

    def _wait_until(
        self, process: subprocess.Popen[bytes], deadline_ns: int
    ) -> None:
        remaining = max(0, deadline_ns - time.monotonic_ns()) / 1_000_000_000
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass

    def _reap(self, process: subprocess.Popen[bytes]) -> None:
        try:
            process.wait(timeout=FINAL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        if self.stderr is not None:
            self.stderr.finish()
        for stream in (process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass
