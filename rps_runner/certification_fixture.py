"""Run packaged, organizer-owned certification fixtures for internal practice."""

from __future__ import annotations

import os
import random
import sys
from collections.abc import Callable
from typing import Optional


ChooseMove = Callable[[int, str, str, random.Random], str]


def _random_move(
    turn: int,
    my_history: str,
    opponent_history: str,
    rng: random.Random,
) -> str:
    return rng.choice(("R", "P", "S"))


def _copycat_move(
    turn: int,
    my_history: str,
    opponent_history: str,
    rng: random.Random,
) -> str:
    return opponent_history[-1] if opponent_history else "R"


_FIXTURES: dict[str, ChooseMove] = {
    "copycat": _copycat_move,
    "random": _random_move,
}


def _history(line: str) -> str:
    return "" if line == "-" else line


def run(fixture_name: str) -> None:
    """Serve one internal fixture over the Runner's line protocol."""
    try:
        choose_move = _FIXTURES[fixture_name]
    except KeyError as error:
        raise ValueError(f"unknown certification fixture: {fixture_name}") from error

    rng = random.Random(int(os.environ["RPS_SEED"]))
    while True:
        turn_line = sys.stdin.readline()
        if turn_line == "":
            return
        my_history_line = sys.stdin.readline()
        opponent_history_line = sys.stdin.readline()
        if my_history_line == "" or opponent_history_line == "":
            return
        move = choose_move(
            int(turn_line.rstrip("\n")),
            _history(my_history_line.rstrip("\n")),
            _history(opponent_history_line.rstrip("\n")),
            rng,
        )
        print(move, flush=True)


def main(arguments: Optional[list[str]] = None) -> int:
    values = sys.argv[1:] if arguments is None else arguments
    if len(values) != 1:
        print(
            "usage: certification_fixture.py {copycat,random}",
            file=sys.stderr,
        )
        return 2
    try:
        run(values[0])
    except (KeyError, TypeError, ValueError) as error:
        print(f"certification fixture: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
