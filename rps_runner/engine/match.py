from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import selectors
import time
from typing import Callable, Optional

from rps_runner.engine.bot_process import HostProcessBotSession
from rps_runner.engine.bot_session import (
    BotArtifactDisconnected,
    BotSession,
    BotSessionFactory,
)
from rps_runner.engine.models import InfrastructureError, MatchConfig


MOVES = frozenset({"R", "P", "S"})
WINNING_MATCHUPS = {("R", "S"), ("S", "P"), ("P", "R")}


def _history_line(history: str) -> str:
    return history if history else "-"


def _request(turn: int, own_history: str, opponent_history: str) -> bytes:
    return (
        f"{turn}\n{_history_line(own_history)}\n"
        f"{_history_line(opponent_history)}\n"
    ).encode("utf-8")


def _round_winner(move_a: str, move_b: str) -> str:
    if move_a == move_b:
        return "draw"
    return "a" if (move_a, move_b) in WINNING_MATCHUPS else "b"


def _fault(kind: str, turn: int, detail: str) -> dict[str, object]:
    return {"kind": kind, "turn": turn, "detail": detail}


def _bot_result(session: BotSession) -> dict[str, object]:
    return {
        "command": session.artifact_reference,
        "stderr": session.stderr_text(),
        "stderr_truncated": session.stderr_truncated,
    }


def _start_sessions(
    config: MatchConfig, session_factory: BotSessionFactory
) -> list[BotSession]:
    artifact_references = {"a": config.bot_a, "b": config.bot_b}
    sessions = [
        session_factory(bot_position, artifact_references[bot_position], config)
        for bot_position in ("a", "b")
    ]
    try:
        _run_session_phase(sessions, lambda session: session.start())
    except InfrastructureError:
        _stop_sessions(sessions)
        raise
    return sessions


def _run_session_phase(
    sessions: list[BotSession], operation: Callable[[BotSession], None]
) -> None:
    first_error: Optional[InfrastructureError] = None
    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures = [
            executor.submit(operation, session) for session in sessions
        ]
        for future in futures:
            try:
                future.result()
            except InfrastructureError as error:
                if first_error is None:
                    first_error = error
    if first_error is not None:
        raise first_error


def _stop_sessions(sessions: list[BotSession]) -> None:
    cleanup_error: Optional[InfrastructureError] = None
    operations: tuple[Callable[[BotSession], None], ...] = (
        lambda session: session.stop(),
        lambda session: session.force_stop(),
        lambda session: session.finish_stop(),
    )
    for operation in operations:
        try:
            _run_session_phase(sessions, operation)
        except InfrastructureError as error:
            if cleanup_error is None:
                cleanup_error = error
    if cleanup_error is not None:
        raise cleanup_error


