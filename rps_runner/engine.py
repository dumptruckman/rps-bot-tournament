from __future__ import annotations

from dataclasses import dataclass, field
import os
import selectors
import shlex
import signal
import subprocess
import threading
import time
from typing import BinaryIO


MOVES = frozenset({"R", "P", "S"})
WINNING_MATCHUPS = {("R", "S"), ("S", "P"), ("P", "R")}
MAX_STDOUT_RESPONSE_BYTES = 4096


class InfrastructureError(RuntimeError):
    """The runner could not create or operate the match infrastructure."""


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


@dataclass
class StderrCapture:
    stream: BinaryIO
    limit: int
    captured: bytearray = field(default_factory=bytearray)
    truncated: bool = False
    thread: threading.Thread | None = None

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


def _start_bot(label: str, command: str, config: MatchConfig) -> BotProcess:
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
    capture = StderrCapture(process.stderr, config.stderr_limit_bytes)
    capture.start()
    return BotProcess(label, command, process, capture)


def _stop_bots(bots: list[BotProcess]) -> None:
    for bot in bots:
        if bot.process.stdin is not None:
            try:
                bot.process.stdin.close()
            except OSError:
                pass

    for bot in bots:
        if bot.process.poll() is None:
            _signal_bot(bot, signal.SIGTERM)

    deadline_ns = time.monotonic_ns() + 200_000_000
    for bot in bots:
        remaining = max(0, deadline_ns - time.monotonic_ns()) / 1_000_000_000
        try:
            bot.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            pass

    for bot in bots:
        if bot.process.poll() is None:
            _signal_bot(bot, signal.SIGKILL)

    for bot in bots:
        try:
            bot.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        bot.stderr.finish()


def _signal_bot(bot: BotProcess, requested_signal: signal.Signals) -> None:
    try:
        os.killpg(bot.process.pid, requested_signal)
    except OSError:
        try:
            bot.process.send_signal(requested_signal)
        except OSError:
            pass


