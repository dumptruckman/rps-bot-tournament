from __future__ import annotations

from dataclasses import dataclass, field
import os
import selectors
import shlex
import signal
import subprocess
import threading
import time
from typing import BinaryIO, Optional, cast

from rps_runner.engine.models import InfrastructureError, MatchConfig


MOVES = frozenset({"R", "P", "S"})
MAX_STDOUT_RESPONSE_BYTES = 4096


@dataclass
class StderrCapture:
    stream: BinaryIO
    limit: int
    captured: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._drain, daemon=True)
        self.thread.start()

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
class BotProcess:
    label: str
    command: str
    process: subprocess.Popen[bytes]
    stderr: StderrCapture
    stdout_buffer: bytearray = field(default_factory=bytearray)
    total_response_ns: int = 0


def start_bot(label: str, command: str, config: MatchConfig) -> BotProcess:
    try:
        arguments = shlex.split(command)
    except ValueError as error:
        raise InfrastructureError(
            f"Could not parse bot {label} command: {error}"
        ) from error
    if not arguments:
        raise InfrastructureError(f"Could not start bot {label}: command is empty")

    environment = os.environ.copy()
    environment.update(
        {
            "RPS_PROTOCOL_VERSION": "1",
            "RPS_ROUNDS": str(config.rounds),
            "RPS_SEED": str(config.seed),
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
            f"Could not start bot {label} ({command!r}): {error}"
        ) from error

    assert process.stderr is not None
    capture = StderrCapture(
        cast(BinaryIO, process.stderr), config.stderr_limit_bytes
    )
    capture.start()
    return BotProcess(label, command, process, capture)


def stop_bots(bots: list[BotProcess]) -> None:
    for bot in bots:
        if bot.process.stdin is not None:
            try:
                bot.process.stdin.close()
            except OSError:
                pass

    for bot in bots:
        if bot.process.poll() is None:
            signal_bot(bot, signal.SIGTERM)

    deadline_ns = time.monotonic_ns() + 200_000_000
    for bot in bots:
        remaining = max(0, deadline_ns - time.monotonic_ns()) / 1_000_000_000
        try:
            bot.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass

    for bot in bots:
        if bot.process.poll() is None:
            signal_bot(bot, signal.SIGKILL)

    for bot in bots:
        try:
            bot.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        bot.stderr.finish()


def signal_bot(bot: BotProcess, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(bot.process.pid, requested_signal)
    except OSError:
        try:
            bot.process.send_signal(requested_signal)
        except OSError:
            pass


def fault(kind: str, turn: int, detail: str) -> dict[str, object]:
    return {"kind": kind, "turn": turn, "detail": detail}


def pre_request_faults(
    bots: dict[str, BotProcess], turn: int
) -> dict[str, dict[str, object]]:
    faults: dict[str, dict[str, object]] = {}
    selector = selectors.DefaultSelector()
    try:
        for label, bot in bots.items():
            assert bot.process.stdout is not None
            os.set_blocking(bot.process.stdout.fileno(), False)
            selector.register(bot.process.stdout, selectors.EVENT_READ, label)

        for key, _ in selector.select(0):
            label = key.data
            bot = bots[label]
            try:
                output = os.read(key.fd, MAX_STDOUT_RESPONSE_BYTES + 1)
            except BlockingIOError:
                continue
            if output:
                faults[label] = fault(
                    "unexpected_output",
                    turn,
                    "Bot wrote output before receiving this turn's request",
                )
            else:
                faults[label] = fault(
                    "unexpected_exit",
                    turn,
                    "Bot closed stdout before receiving this turn's request",
                )
            signal_bot(bot, signal.SIGTERM)
    finally:
        selector.close()
    return faults


def read_responses(
    bots: dict[str, BotProcess],
    turn: int,
    sent_ns: int,
    timeout_ns: int,
    total_budget_ns: int,
) -> tuple[
    dict[str, str], dict[str, dict[str, object]], dict[str, int]
]:
    responses: dict[str, str] = {}
    faults: dict[str, dict[str, object]] = {}
    response_times_ns: dict[str, int] = {}
    pending = set(bots)
    deadlines: dict[str, int] = {}
    selector = selectors.DefaultSelector()

    try:
        for label, bot in bots.items():
            if bot.stdout_buffer:
                faults[label] = fault(
                    "unexpected_output",
                    turn,
                    "Bot wrote output before receiving this turn's request",
                )
                pending.remove(label)
                continue

            remaining_budget = total_budget_ns - bot.total_response_ns
            deadlines[label] = sent_ns + min(timeout_ns, max(0, remaining_budget))
            assert bot.process.stdout is not None
            os.set_blocking(bot.process.stdout.fileno(), False)
            selector.register(bot.process.stdout, selectors.EVENT_READ, label)

        while pending:
            now_ns = time.monotonic_ns()
            for label in list(pending):
                if now_ns >= deadlines[label]:
                    faults[label] = fault(
                        "timeout", turn, "Bot exceeded its response-time limit"
                    )
                    signal_bot(bots[label], signal.SIGTERM)
                    pending.remove(label)
                    stream = bots[label].process.stdout
                    if stream is not None:
                        try:
                            selector.unregister(stream)
                        except KeyError:
                            pass

            if not pending:
                break

            nearest_deadline = min(deadlines[label] for label in pending)
            wait_seconds = max(
                0, nearest_deadline - time.monotonic_ns()
            ) / 1_000_000_000
            for key, _ in selector.select(wait_seconds):
                label = key.data
                if label not in pending:
                    continue
                bot = bots[label]
                try:
                    chunk = os.read(key.fd, MAX_STDOUT_RESPONSE_BYTES + 1)
                except BlockingIOError:
                    continue
                if not chunk:
                    faults[label] = fault(
                        "unexpected_exit",
                        turn,
                        "Bot closed stdout before returning a move",
                    )
                    pending.remove(label)
                    selector.unregister(key.fileobj)
                    continue

                bot.stdout_buffer.extend(chunk)
                if len(bot.stdout_buffer) > MAX_STDOUT_RESPONSE_BYTES:
                    faults[label] = fault(
                        "excessive_output",
                        turn,
                        "Bot response exceeded the stdout limit",
                    )
                    signal_bot(bot, signal.SIGTERM)
                    pending.remove(label)
                    selector.unregister(key.fileobj)
                    continue
                if b"\n" not in bot.stdout_buffer:
                    continue

                response_bytes, remainder = bot.stdout_buffer.split(b"\n", 1)
                bot.stdout_buffer = bytearray(remainder)
                response_ns = time.monotonic_ns()
                response_time_ns = response_ns - sent_ns
                response_times_ns[label] = response_time_ns
                bot.total_response_ns += response_time_ns
                pending.remove(label)
                selector.unregister(key.fileobj)

                if remainder:
                    faults[label] = fault(
                        "unexpected_output",
                        turn,
                        "Bot returned more than one line for a request",
                    )
                    signal_bot(bot, signal.SIGTERM)
                    continue
                try:
                    response = response_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    faults[label] = fault(
                        "invalid_response", turn, "Bot response was not valid UTF-8"
                    )
                    signal_bot(bot, signal.SIGTERM)
                    continue
                if response not in MOVES:
                    faults[label] = fault(
                        "invalid_response",
                        turn,
                        f"Expected exactly R, P, or S; received {response!r}",
                    )
                    signal_bot(bot, signal.SIGTERM)
                    continue
                responses[label] = response
    finally:
        selector.close()

    return responses, faults, response_times_ns