@dataclass
class _ResponseReader:
    sessions: dict[str, BotSession]
    output_buffers: dict[str, bytearray]
    total_response_ns: dict[str, int]
    stdout_limit_bytes: int
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
            self._register_sessions(selector)
            while self.pending:
                self._expire_timeouts(selector)
                if self.pending:
                    self._read_ready_sessions(selector)
        finally:
            selector.close()

        return self.responses, self.faults, self.response_times_ns

    def _register_sessions(self, selector: selectors.BaseSelector) -> None:
        for bot_position, session in self.sessions.items():
            if self.output_buffers[bot_position]:
                self.faults[bot_position] = _fault(
                    "unexpected_output",
                    self.turn,
                    "Bot wrote output before receiving this turn's request",
                )
                continue

            remaining_budget = (
                self.total_budget_ns
                - self.total_response_ns[bot_position]
            )
            self.deadlines[bot_position] = self.sent_ns + min(
                self.timeout_ns, max(0, remaining_budget)
            )
            selector.register(
                session.output_descriptor,
                selectors.EVENT_READ,
                bot_position,
            )
            self.pending.add(bot_position)

    def _expire_timeouts(self, selector: selectors.BaseSelector) -> None:
        now_ns = time.monotonic_ns()
        expired = [
            bot_position
            for bot_position in self.pending
            if now_ns >= self.deadlines[bot_position]
        ]
        for bot_position in expired:
            self._record_fault(
                selector,
                bot_position,
                "timeout",
                "Bot exceeded its response-time limit",
                terminate=True,
            )

    def _read_ready_sessions(
        self, selector: selectors.BaseSelector
    ) -> None:
        nearest_deadline = min(
            self.deadlines[bot_position]
            for bot_position in self.pending
        )
        wait_seconds = max(
            0, nearest_deadline - time.monotonic_ns()
        ) / 1_000_000_000
        for key, _ in selector.select(wait_seconds):
            bot_position = key.data
            if bot_position in self.pending:
                self._read_session(selector, bot_position)

    def _read_session(
        self, selector: selectors.BaseSelector, bot_position: str
    ) -> None:
        chunk = self.sessions[bot_position].read_output(
            self.stdout_limit_bytes + 1
        )
        if not chunk:
            self._record_fault(
                selector,
                bot_position,
                "unexpected_exit",
                "Bot closed stdout before returning a move",
            )
            return

        output_buffer = self.output_buffers[bot_position]
        output_buffer.extend(chunk)
        if len(output_buffer) > self.stdout_limit_bytes:
            self._record_fault(
                selector,
                bot_position,
                "excessive_output",
                "Bot response exceeded the stdout limit",
                terminate=True,
            )
            return
        if b"\n" in output_buffer:
            self._process_line(selector, bot_position)

    def _process_line(
        self, selector: selectors.BaseSelector, bot_position: str
    ) -> None:
        response_bytes, remainder = self.output_buffers[bot_position].split(
            b"\n", 1
        )
        self.output_buffers[bot_position] = bytearray(remainder)
        self._record_response_time(bot_position)
        self._complete(selector, bot_position)

        if remainder:
            self._record_fault(
                selector,
                bot_position,
                "unexpected_output",
                "Bot returned more than one line for a request",
                terminate=True,
            )
            return

        response = self._decode_response(
            selector, bot_position, response_bytes
        )
        if response is None:
            return
        if response not in MOVES:
            self._record_fault(
                selector,
                bot_position,
                "invalid_response",
                f"Expected exactly R, P, or S; received {response!r}",
                terminate=True,
            )
            return
        self.responses[bot_position] = response

    def _decode_response(
        self,
        selector: selectors.BaseSelector,
        bot_position: str,
        response_bytes: bytes,
    ) -> Optional[str]:
        try:
            return response_bytes.decode("utf-8")
        except UnicodeDecodeError:
            self._record_fault(
                selector,
                bot_position,
                "invalid_response",
                "Bot response was not valid UTF-8",
                terminate=True,
            )
            return None

    def _record_response_time(self, bot_position: str) -> None:
        response_time_ns = time.monotonic_ns() - self.sent_ns
        self.response_times_ns[bot_position] = response_time_ns
        self.total_response_ns[bot_position] += response_time_ns

    def _record_fault(
        self,
        selector: selectors.BaseSelector,
        bot_position: str,
        kind: str,
        detail: str,
        *,
        terminate: bool = False,
    ) -> None:
        self.faults[bot_position] = _fault(kind, self.turn, detail)
        self._complete(selector, bot_position)
        if terminate:
            self.sessions[bot_position].terminate()

    def _complete(
        self, selector: selectors.BaseSelector, bot_position: str
    ) -> None:
        self.pending.discard(bot_position)
        try:
            selector.unregister(
                self.sessions[bot_position].output_descriptor
            )
        except KeyError:
            pass


