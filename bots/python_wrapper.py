from __future__ import annotations

import os
import random
import sys
from typing import Callable


ChooseMove = Callable[[int, str, str, random.Random], str]


def _read_history(line: str) -> str:
    return "" if line == "-" else line


def run(choose_move: ChooseMove) -> None:
    """Run a Python strategy function using the line-based bot protocol."""
    rng = random.Random(int(os.environ["RPS_SEED"]))
    while True:
        turn_line = sys.stdin.readline()
        if turn_line == "":
            return
        own_history_line = sys.stdin.readline()
        opponent_history_line = sys.stdin.readline()
        if own_history_line == "" or opponent_history_line == "":
            return

        move = choose_move(
            int(turn_line.rstrip("\n")),
            _read_history(own_history_line.rstrip("\n")),
            _read_history(opponent_history_line.rstrip("\n")),
            rng,
        )
        print(move, flush=True)
