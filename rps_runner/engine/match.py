from __future__ import annotations

import signal
import time
from typing import Optional

from rps_runner.engine.bot_process import (
    BotProcess,
    fault,
    pre_request_faults,
    read_responses,
    signal_bot,
    start_bot,
    stop_bots,
)
from rps_runner.engine.models import InfrastructureError, MatchConfig


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


def _bot_result(bot: BotProcess) -> dict[str, object]:
    return {
        "command": bot.command,
        "stderr": bot.stderr.text(),
        "stderr_truncated": bot.stderr.truncated,
    }


def _start_bots(config: MatchConfig) -> list[BotProcess]:
    bots: list[BotProcess] = []
    try:
        bots.append(start_bot("a", config.bot_a, config))
        bots.append(start_bot("b", config.bot_b, config))
    except InfrastructureError:
        stop_bots(bots)
        raise
    return bots


class _MatchRunner:
    def __init__(self, config: MatchConfig, bots: list[BotProcess]) -> None:
        self.config = config
        self.bots_by_label = {bot.label: bot for bot in bots}
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
        before_request_faults = pre_request_faults(
            self.bots_by_label, turn
        )
        if before_request_faults:
            return self._stop_for_faults(before_request_faults)

        requests = self._requests(turn)
        send_faults = self._send_requests(turn, requests)
        sent_ns = time.monotonic_ns()
        responses, response_faults, response_times_ns = read_responses(
            self._waiting_bots(send_faults),
            turn,
            sent_ns,
            self._timeout_ns(turn),
            self.config.total_timeout_ms * 1_000_000,
        )

        turn_faults = send_faults | response_faults
        if turn_faults:
            return self._stop_for_faults(turn_faults)

        self._record_round(turn, responses, response_times_ns)
        return True

    def _requests(self, turn: int) -> dict[str, bytes]:
        return {
            "a": _request(turn, self.moves["a"], self.moves["b"]),
            "b": _request(turn, self.moves["b"], self.moves["a"]),
        }

    def _send_requests(
        self, turn: int, requests: dict[str, bytes]
    ) -> dict[str, dict[str, object]]:
        send_faults: dict[str, dict[str, object]] = {}
        for label in ("a", "b"):
            bot_fault = self._send_request(label, turn, requests[label])
            if bot_fault is not None:
                send_faults[label] = bot_fault
        return send_faults

    def _send_request(
        self, label: str, turn: int, request: bytes
    ) -> Optional[dict[str, object]]:
        bot = self.bots_by_label[label]
        process_input = bot.process.stdin
        assert process_input is not None
        try:
            process_input.write(request)
            process_input.flush()
            return None
        except (BrokenPipeError, OSError):
            signal_bot(bot, signal.SIGTERM)
            return fault(
                "unexpected_exit",
                turn,
                "Bot exited or closed stdin before receiving the request",
            )

    def _waiting_bots(
        self, send_faults: dict[str, dict[str, object]]
    ) -> dict[str, BotProcess]:
        return {
            label: bot
            for label, bot in self.bots_by_label.items()
            if label not in send_faults
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
                "total_response_ns": {
                    label: bot.total_response_ns
                    for label, bot in self.bots_by_label.items()
                },
            },
            "bots": {
                "a": _bot_result(self.bots_by_label["a"]),
                "b": _bot_result(self.bots_by_label["b"]),
            },
        }

    def _outcome(self) -> tuple[str, Optional[str]]:
        faulted = [
            label
            for label, bot_fault in self.faults.items()
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


def run_match(config: MatchConfig) -> dict[str, object]:
    bots = _start_bots(config)
    runner = _MatchRunner(config, bots)

    try:
        runner.play()
    except OSError as error:
        raise InfrastructureError(f"Match runner failed: {error}") from error
    finally:
        stop_bots(bots)

    return runner.result()
