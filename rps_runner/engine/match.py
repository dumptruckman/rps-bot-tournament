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


def run_match(config: MatchConfig) -> dict[str, object]:
    bots: list[BotProcess] = []
    try:
        bots.append(start_bot("a", config.bot_a, config))
        bots.append(start_bot("b", config.bot_b, config))
    except InfrastructureError:
        stop_bots(bots)
        raise

    bots_by_label = {bot.label: bot for bot in bots}
    moves = {"a": "", "b": ""}
    score = {"a": 0, "b": 0, "draws": 0}
    played_rounds: list[dict[str, object]] = []
    faults: dict[str, Optional[dict[str, object]]] = {"a": None, "b": None}

    try:
        for turn in range(config.rounds):
            before_request_faults = pre_request_faults(bots_by_label, turn)
            if before_request_faults:
                for label, bot_fault in before_request_faults.items():
                    faults[label] = bot_fault
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
                    send_faults[label] = fault(
                        "unexpected_exit",
                        turn,
                        "Bot exited or closed stdin before receiving the request",
                    )
                    signal_bot(bots_by_label[label], signal.SIGTERM)

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
            responses, response_faults, response_times_ns = read_responses(
                waiting_bots,
                turn,
                sent_ns,
                timeout_ms * 1_000_000,
                config.total_timeout_ms * 1_000_000,
            )
            turn_faults = send_faults | response_faults
            if turn_faults:
                for label, bot_fault in turn_faults.items():
                    faults[label] = bot_fault
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
        stop_bots(bots)

    faulted = [label for label, bot_fault in faults.items() if bot_fault is not None]
    if len(faulted) == 2:
        status = "double_forfeit"
        winner: Optional[str] = None
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