class _MatchRunner:
    def __init__(self, config: MatchConfig, sessions: list[BotSession]) -> None:
        self.config = config
        self.sessions_by_position = {
            session.bot_position: session for session in sessions
        }
        self.output_buffers = {"a": bytearray(), "b": bytearray()}
        self.total_response_ns = {"a": 0, "b": 0}
        self.moves = {"a": "", "b": ""}
        self.score = {"a": 0, "b": 0, "draws": 0}
        self.played_rounds: list[dict[str, object]] = []
        self.faults: dict[str, Optional[dict[str, object]]] = {
            "a": None,
            "b": None,
        }

    def play(self) -> None:
        for turn in range(self.config.rounds):
            if not self._play_turn(turn):
                return

    def _play_turn(self, turn: int) -> bool:
        before_request_faults = self._pre_request_faults(turn)
        if before_request_faults:
            return self._stop_for_faults(before_request_faults)

        requests = self._requests(turn)
        send_faults = self._send_requests(turn, requests)
        sent_ns = time.monotonic_ns()
        responses, response_faults, response_times_ns = _ResponseReader(
            self._waiting_sessions(send_faults),
            self.output_buffers,
            self.total_response_ns,
            self.config.stdout_limit_bytes,
            turn,
            sent_ns,
            self._timeout_ns(turn),
            self.config.total_timeout_ms * 1_000_000,
        ).read()

        turn_faults = send_faults | response_faults
        if turn_faults:
            return self._stop_for_faults(turn_faults)

        self._record_round(turn, responses, response_times_ns)
        return True

    def _pre_request_faults(
        self, turn: int
    ) -> dict[str, dict[str, object]]:
        faults: dict[str, dict[str, object]] = {}
        selector = selectors.DefaultSelector()
        try:
            for bot_position, session in self.sessions_by_position.items():
                selector.register(
                    session.output_descriptor,
                    selectors.EVENT_READ,
                    bot_position,
                )

            for key, _ in selector.select(0):
                bot_position = key.data
                output = self.sessions_by_position[
                    bot_position
                ].read_output(self.config.stdout_limit_bytes + 1)
                if output:
                    faults[bot_position] = _fault(
                        "unexpected_output",
                        turn,
                        "Bot wrote output before receiving this turn's request",
                    )
                else:
                    faults[bot_position] = _fault(
                        "unexpected_exit",
                        turn,
                        "Bot closed stdout before receiving this turn's request",
                    )
                self.sessions_by_position[bot_position].terminate()
        finally:
            selector.close()
        return faults

    def _requests(self, turn: int) -> dict[str, bytes]:
        return {
            "a": _request(turn, self.moves["a"], self.moves["b"]),
            "b": _request(turn, self.moves["b"], self.moves["a"]),
        }

    def _send_requests(
        self, turn: int, requests: dict[str, bytes]
    ) -> dict[str, dict[str, object]]:
        send_faults: dict[str, dict[str, object]] = {}
        for bot_position in ("a", "b"):
            try:
                self.sessions_by_position[bot_position].send(
                    requests[bot_position]
                )
            except BotArtifactDisconnected:
                send_faults[bot_position] = _fault(
                    "unexpected_exit",
                    turn,
                    "Bot exited or closed stdin before receiving the request",
                )
        return send_faults

    def _waiting_sessions(
        self, send_faults: dict[str, dict[str, object]]
    ) -> dict[str, BotSession]:
        return {
            bot_position: session
            for bot_position, session in self.sessions_by_position.items()
            if bot_position not in send_faults
        }

    def _timeout_ns(self, turn: int) -> int:
        timeout_ms = (
            self.config.first_move_timeout_ms
            if turn == 0
            else self.config.move_timeout_ms
        )
        return timeout_ms * 1_000_000

    def _stop_for_faults(
        self, turn_faults: dict[str, dict[str, object]]
    ) -> bool:
        self.faults.update(turn_faults)
        return False

    def _record_round(
        self,
        turn: int,
        responses: dict[str, str],
        response_times_ns: dict[str, int],
    ) -> None:
        move_a = responses["a"]
        move_b = responses["b"]
        winner = _round_winner(move_a, move_b)
        self.moves["a"] += move_a
        self.moves["b"] += move_b
        self.score["draws" if winner == "draw" else winner] += 1
        self.played_rounds.append(
            {
                "turn": turn,
                "a": move_a,
                "b": move_b,
                "winner": winner,
                "response_time_ns": response_times_ns,
            }
        )

    def result(self) -> dict[str, object]:
        status, winner = self._outcome()
        return {
            "protocol_version": 1,
            "scheduled_rounds": self.config.rounds,
            "seed": self.config.seed,
            "status": status,
            "winner": winner,
            "score": self.score,
            "completed_rounds": len(self.played_rounds),
            "moves": self.moves,
            "rounds": self.played_rounds,
            "faults": self.faults,
            "timing": {
                "clock": "monotonic",
                "total_response_ns": self.total_response_ns,
            },
            "bots": {
                "a": _bot_result(self.sessions_by_position["a"]),
                "b": _bot_result(self.sessions_by_position["b"]),
            },
        }

    def _outcome(self) -> tuple[str, Optional[str]]:
        faulted = [
            bot_position
            for bot_position, bot_fault in self.faults.items()
            if bot_fault is not None
        ]
        if len(faulted) == 2:
            return "double_forfeit", None
        if len(faulted) == 1:
            winner = "b" if faulted[0] == "a" else "a"
            return "forfeit", winner
        if self.score["a"] == self.score["b"]:
            return "completed", "draw"
        winner = "a" if self.score["a"] > self.score["b"] else "b"
        return "completed", winner


def run_match(
    config: MatchConfig,
    *,
    session_factory: BotSessionFactory = HostProcessBotSession,
) -> dict[str, object]:
    sessions = _start_sessions(config, session_factory)
    runner = _MatchRunner(config, sessions)

    try:
        runner.play()
    except OSError as error:
        raise InfrastructureError(f"Match runner failed: {error}") from error
    finally:
        _stop_sessions(sessions)

    return runner.result()
