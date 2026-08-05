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

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("RPS_")
    }
    environment.update(
        {
            "RPS_PROTOCOL_VERSION": "1",
            "RPS_ROUNDS": str(config.rounds),
            "RPS_SEED": str(config.seed_for_bot_position(label)),
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
    _close_bot_inputs(bots)
    _signal_running_bots(bots, signal.SIGTERM)
    _wait_for_bots_until(
        bots, time.monotonic_ns() + TERMINATION_GRACE_NS
    )
    _signal_running_bots(bots, signal.SIGKILL)
    _reap_bots(bots)


def _close_bot_inputs(bots: list[BotProcess]) -> None:
    for bot in bots:
        process_input = bot.process.stdin
        if process_input is None:
            continue
        try:
            process_input.close()
        except OSError:
            pass


def _signal_running_bots(
    bots: list[BotProcess], requested_signal: signal.Signals
) -> None:
    for bot in bots:
        if bot.process.poll() is None:
            signal_bot(bot, requested_signal)


def _wait_for_bots_until(
    bots: list[BotProcess], deadline_ns: int
) -> None:
    for bot in bots:
        remaining = max(0, deadline_ns - time.monotonic_ns()) / 1_000_000_000
        try:
            bot.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass


def _reap_bots(bots: list[BotProcess]) -> None:
    for bot in bots:
        try:
            bot.process.wait(timeout=FINAL_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        bot.stderr.finish()
        for stream in (bot.process.stdout, bot.process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except OSError:
                pass


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


@dataclass
class _ResponseReader:
    bots: dict[str, BotProcess]
    turn: int
    sent_ns: int
    timeout_ns: int
    total_budget_ns: int
    responses: dict[str, str] = field(default_factory=dict)
    faults: dict[str, dict[str, object]] = field(default_factory=dict)
    response_times_ns: dict[str, int] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    deadlines: dict[str, int] = field(default_factory=dict)

    def read(self) -> tuple[
        dict[str, str], dict[str, dict[str, object]], dict[str, int]
    ]:
        selector = selectors.DefaultSelector()
        try:
            self._register_bots(selector)
            while self.pending:
                self._expire_timeouts(selector)
                if self.pending:
                    self._read_ready_streams(selector)
        finally:
            selector.close()

        return self.responses, self.faults, self.response_times_ns

    def _register_bots(self, selector: selectors.BaseSelector) -> None:
        for label, bot in self.bots.items():
            if bot.stdout_buffer:
                self.faults[label] = fault(
                    "unexpected_output",
                    self.turn,
                    "Bot wrote output before receiving this turn's request",
                )
                continue

            remaining_budget = self.total_budget_ns - bot.total_response_ns
            self.deadlines[label] = self.sent_ns + min(
                self.timeout_ns, max(0, remaining_budget)
            )
            assert bot.process.stdout is not None
            os.set_blocking(bot.process.stdout.fileno(), False)
            selector.register(bot.process.stdout, selectors.EVENT_READ, label)
            self.pending.add(label)

    def _expire_timeouts(self, selector: selectors.BaseSelector) -> None:
        now_ns = time.monotonic_ns()
        expired = [
            label
            for label in self.pending
            if now_ns >= self.deadlines[label]
        ]
        for label in expired:
            self._record_fault(
                selector,
                label,
                "timeout",
                "Bot exceeded its response-time limit",
                terminate=True,
            )

    def _read_ready_streams(self, selector: selectors.BaseSelector) -> None:
        nearest_deadline = min(
            self.deadlines[label] for label in self.pending
        )
        wait_seconds = max(
            0, nearest_deadline - time.monotonic_ns()
        ) / 1_000_000_000
        for key, _ in selector.select(wait_seconds):
            label = key.data
            if label in self.pending:
                self._read_stream(selector, key, label)

    def _read_stream(
        self,
        selector: selectors.BaseSelector,
        key: selectors.SelectorKey,
        label: str,
    ) -> None:
        try:
            chunk = os.read(key.fd, MAX_STDOUT_RESPONSE_BYTES + 1)
        except BlockingIOError:
            return

        if not chunk:
            self._record_fault(
                selector,
                label,
                "unexpected_exit",
                "Bot closed stdout before returning a move",
            )
            return

        bot = self.bots[label]
        bot.stdout_buffer.extend(chunk)
        if len(bot.stdout_buffer) > MAX_STDOUT_RESPONSE_BYTES:
            self._record_fault(
                selector,
                label,
                "excessive_output",
                "Bot response exceeded the stdout limit",
                terminate=True,
            )
            return
        if b"\n" in bot.stdout_buffer:
            self._process_line(selector, label)

    def _process_line(
        self, selector: selectors.BaseSelector, label: str
    ) -> None:
        bot = self.bots[label]
        response_bytes, remainder = bot.stdout_buffer.split(b"\n", 1)
        bot.stdout_buffer = bytearray(remainder)
        self._record_response_time(label)
        self._complete(selector, label)

        if remainder:
            self._record_fault(
                selector,
                label,
                "unexpected_output",
                "Bot returned more than one line for a request",
                terminate=True,
            )
            return

        response = self._decode_response(selector, label, response_bytes)
        if response is None:
            return
        if response not in MOVES:
            self._record_fault(
                selector,
                label,
                "invalid_response",
                f"Expected exactly R, P, or S; received {response!r}",
                terminate=True,
            )
            return
        self.responses[label] = response

    def _decode_response(
        self,
        selector: selectors.BaseSelector,
        label: str,
        response_bytes: bytes,
    ) -> Optional[str]:
        try:
            return response_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self._record_fault(
                selector,
                label,
                "invalid_response",
                "Bot response was not valid UTF-8",
                terminate=True,
            )
            return None

    def _record_response_time(self, label: str) -> None:
        response_time_ns = time.monotonic_ns() - self.sent_ns
        self.response_times_ns[label] = response_time_ns
        self.bots[label].total_response_ns += response_time_ns

    def _record_fault(
        self,
        selector: selectors.BaseSelector,
        label: str,
        kind: str,
        detail: str,
        *,
        terminate: bool = False,
    ) -> None:
        self.faults[label] = fault(kind, self.turn, detail)
        self._complete(selector, label)
        if terminate:
            signal_bot(self.bots[label], signal.SIGTERM)

    def _complete(
        self, selector: selectors.BaseSelector, label: str
    ) -> None:
        self.pending.discard(label)
        stream = self.bots[label].process.stdout
        if stream is None:
            return
        try:
            selector.unregister(stream)
        except KeyError:
            pass


def read_responses(
    bots: dict[str, BotProcess],
    turn: int,
    sent_ns: int,
    timeout_ns: int,
    total_budget_ns: int,
) -> tuple[
    dict[str, str], dict[str, dict[str, object]], dict[str, int]
]:
    return _ResponseReader(
        bots, turn, sent_ns, timeout_ns, total_budget_ns
    ).read()
