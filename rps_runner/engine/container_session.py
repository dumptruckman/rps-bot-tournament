from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import threading
import time
from typing import BinaryIO, ClassVar, Optional, Sequence, cast

from rps_runner.engine.bot_session import BotArtifactDisconnected
from rps_runner.engine.models import InfrastructureError, MatchConfig
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE


DEFAULT_READINESS_MARKER = b"RPS_READY_V1"
IMPORT_STDERR_ESCAPE = b"RPS_STDERR_ESCAPE_V1:"
SECURITY_EVIDENCE_PREFIX = "RPS_SECURITY_EVIDENCE_V1:"
RESOURCE_EVIDENCE_PREFIX = "RPS_RESOURCE_EVIDENCE_V1:"
CONTAINER_ISOLATION_PROFILE_VERSION = INITIAL_EXECUTION_PROFILE.version
RUNNER_OWNER_LABEL = "rps.runner.owner"
MATCH_LABEL = "rps.match"
MATCH_ATTEMPT_LABEL = "rps.match-attempt"
BOT_POSITION_LABEL = "rps.bot-position"
RUNNER_OWNER = "rps-tournament"
_SECCOMP_POLICY_PATH = Path(__file__).with_name(
    "seccomp-docker-execution-v1.json"
)
_SECCOMP_POLICY_SHA256 = (
    "8887966730a34413633a566ddf320097b5b526525c4b16a1f8587dea26986400"
)


@dataclass(frozen=True)
class ContainerIsolationProfile:
    """One immutable prevention-first contract for every Bot Position."""

    version: str
    cpu_millis_per_second: int
    memory_limit_bytes: int
    process_limit: int
    open_file_limit: int
    writable_filesystem_limit_bytes: int
    cpu_quota_millis_per_second: int = 1_000
    NUMERIC_USER: ClassVar[str] = "65532:65532"
    HOSTNAME: ClassVar[str] = "rps-bot"
    INFRASTRUCTURE_ENVIRONMENT: ClassVar[tuple[tuple[str, str], ...]] = (
        ("LANG", "C.UTF-8"),
        ("LC_ALL", "C.UTF-8"),
        ("TZ", "UTC"),
        ("HOME", "/tmp"),
        ("TMPDIR", "/tmp"),
    )
    SECCOMP_POLICY_SHA256: ClassVar[str] = _SECCOMP_POLICY_SHA256

    def __post_init__(self) -> None:
        if self.version != CONTAINER_ISOLATION_PROFILE_VERSION:
            raise ValueError(
                "Unsupported container isolation profile version: "
                f"{self.version!r}"
            )
        for field_name in (
            "cpu_millis_per_second",
            "memory_limit_bytes",
            "process_limit",
            "open_file_limit",
            "writable_filesystem_limit_bytes",
            "cpu_quota_millis_per_second",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.cpu_millis_per_second % 1000 != 0:
            raise ValueError("cpu_millis_per_second must use whole CPU seconds")

    def create_arguments(self, protocol_environment: tuple[str, ...]) -> list[str]:
        """Translate the versioned contract into Docker create arguments."""

        seccomp_path = self._verified_seccomp_policy_path()
        cpu_count = str(
            Decimal(self.cpu_quota_millis_per_second) / Decimal(1000)
        )
        total_cpu_seconds = self.cpu_millis_per_second // 1000
        arguments = [
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,"
            f"size={self.writable_filesystem_limit_bytes},"
            "mode=700,uid=65532,gid=65532",
            "--tmpfs",
            "/dev/shm:ro,noexec,nosuid,nodev,size=4096,mode=000",
            "--user",
            self.NUMERIC_USER,
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--security-opt",
            f"seccomp={seccomp_path}",
            "--pids-limit",
            str(self.process_limit),
            "--ulimit",
            f"nofile={self.open_file_limit}:{self.open_file_limit}",
            "--ulimit",
            f"cpu={total_cpu_seconds}:{total_cpu_seconds}",
            "--memory",
            str(self.memory_limit_bytes),
            "--memory-swap",
            str(self.memory_limit_bytes),
            "--cpus",
            cpu_count,
            "--hostname",
            self.HOSTNAME,
            "--ipc",
            "private",
            "--cgroupns",
            "private",
        ]
        for name, value in self.INFRASTRUCTURE_ENVIRONMENT:
            arguments.extend(("--env", f"{name}={value}"))
        for value in protocol_environment:
            arguments.extend(("--env", value))
        return arguments

    def _verified_seccomp_policy_path(self) -> Path:
        try:
            content = _SECCOMP_POLICY_PATH.read_bytes()
        except OSError as error:
            raise InfrastructureError(
                f"Could not read pinned syscall policy: {error}"
            ) from error
        actual = hashlib.sha256(content).hexdigest()
        if actual != self.SECCOMP_POLICY_SHA256:
            raise InfrastructureError("Pinned syscall policy digest does not match")
        return _SECCOMP_POLICY_PATH


@dataclass(frozen=True)
class ContainerOperations:
    """Operational Docker settings kept outside competitive response budgets."""

    docker_command: tuple[str, ...] = ("docker",)
    startup_timeout_seconds: float = INITIAL_EXECUTION_PROFILE.startup_timeout_seconds
    command_timeout_seconds: float = 10.0
    shutdown_timeout_seconds: float = INITIAL_EXECUTION_PROFILE.shutdown_timeout_seconds

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


@dataclass(frozen=True)
class ContainerMatchAttemptIdentity:
    """Canonical Match Attempt identity used for precise Docker ownership."""

    value: str

    @classmethod
    def from_request(
        cls, tournament_id: str, match_id: str, attempt_number: int
    ) -> "ContainerMatchAttemptIdentity":
        return cls(f"{tournament_id}/{match_id}/attempt-{attempt_number}")

    def container_name(self, bot_position: str) -> str:
        digest = hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:20]
        return f"rps-match-{digest}-{bot_position}"

    @property
    def match_value(self) -> str:
        return self.value.rsplit("/attempt-", 1)[0]

    def labels(self, bot_position: str) -> tuple[str, ...]:
        return (
            f"{RUNNER_OWNER_LABEL}={RUNNER_OWNER}",
            f"{MATCH_LABEL}={self.match_value}",
            f"{MATCH_ATTEMPT_LABEL}={self.value}",
            f"{BOT_POSITION_LABEL}={bot_position}",
        )


