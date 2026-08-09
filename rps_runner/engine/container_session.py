from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
import subprocess
import threading
import time
from typing import BinaryIO, Optional, Sequence, cast
import uuid

from rps_runner.engine.bot_session import BotArtifactDisconnected
from rps_runner.engine.models import InfrastructureError, MatchConfig


DEFAULT_READINESS_MARKER = b"RPS_READY_V1"
IMPORT_STDERR_ESCAPE = b"RPS_STDERR_ESCAPE_V1:"


@dataclass(frozen=True)
class ContainerOperations:
    """Operational Docker settings kept outside competitive response budgets."""

    docker_command: tuple[str, ...] = ("docker",)
    startup_timeout_seconds: float = 10.0
    command_timeout_seconds: float = 10.0
    shutdown_timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        if not self.docker_command or any(not part for part in self.docker_command):
            raise ValueError("docker_command must contain a command")
        for field_name in (
            "startup_timeout_seconds",
            "command_timeout_seconds",
            "shutdown_timeout_seconds",
        ):
            value = getattr(self, field_name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{field_name} must be finite and positive")


@dataclass
class ReadinessStderrCapture:
    stream: BinaryIO
    marker: bytes
    limit: int
    captured: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    ready: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

    def _drain(self) -> None:
        pending = bytearray()
        diagnostic_line = False
        try:
            while True:
                chunk = os.read(self.stream.fileno(), 8192)
                if not chunk:
                    break
                for value in chunk:
                    byte = bytes((value,))
                    if self.ready.is_set() or diagnostic_line:
                        self._capture(byte)
                        if byte == b"\n":
                            diagnostic_line = False
                        continue
                    pending.append(value)
                    if bytes(pending) == IMPORT_STDERR_ESCAPE:
                        pending.clear()
                        diagnostic_line = True
                    elif byte == b"\n":
                        self._consume_candidate(bytes(pending[:-1]))
                        pending.clear()
                    elif not self.marker.startswith(
                        bytes(pending)
                    ) and not IMPORT_STDERR_ESCAPE.startswith(bytes(pending)):
                        self._capture(bytes(pending))
                        pending.clear()
                        diagnostic_line = True
            if pending:
                self._capture(bytes(pending))
        finally:
            self.finished.set()

    def _consume_candidate(self, line: bytes) -> None:
        content = line[:-1] if line.endswith(b"\r") else line
        if content == self.marker:
            self.ready.set()
            return
        self._capture(line + b"\n")

    def _capture(self, diagnostic: bytes) -> None:
        available = max(0, self.limit - len(self.captured))
        self.captured.extend(diagnostic[:available])
        if len(diagnostic) > available:
            self.truncated = True

    def finish(self) -> None:
        if self.thread is not None:
            self.thread.join(timeout=1)

    def text(self) -> str:
        return bytes(self.captured).decode("utf-8", errors="replace")


@dataclass
class ContainerBotSession:
    """Docker CLI implementation of one runtime-neutral Bot Artifact session."""

    bot_position: str
    artifact_reference: str
    config: MatchConfig
    operations: ContainerOperations = field(default_factory=ContainerOperations)
    readiness_marker: bytes = DEFAULT_READINESS_MARKER
    container_id: Optional[str] = None
    attach_process: Optional[subprocess.Popen[bytes]] = None
    stderr: Optional[ReadinessStderrCapture] = None
    stop_process: Optional[subprocess.Popen[bytes]] = None
    terminate_process: Optional[subprocess.Popen[bytes]] = None
    container_started: bool = False

    @property
    def output_descriptor(self) -> int:
        process = self._attached_process()
        assert process.stdout is not None
        return process.stdout.fileno()

    def start(self) -> None:
        self.container_id = "rps-match-" + uuid.uuid4().hex
        completed = self._run(
            [
                "create",
                "--name",
                self.container_id,
                "--interactive",
                "--env",
                "RPS_PROTOCOL_VERSION=1",
                "--env",
                f"RPS_ROUNDS={self.config.rounds}",
                "--env",
                "RPS_SEED="
                + str(self.config.seed_for_bot_position(self.bot_position)),
                self.artifact_reference,
            ],
            "create",
        )
        container_id = completed.stdout.decode("utf-8", errors="replace").strip()
        if not container_id or "\n" in container_id:
            raise InfrastructureError(
                "Docker create returned an invalid container ID for Bot Position "
                + self.bot_position
            )
        self.container_id = container_id
        try:
            process = subprocess.Popen(
                self._arguments("start", "--attach", "--interactive", container_id),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise InfrastructureError(
                f"Could not attach Bot Position {self.bot_position} container: {error}"
            ) from error
        self.attach_process = process
        self.container_started = True
        assert process.stderr is not None
        self.stderr = ReadinessStderrCapture(
            cast(BinaryIO, process.stderr),
            self.readiness_marker,
            self.config.stderr_limit_bytes,
        )
        self.stderr.start()
        self._await_readiness(process)

    def _await_readiness(self, process: subprocess.Popen[bytes]) -> None:
        assert self.stderr is not None
        deadline = time.monotonic() + self.operations.startup_timeout_seconds
        while not self.stderr.ready.is_set():
            if process.poll() is not None and self.stderr.finished.wait(0.01):
                status = self._container_status()
                if status not in {"dead", "exited"}:
                    raise InfrastructureError(
                        f"Docker attach failed for Bot Position {self.bot_position}; "
                        f"container status is {status!r}"
                    )
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InfrastructureError(
                    f"Bot Position {self.bot_position} container readiness timed out"
                )
            self.stderr.ready.wait(min(remaining, 0.01))

    def _container_status(self) -> str:
        assert self.container_id is not None
        completed = self._run(
            [
                "inspect",
                "--format",
                "{{.State.Status}}",
                self.container_id,
            ],
            "inspect",
        )
        return completed.stdout.decode("utf-8", errors="replace").strip()

    def send(self, request: bytes) -> None:
        process = self._attached_process()
        assert process.stdin is not None
        try:
            process.stdin.write(request)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self.terminate()
            raise BotArtifactDisconnected from error

    def read_output(self, maximum_bytes: int) -> bytes:
        process = self._attached_process()
        assert process.stdout is not None
        try:
            return process.stdout.read1(maximum_bytes)
        except OSError as error:
            raise InfrastructureError(
                "Could not read Bot Position "
                f"{self.bot_position} container output: {error}"
            ) from error

    def terminate(self) -> None:
        if (
            self.container_id is None
            or not self.container_started
            or self.terminate_process is not None
        ):
            return
        try:
            self.terminate_process = subprocess.Popen(
                self._arguments("kill", self.container_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError:
            pass

    def stop(self) -> None:
        process = self.attach_process
        if process is not None and process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.stdin = None
        if (
            self.container_id is None
            or not self.container_started
            or self.stop_process is not None
        ):
            return
        try:
            self.stop_process = subprocess.Popen(
                self._arguments("stop", "--time", "1", self.container_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise InfrastructureError(
                f"Could not stop Bot Position {self.bot_position} container: {error}"
            ) from error

    def force_stop(self) -> None:
        stop_process = self.stop_process
        if stop_process is None:
            return
        try:
            _, diagnostics_bytes = stop_process.communicate(
                timeout=self.operations.shutdown_timeout_seconds
            )
        except subprocess.TimeoutExpired:
            stop_process.kill()
            stop_process.communicate()
            if self.container_id is not None:
                self._run(["kill", self.container_id], "kill")
            return
        if stop_process.returncode != 0:
            diagnostics = diagnostics_bytes.decode(
                "utf-8", errors="replace"
            )
            raise InfrastructureError(
                "Docker stop failed for Bot Position "
                f"{self.bot_position}: {diagnostics.strip()}"
            )

    def finish_stop(self) -> None:
        try:
            self._finish_helper(self.terminate_process)
            self._finish_helper(self.attach_process, read_pipes=False)
            if self.container_id is not None:
                self._run(
                    ["rm", "--force", self.container_id],
                    "remove",
                    missing_ok=True,
                )
                self.container_id = None
        finally:
            if self.stderr is not None:
                self.stderr.finish()
            process = self.attach_process
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except OSError:
                            pass

    def _finish_helper(
        self,
        process: Optional[subprocess.Popen[bytes]],
        *,
        read_pipes: bool = True,
    ) -> None:
        if process is None:
            return
        try:
            if read_pipes:
                process.communicate(
                    timeout=self.operations.shutdown_timeout_seconds
                )
            else:
                process.wait(timeout=self.operations.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            if read_pipes:
                process.communicate()
            else:
                process.wait()

    def stderr_text(self) -> str:
        return "" if self.stderr is None else self.stderr.text()

    @property
    def stderr_truncated(self) -> bool:
        return False if self.stderr is None else self.stderr.truncated

    def _run(
        self,
        arguments: Sequence[str],
        operation: str,
        *,
        missing_ok: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            completed = subprocess.run(
                self._arguments(*arguments),
                capture_output=True,
                timeout=self.operations.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise InfrastructureError(
                f"Docker {operation} timed out for Bot Position {self.bot_position}"
            ) from error
        except OSError as error:
            raise InfrastructureError(
                f"Could not run Docker {operation} for Bot Position "
                f"{self.bot_position}: {error}"
            ) from error
        if completed.returncode != 0:
            diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
            if missing_ok and "no such container" in diagnostics.lower():
                return completed
            raise InfrastructureError(
                f"Docker {operation} failed for Bot Position "
                f"{self.bot_position}: {diagnostics}"
            )
        return completed

    def _arguments(self, *arguments: str) -> list[str]:
        return [*self.operations.docker_command, *arguments]

    def _attached_process(self) -> subprocess.Popen[bytes]:
        if self.attach_process is None:
            raise InfrastructureError(
                f"Bot Position {self.bot_position} container session was not started"
            )
        return self.attach_process
