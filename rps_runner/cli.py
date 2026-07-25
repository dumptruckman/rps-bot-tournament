from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from rps_runner.engine import InfrastructureError, MatchConfig, run_match


INFRASTRUCTURE_ERROR_EXIT_CODE = 2


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def unsigned_64_bit_integer(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= 2**64 - 1:
        raise argparse.ArgumentTypeError("must be an unsigned 64-bit integer")
    return parsed


def nonnegative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-run", description="Run a local Rock-Paper-Scissors bot match"
    )
    parser.add_argument("--bot-a", required=True, help="command used to start bot A")
    parser.add_argument("--bot-b", required=True, help="command used to start bot B")
    parser.add_argument("--rounds", required=True, type=positive_integer)
    parser.add_argument("--seed", required=True, type=unsigned_64_bit_integer)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--first-move-timeout-ms", type=positive_integer, default=250
    )
    parser.add_argument("--move-timeout-ms", type=positive_integer, default=50)
    parser.add_argument("--total-timeout-ms", type=positive_integer, default=2000)
    parser.add_argument(
        "--stderr-limit-bytes", type=nonnegative_integer, default=65_536
    )
    return parser


def _write_result(path: Path, result: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def main(arguments: list[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    config = MatchConfig(
        bot_a=options.bot_a,
        bot_b=options.bot_b,
        rounds=options.rounds,
        seed=options.seed,
        first_move_timeout_ms=options.first_move_timeout_ms,
        move_timeout_ms=options.move_timeout_ms,
        total_timeout_ms=options.total_timeout_ms,
        stderr_limit_bytes=options.stderr_limit_bytes,
    )

    try:
        result = run_match(config)
    except InfrastructureError as error:
        result = {
            "protocol_version": 1,
            "scheduled_rounds": options.rounds,
            "seed": options.seed,
            "status": "infrastructure_error",
            "error": str(error),
        }
        try:
            _write_result(options.output, result)
        except OSError as output_error:
            print(
                f"rps-run: {error}; also could not write result: {output_error}",
                file=sys.stderr,
            )
            return INFRASTRUCTURE_ERROR_EXIT_CODE
        print(f"rps-run: {error}", file=sys.stderr)
        return INFRASTRUCTURE_ERROR_EXIT_CODE

    try:
        _write_result(options.output, result)
    except OSError as error:
        print(f"rps-run: could not write result: {error}", file=sys.stderr)
        return INFRASTRUCTURE_ERROR_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
