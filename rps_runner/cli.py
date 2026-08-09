from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Optional

from rps_runner.engine import InfrastructureError, MatchConfig, run_match
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.tournament.match_executor import (
    ContainerMatchExecutor,
    MatchExecutionRequest,
)


INFRASTRUCTURE_ERROR_EXIT_CODE = 2
_IMMUTABLE_IMAGE_REFERENCE = re.compile(
    r"(?:sha256:[0-9a-f]{64}|[^@\s]+@sha256:[0-9a-f]{64})\Z"
)


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
    profile = INITIAL_EXECUTION_PROFILE
    parser = argparse.ArgumentParser(
        prog="rps-run", description="Run a local Rock-Paper-Scissors bot match"
    )
    parser.add_argument("--bot-a", required=True, help="command used to start bot A")
    parser.add_argument("--bot-b", required=True, help="command used to start bot B")
    parser.add_argument(
        "--container",
        action="store_true",
        help="treat --bot-a and --bot-b as immutable container image references",
    )
    parser.add_argument("--rounds", required=True, type=positive_integer)
    parser.add_argument("--seed", required=True, type=unsigned_64_bit_integer)
    parser.add_argument("--bot-a-seed", type=unsigned_64_bit_integer)
    parser.add_argument("--bot-b-seed", type=unsigned_64_bit_integer)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--first-move-timeout-ms",
        type=positive_integer,
        default=profile.first_move_timeout_ms,
    )
    parser.add_argument(
        "--move-timeout-ms", type=positive_integer, default=profile.move_timeout_ms
    )
    parser.add_argument(
        "--total-timeout-ms",
        type=positive_integer,
        default=profile.total_timeout_ms,
    )
    parser.add_argument(
        "--stderr-limit-bytes",
        type=nonnegative_integer,
        default=profile.stderr_limit_bytes,
    )
    parser.add_argument(
        "--stdout-limit-bytes",
        type=positive_integer,
        default=profile.stdout_limit_bytes,
    )
    parser.add_argument(
        "--cpu-limit-ms", type=positive_integer, default=profile.cpu_limit_ms
    )
    parser.add_argument(
        "--cpu-quota-millis-per-second",
        type=positive_integer,
        default=profile.cpu_quota_millis_per_second,
    )
    parser.add_argument(
        "--memory-limit-bytes",
        type=positive_integer,
        default=profile.memory_limit_bytes,
    )
    parser.add_argument(
        "--process-limit", type=positive_integer, default=profile.process_limit
    )
    parser.add_argument(
        "--open-file-limit", type=positive_integer, default=profile.open_file_limit
    )
    parser.add_argument(
        "--filesystem-write-limit-bytes",
        type=positive_integer,
        default=profile.filesystem_write_limit_bytes,
    )
    return parser


def _write_result(path: Path, result: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


def main(arguments: Optional[list[str]] = None) -> int:
    parser = build_parser()
    options = parser.parse_args(arguments)
    if options.container:
        if options.rounds != 300:
            parser.error("official container Matches require exactly 300 rounds")
        for option_name in ("bot_a", "bot_b"):
            value = getattr(options, option_name)
            if _IMMUTABLE_IMAGE_REFERENCE.fullmatch(value) is None:
                parser.error(
                    "container image references must use an immutable sha256 digest"
                )
        if options.cpu_limit_ms % 1000 != 0:
            parser.error("--cpu-limit-ms must be a whole number of seconds")
        return _run_container_match(options)
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


def _run_container_match(options: argparse.Namespace) -> int:
    images = {"bot-a": options.bot_a, "bot-b": options.bot_b}
    request = MatchExecutionRequest(
        tournament_id="single-match",
        fixture_id="single-match-fixture",
        series_id="single-match-series",
        match_id="single-match-1",
        attempt_number=1,
        team_a_id="bot-a",
        team_b_id="bot-b",
        artifact_digest_a=options.bot_a,
        artifact_digest_b=options.bot_b,
        match_seed=options.seed,
        bot_visible_seed_a=(
            options.seed if options.bot_a_seed is None else options.bot_a_seed
        ),
        bot_visible_seed_b=(
            options.seed if options.bot_b_seed is None else options.bot_b_seed
        ),
        protocol_version=1,
        scheduled_turns=options.rounds,
        first_move_timeout_ms=options.first_move_timeout_ms,
        move_timeout_ms=options.move_timeout_ms,
        total_timeout_ms=options.total_timeout_ms,
        stderr_limit_bytes=options.stderr_limit_bytes,
        stdout_limit_bytes=options.stdout_limit_bytes,
        cpu_limit_ms=options.cpu_limit_ms,
        cpu_quota_millis_per_second=options.cpu_quota_millis_per_second,
        memory_limit_bytes=options.memory_limit_bytes,
        process_limit=options.process_limit,
        open_file_limit=options.open_file_limit,
        filesystem_write_limit_bytes=options.filesystem_write_limit_bytes,
        network_access_allowed=False,
    )
    result = ContainerMatchExecutor(
        lambda team_id, digest: images[team_id]
    ).execute(request)
    output = {
        "infrastructure_failure": result.infrastructure_failure,
        "competitive_outcome": result.competitive_outcome,
        "operational_telemetry": result.operational_telemetry,
    }
    try:
        _write_result(options.output, output)
    except OSError as error:
        print(f"rps-run: could not write result: {error}", file=sys.stderr)
        return INFRASTRUCTURE_ERROR_EXIT_CODE
    if result.infrastructure_failure:
        message = result.operational_telemetry["infrastructure_failure"]["message"]
        print(f"rps-run: {message}", file=sys.stderr)
        return INFRASTRUCTURE_ERROR_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