def cleanup_stale_match_containers(
    identity: ContainerMatchAttemptIdentity,
    operations: ContainerOperations,
    docker_operations: Optional[list[dict[str, object]]] = None,
) -> list[str]:
    """Remove stale runner-owned containers for this canonical Match."""

    completed = _run_docker_command(
        operations,
        (
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label={RUNNER_OWNER_LABEL}={RUNNER_OWNER}",
            "--filter",
            f"label={MATCH_LABEL}={identity.match_value}",
        ),
        "list stale Match containers",
        docker_operations,
    )
    container_ids = [
        line.strip()
        for line in completed.stdout.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if any(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
        for value in container_ids
    ):
        raise InfrastructureError(
            "Docker returned unsafe runner-owned container identities"
        )
    for container_id in container_ids:
        _run_docker_command(
            operations,
            ("rm", "--force", container_id),
            "remove stale Match container",
            docker_operations,
        )
    return container_ids


def inspect_docker_engine(
    operations: ContainerOperations,
    docker_operations: Optional[list[dict[str, object]]] = None,
) -> dict[str, object]:
    completed = _run_docker_command(
        operations,
        ("version", "--format", "{{json .Server}}"),
        "inspect the Docker engine",
        docker_operations,
    )
    try:
        details = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise InfrastructureError("Docker returned invalid engine details") from error
    if not isinstance(details, dict):
        raise InfrastructureError("Docker returned invalid engine details")
    return details


def _run_docker_command(
    operations: ContainerOperations,
    arguments: Sequence[str],
    operation: str,
    docker_operations: Optional[list[dict[str, object]]] = None,
) -> subprocess.CompletedProcess[bytes]:
    command = [*operations.docker_command, *arguments]
    started_ns = time.monotonic_ns()
    observation: dict[str, object] = {
        "command": command,
        "started_at": _utc_timestamp(),
    }
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=operations.command_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        observation.update(
            {
                "duration_ms": _duration_ms(started_ns),
                "returncode": None,
                "raw_error": str(error),
            }
        )
        if docker_operations is not None:
            docker_operations.append(observation)
        raise InfrastructureError(f"Docker {operation} timed out") from error
    except OSError as error:
        observation.update(
            {
                "duration_ms": _duration_ms(started_ns),
                "returncode": None,
                "raw_error": str(error),
            }
        )
        if docker_operations is not None:
            docker_operations.append(observation)
        raise InfrastructureError(f"Could not {operation}: {error}") from error
    diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
    observation.update(
        {
            "duration_ms": _duration_ms(started_ns),
            "returncode": completed.returncode,
            "raw_error": diagnostics,
        }
    )
    if docker_operations is not None:
        docker_operations.append(observation)
    if completed.returncode != 0:
        raise InfrastructureError(f"Docker could not {operation}: {diagnostics}")
    return completed


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
    isolation_profile: ContainerIsolationProfile
    match_attempt_identity: ContainerMatchAttemptIdentity
    engine_details: dict[str, object]
    operations: ContainerOperations = field(default_factory=ContainerOperations)
    readiness_marker: bytes = DEFAULT_READINESS_MARKER
    container_id: Optional[str] = None
    attach_process: Optional[subprocess.Popen[bytes]] = None
    stderr: Optional[ReadinessStderrCapture] = None
    stop_process: Optional[subprocess.Popen[bytes]] = None
    terminate_process: Optional[subprocess.Popen[bytes]] = None
    container_started: bool = False
    final_state: Optional[dict[str, object]] = None
    container_name: Optional[str] = None
    created_container_id: Optional[str] = None
    started_at: Optional[str] = None
    startup_duration_ms: Optional[float] = None
    cleanup_started_at: Optional[str] = None
    cleanup_duration_ms: Optional[float] = None
    cleanup_started_ns: Optional[int] = None
    docker_commands: list[list[str]] = field(default_factory=list)
    raw_errors: list[str] = field(default_factory=list)
    security_evidence: Optional[dict[str, object]] = None

    @property
    def output_descriptor(self) -> int:
        process = self._attached_process()
        assert process.stdout is not None
        return process.stdout.fileno()

    def start(self) -> None:
        startup_started_ns = time.monotonic_ns()
        self.started_at = _utc_timestamp()
        self.container_name = self.match_attempt_identity.container_name(
            self.bot_position
        )
        self.container_id = self.container_name
        labels: list[str] = []
        for label in self.match_attempt_identity.labels(self.bot_position):
            labels.extend(("--label", label))
        try:
            completed = self._run(
                [
                    "create",
                    "--name",
                    self.container_id,
                    *labels,
                    "--interactive",
                    *self.isolation_profile.create_arguments(
                        (
                            "RPS_PROTOCOL_VERSION=1",
                            f"RPS_ROUNDS={self.config.rounds}",
                            "RPS_SEED="
                            + str(
                                self.config.seed_for_bot_position(self.bot_position)
                            ),
                        )
                    ),
                    self.artifact_reference,
                ],
                "create",
            )
            container_id = completed.stdout.decode(
                "utf-8", errors="replace"
            ).strip()
            if not container_id or "\n" in container_id:
                raise InfrastructureError(
                    "Docker create returned an invalid container ID for Bot Position "
                    + self.bot_position
                )
            self.container_id = container_id
            self.created_container_id = container_id
            start_arguments = self._arguments(
                "start", "--attach", "--interactive", container_id
            )
            self.docker_commands.append(start_arguments)
            process = subprocess.Popen(
                start_arguments,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            self.raw_errors.append(str(error))
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
        try:
            self._await_readiness(process)
        finally:
            self.startup_duration_ms = _duration_ms(startup_started_ns)

    def _await_readiness(self, process: subprocess.Popen[bytes]) -> None:
        assert self.stderr is not None
        deadline = time.monotonic() + self.operations.startup_timeout_seconds
        while not self.stderr.ready.is_set():
            if process.poll() is not None and self.stderr.finished.wait(0.01):
                status = self._container_state().get("Status")
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

    def _container_state(self) -> dict[str, object]:
        if self.final_state is not None:
            return self.final_state
        assert self.container_id is not None
        completed = self._run(
            [
                "inspect",
                "--format",
                "{{json .State}}",
                self.container_id,
            ],
            "inspect",
        )
        try:
            state = json.loads(completed.stdout)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise InfrastructureError(
                "Docker inspect returned invalid state for Bot Position "
                + self.bot_position
            ) from error
        if not isinstance(state, dict) or not isinstance(state.get("Status"), str):
            raise InfrastructureError(
                "Docker inspect returned incomplete state for Bot Position "
                + self.bot_position
            )
        self.final_state = state
        return state

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

    def disconnection_fault(
        self, turn: int, default_detail: str
    ) -> dict[str, object]:
        state = self._container_state()
        raw_runtime_error = str(state.get("Error", ""))
        if raw_runtime_error.startswith(SECURITY_EVIDENCE_PREFIX) and len(
            raw_runtime_error
        ) > len(SECURITY_EVIDENCE_PREFIX):
            self.security_evidence = {
                "source": "container_runtime",
                "attributable": True,
                "raw": raw_runtime_error,
            }
            kind = "suspected_security_violation"
        elif state.get("OOMKilled") is True:
            kind = "resource_oom"
        elif raw_runtime_error.startswith(RESOURCE_EVIDENCE_PREFIX):
            resource = raw_runtime_error.removeprefix(RESOURCE_EVIDENCE_PREFIX)
            resource_faults = {
                "pid_exhaustion": "resource_pid_exhaustion",
                "open_file_exhaustion": "resource_open_file_exhaustion",
                "filesystem_exhaustion": "resource_filesystem_exhaustion",
            }
            kind = resource_faults.get(resource, "")
            if not kind:
                raise InfrastructureError(
                    "Container runtime returned unknown attributable resource evidence"
                )
        elif raw_runtime_error:
            raise InfrastructureError(
                "Container runtime reported a non-attributable execution failure"
            )
        else:
            kind = "unexpected_exit"
        return {"kind": kind, "turn": turn, "detail": default_detail}

    def terminate(self) -> None:
        self.stop()

    def stop(self) -> None:
        if self.cleanup_started_ns is None:
            self.cleanup_started_ns = time.monotonic_ns()
            self.cleanup_started_at = _utc_timestamp()
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
            arguments = self._arguments(
                "stop", "--time", "1", self.container_id
            )
            self.docker_commands.append(arguments)
            self.stop_process = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            self.raw_errors.append(str(error))
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
            self.raw_errors.append(diagnostics.strip())
            raise InfrastructureError(
                "Docker stop failed for Bot Position "
                f"{self.bot_position}: {diagnostics.strip()}"
            )

    def finish_stop(self) -> None:
        first_error: Optional[InfrastructureError] = None
        try:
            self._finish_helper(self.terminate_process)
            self._finish_helper(self.attach_process, read_pipes=False)
            if self.container_id is not None:
                try:
                    self._container_state()
                except InfrastructureError as error:
                    first_error = error
                try:
                    self._run(
                        ["rm", "--force", self.container_id],
                        "remove",
                        missing_ok=True,
                    )
                    self.container_id = None
                except InfrastructureError as error:
                    if first_error is None:
                        first_error = error
        finally:
            if self.cleanup_started_ns is not None:
                self.cleanup_duration_ms = _duration_ms(self.cleanup_started_ns)
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
        if first_error is not None:
            raise first_error

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

    def operational_telemetry(self) -> dict[str, object]:
        state = self.final_state or {}
        telemetry = {
            "container_id": self.created_container_id,
            "container_name": self.container_name,
            "match_attempt_identity": self.match_attempt_identity.value,
            "labels": list(self.match_attempt_identity.labels(self.bot_position)),
            "docker_commands": self.docker_commands,
            "engine": self.engine_details,
            "host": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
            "started_at": self.started_at,
            "startup_duration_ms": self.startup_duration_ms,
            "cleanup_started_at": self.cleanup_started_at,
            "cleanup_duration_ms": self.cleanup_duration_ms,
            "readiness_observed": False
            if self.stderr is None
            else self.stderr.ready.is_set(),
            "exit_metadata": {
                "status": state.get("Status"),
                "exit_code": state.get("ExitCode"),
                "oom_killed": state.get("OOMKilled"),
                "error": state.get("Error"),
            },
            "resource_observations": {
                key: value
                for key, value in state.items()
                if key not in {"Status", "ExitCode", "OOMKilled", "Error"}
            },
            "raw_errors": self.raw_errors,
        }
        if self.security_evidence is not None:
            telemetry["security_evidence"] = self.security_evidence
        return telemetry

    def _run(
        self,
        arguments: Sequence[str],
        operation: str,
        *,
        missing_ok: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        command = self._arguments(*arguments)
        self.docker_commands.append(command)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=self.operations.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            self.raw_errors.append(str(error))
            raise InfrastructureError(
                f"Docker {operation} timed out for Bot Position {self.bot_position}"
            ) from error
        except OSError as error:
            self.raw_errors.append(str(error))
            raise InfrastructureError(
                f"Could not run Docker {operation} for Bot Position "
                f"{self.bot_position}: {error}"
            ) from error
        if completed.returncode != 0:
            diagnostics = completed.stderr.decode("utf-8", errors="replace").strip()
            self.raw_errors.append(diagnostics)
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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started_ns: int) -> float:
    return (time.monotonic_ns() - started_ns) / 1_000_000
