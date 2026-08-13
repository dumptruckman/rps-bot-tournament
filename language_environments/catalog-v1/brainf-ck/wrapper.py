"""Organizer-owned protocol wrapper for the Brainf-ck RPS dialect."""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interpreter import (
    ExecutionLimitError,
    InputExhaustedError,
    ProgramSyntaxError,
    compile_program,
    execute,
)


READY_MARKER = "RPS_READY_V1"
MOVES = "RPS"
MAX_SEED = (1 << 64) - 1
LCG_MULTIPLIER = 6364136223846793005
LCG_INCREMENT = 1442695040888963407


def fail(message: str) -> None:
    print("Brainf-ck wrapper: " + message, file=sys.stderr, flush=True)
    raise SystemExit(2)


def read_history(line: str) -> str:
    value = "" if line == "-" else line
    if any(move not in MOVES for move in value):
        fail("history must contain only R, P, or S")
    return value


def seeded_move(seed: int, turn: int) -> str:
    """Return one move from the Brainf-ck deterministic 64-bit LCG stream."""

    state = seed
    for _ in range(turn + 1):
        state = (state * LCG_MULTIPLIER + LCG_INCREMENT) & MAX_SEED
    return MOVES[state % len(MOVES)]


def encode_turn(seed: int, turn: int, own_history: str, opponent_history: str) -> bytes:
    """Encode the deterministic Brainf-ck RPS input record."""

    random_move = seeded_move(seed, turn)
    opponent_move = opponent_history[-1] if opponent_history else "R"
    turn_move = MOVES[turn % len(MOVES)]
    return b"".join(
        (
            random_move.encode("ascii"),
            opponent_move.encode("ascii"),
            turn_move.encode("ascii"),
            seed.to_bytes(8, "little"),
            turn.to_bytes(8, "little"),
            len(own_history).to_bytes(2, "little"),
            own_history.encode("ascii"),
            len(opponent_history).to_bytes(2, "little"),
            opponent_history.encode("ascii"),
        )
    )


def load_program():
    source_path = Path(os.environ.get("RPS_BRAINF_CK_SOURCE", "/opt/rps/team/strategy.bf"))
    try:
        source = source_path.read_text(encoding="ascii")
        program = compile_program(source)
    except (OSError, UnicodeError, ProgramSyntaxError) as error:
        fail(str(error))
    try:
        execute(program, b"")
    except InputExhaustedError as error:
        if error.output:
            sys.stdout.buffer.write(error.output)
            sys.stdout.buffer.flush()
        return program
    except ExecutionLimitError as error:
        fail(str(error))
    fail("program must request encoded input before producing a move")


def main() -> None:
    if os.environ.get("RPS_PROTOCOL_VERSION") != "1":
        fail("unsupported RPS_PROTOCOL_VERSION")
    try:
        seed_text = os.environ["RPS_SEED"]
        if not seed_text.isascii() or not seed_text.isdecimal():
            raise ValueError
        seed = int(seed_text)
        if not 0 <= seed <= MAX_SEED:
            raise ValueError
    except (KeyError, ValueError):
        fail("RPS_SEED must be an unsigned 64-bit integer")

    program = load_program()
    print(READY_MARKER, file=sys.stderr, flush=True)
    while True:
        turn_line = sys.stdin.readline()
        if turn_line == "":
            return
        own_line = sys.stdin.readline()
        opponent_line = sys.stdin.readline()
        if own_line == "" or opponent_line == "":
            return
        try:
            turn = int(turn_line.rstrip("\n"))
        except ValueError:
            fail("Turn must be an integer")
        own_history = read_history(own_line.rstrip("\n"))
        opponent_history = read_history(opponent_line.rstrip("\n"))
        if turn < 0 or turn != len(own_history) or turn != len(opponent_history):
            fail("Turn and history lengths must match")
        try:
            output = execute(program, encode_turn(seed, turn, own_history, opponent_history))
        except (ExecutionLimitError, InputExhaustedError) as error:
            fail(str(error))
        if len(output) != 1 or chr(output[0]) not in MOVES:
            fail("move output must be exactly one ASCII R, P, or S byte")
        sys.stdout.buffer.write(output + b"\n")
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
