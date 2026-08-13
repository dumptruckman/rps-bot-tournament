"""Catalog-owned Brainf-ck RPS dialect interpreter, version 1."""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple


COMMANDS = frozenset("><+-.,[]")
DEFAULT_TAPE_CELLS = 30_000
DEFAULT_STEP_LIMIT = 1_000_000
DEFAULT_OUTPUT_LIMIT = 1
DEFAULT_TIME_LIMIT_MS = 50


class ProgramSyntaxError(ValueError):
    """The program does not have balanced loop delimiters."""


class ExecutionLimitError(RuntimeError):
    """The program exceeded an organizer-owned execution bound."""


class InputExhaustedError(RuntimeError):
    """The program requested another byte after consuming its input."""

    def __init__(self, output: bytes) -> None:
        super().__init__("Brainf-ck input exhausted")
        self.output = output


Program = Tuple[str, Dict[int, int]]


def compile_program(source: str) -> Program:
    """Strip comments and compile balanced loop jumps."""

    code = "".join(character for character in source if character in COMMANDS)
    stack = []
    jumps: Dict[int, int] = {}
    for index, command in enumerate(code):
        if command == "[":
            stack.append(index)
        elif command == "]":
            if not stack:
                raise ProgramSyntaxError("unmatched closing bracket at command " + str(index))
            opening = stack.pop()
            jumps[opening] = index
            jumps[index] = opening
    if stack:
        raise ProgramSyntaxError("unmatched opening bracket at command " + str(stack[-1]))
    return code, jumps


def execute(
    program: Program,
    input_bytes: bytes,
    *,
    tape_cells: int = DEFAULT_TAPE_CELLS,
    step_limit: int = DEFAULT_STEP_LIMIT,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    time_limit_ms: Optional[int] = DEFAULT_TIME_LIMIT_MS,
) -> bytes:
    """Execute with wrapping 8-bit cells and a fixed, non-wrapping tape."""

    code, jumps = program
    tape = bytearray(tape_cells)
    pointer = 0
    instruction = 0
    input_index = 0
    output = bytearray()
    steps = 0
    started = time.monotonic()
    while instruction < len(code):
        steps += 1
        if steps > step_limit:
            raise ExecutionLimitError("Brainf-ck step limit exceeded")
        if time_limit_ms is not None and steps % 1024 == 0:
            elapsed_ms = (time.monotonic() - started) * 1000
            if elapsed_ms > time_limit_ms:
                raise ExecutionLimitError("Brainf-ck time limit exceeded")

        command = code[instruction]
        if command == ">":
            pointer += 1
            if pointer >= tape_cells:
                raise ExecutionLimitError("Brainf-ck tape limit exceeded")
        elif command == "<":
            pointer -= 1
            if pointer < 0:
                raise ExecutionLimitError("Brainf-ck tape limit exceeded")
        elif command == "+":
            tape[pointer] = (tape[pointer] + 1) & 0xFF
        elif command == "-":
            tape[pointer] = (tape[pointer] - 1) & 0xFF
        elif command == ".":
            if len(output) >= output_limit:
                raise ExecutionLimitError("Brainf-ck output limit exceeded")
            output.append(tape[pointer])
        elif command == ",":
            if input_index >= len(input_bytes):
                raise InputExhaustedError(bytes(output))
            tape[pointer] = input_bytes[input_index]
            input_index += 1
        elif command == "[" and tape[pointer] == 0:
            instruction = jumps[instruction]
        elif command == "]" and tape[pointer] != 0:
            instruction = jumps[instruction]
        instruction += 1
    return bytes(output)
