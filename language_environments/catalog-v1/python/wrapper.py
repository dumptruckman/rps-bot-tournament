from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, "/opt/rps/team")
from strategy import choose_move


READY_MARKER = "RPS_READY_V1"


def read_history(line: str) -> str:
    return "" if line == "-" else line


def main() -> None:
    rng = random.Random(int(os.environ["RPS_SEED"]))
    print(READY_MARKER, file=sys.stderr, flush=True)
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
            read_history(own_history_line.rstrip("\n")),
            read_history(opponent_history_line.rstrip("\n")),
            rng,
        )
        print(move, flush=True)


if __name__ == "__main__":
    main()