def _pre_request_faults(
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
                faults[label] = _fault(
                    "unexpected_output",
                    turn,
                    "Bot wrote output before receiving this turn's request",
                )
            else:
                faults[label] = _fault(
                    "unexpected_exit",
                    turn,
                    "Bot closed stdout before receiving this turn's request",
                )
            _signal_bot(bot, signal.SIGTERM)
    finally:
        selector.close()
    return faults


def _history_line(history: str) -> str:
    return history if history else "-"


def _request(turn: int, own_history: str, opponent_history: str) -> bytes:
    return (
        f"{turn}\n{_history_line(own_history)}\n"
        f"{_history_line(opponent_history)}\n"
    ).encode("utf-8")


def _fault(kind: str, turn: int, detail: str) -> dict[str, object]:
    return {"kind": kind, "turn": turn, "detail": detail}


def _read_responses(
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
                faults[label] = _fault(
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
                    faults[label] = _fault(
                        "timeout", turn, "Bot exceeded its response-time limit"
                    )
                    _signal_bot(bots[label], signal.SIGTERM)
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
                    faults[label] = _fault(
                        "unexpected_exit",
                        turn,
                        "Bot closed stdout before returning a move",
                    )
                    pending.remove(label)
                    selector.unregister(key.fileobj)
                    continue

                bot.stdout_buffer.extend(chunk)
                if len(bot.stdout_buffer) > MAX_STDOUT_RESPONSE_BYTES:
                    faults[label] = _fault(
                        "excessive_output",
                        turn,
                        "Bot response exceeded the stdout limit",
                    )
                    _signal_bot(bot, signal.SIGTERM)
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
                    faults[label] = _fault(
                        "unexpected_output",
                        turn,
                        "Bot returned more than one line for a request",
                    )
                    _signal_bot(bot, signal.SIGTERM)
                    continue
                try:
                    response = response_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    faults[label] = _fault(
                        "invalid_response", turn, "Bot response was not valid UTF-8"
                    )
                    _signal_bot(bot, signal.SIGTERM)
                    continue
                if response not in MOVES:
                    faults[label] = _fault(
                        "invalid_response",
                        turn,
                        f"Expected exactly R, P, or S; received {response!r}",
                    )
                    _signal_bot(bot, signal.SIGTERM)
                    continue
                responses[label] = response
    finally:
        selector.close()

    return responses, faults, response_times_ns


def _round_winner(move_a: str, move_b: str) -> str:
    if move_a == move_b:
        return "draw"
    return "a" if (move_a, move_b) in WINNING_MATCHUPS else "b"


def _bot_result(bot: BotProcess) -> dict[str, object]:
    return {
        "command": bot.command,
        "stderr": bot.stderr.text(),
        "stderr_truncated": bot.stderr.truncated,
    }


def run_match(config: MatchConfig) -> dict[str, object]:
    bots: list[BotProcess] = []
    try:
        bots.append(_start_bot("a", config.bot_a, config))
        bots.append(_start_bot("b", config.bot_b, config))
    except InfrastructureError:
        _stop_bots(bots)
        raise

    bots_by_label = {bot.label: bot for bot in bots}
    moves = {"a": "", "b": ""}
    score = {"a": 0, "b": 0, "draws": 0}
    played_rounds: list[dict[str, object]] = []
    faults: dict[str, dict[str, object] | None] = {"a": None, "b": None}

    try:
        for turn in range(config.rounds):
            before_request_faults = _pre_request_faults(bots_by_label, turn)
            if before_request_faults:
                for label, fault in before_request_faults.items():
                    faults[label] = fault
                break

            requests = {
                "a": _request(turn, moves["a"], moves["b"]),
                "b": _request(turn, moves["b"], moves["a"]),
            }
            send_faults: dict[str, dict[str, object]] = {}
            for label in ("a", "b"):
                process_input = bots_by_label[label].process.stdin
                assert process_input is not None
                try:
                    process_input.write(requests[label])
                    process_input.flush()
                except (BrokenPipeError, OSError):
                    send_faults[label] = _fault(
                        "unexpected_exit",
                        turn,
                        "Bot exited or closed stdin before receiving the request",
                    )
                    _signal_bot(bots_by_label[label], signal.SIGTERM)

            sent_ns = time.monotonic_ns()
            waiting_bots = {
                label: bot
                for label, bot in bots_by_label.items()
                if label not in send_faults
            }
            timeout_ms = (
                config.first_move_timeout_ms
                if turn == 0
                else config.move_timeout_ms
            )
            responses, response_faults, response_times_ns = _read_responses(
                waiting_bots,
                turn,
                sent_ns,
                timeout_ms * 1_000_000,
                config.total_timeout_ms * 1_000_000,
            )
            turn_faults = send_faults | response_faults
            if turn_faults:
                for label, fault in turn_faults.items():
                    faults[label] = fault
                break

            move_a = responses["a"]
            move_b = responses["b"]
            winner = _round_winner(move_a, move_b)
            moves["a"] += move_a
            moves["b"] += move_b
            score["draws" if winner == "draw" else winner] += 1
            played_rounds.append(
                {
                    "turn": turn,
                    "a": move_a,
                    "b": move_b,
                    "winner": winner,
                    "response_time_ns": response_times_ns,
                }
            )
    except OSError as error:
        raise InfrastructureError(f"Match runner failed: {error}") from error
    finally:
        _stop_bots(bots)

    faulted = [label for label, fault in faults.items() if fault is not None]
    if len(faulted) == 2:
        status = "double_forfeit"
        winner: str | None = None
    elif len(faulted) == 1:
        status = "forfeit"
        winner = "b" if faulted[0] == "a" else "a"
    else:
        status = "completed"
        if score["a"] == score["b"]:
            winner = "draw"
        else:
            winner = "a" if score["a"] > score["b"] else "b"

    return {
        "protocol_version": 1,
        "scheduled_rounds": config.rounds,
        "seed": config.seed,
        "status": status,
        "winner": winner,
        "score": score,
        "completed_rounds": len(played_rounds),
        "moves": moves,
        "rounds": played_rounds,
        "faults": faults,
        "timing": {
            "clock": "monotonic",
            "total_response_ns": {
                label: bot.total_response_ns
                for label, bot in bots_by_label.items()
            },
        },
        "bots": {
            "a": _bot_result(bots_by_label["a"]),
            "b": _bot_result(bots_by_label["b"]),
        },
    }
