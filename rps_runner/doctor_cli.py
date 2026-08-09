from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from rps_runner.host_readiness import (
    DEFAULT_MINIMUM_FREE_DISK_BYTES,
    HostReadinessRequest,
    diagnose_host_readiness,
)


def _practice_artifact(value: str) -> tuple[str, str]:
    name, separator, reference = value.partition("=")
    if not separator or not name or not reference:
        raise argparse.ArgumentTypeError("practice artifact must be NAME=IMMUTABLE_REFERENCE")
    return name, reference


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-doctor",
        description="Inspect container-host readiness without changing Docker or host state",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument(
        "--platform", required=True, choices=("linux/arm64", "linux/amd64")
    )
    parser.add_argument("--artifact-store", required=True, type=Path)
    parser.add_argument("--parallelism", type=int, default=4)
    parser.add_argument(
        "--minimum-free-disk-bytes",
        type=int,
        default=DEFAULT_MINIMUM_FREE_DISK_BYTES,
    )
    parser.add_argument("--expected-context")
    parser.add_argument(
        "--organizer-layer",
        "--organizer-image",
        dest="organizer_image",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--practice-artifact", action="append", type=_practice_artifact, default=[]
    )
    parser.add_argument("--rehearsal-evidence", type=Path)
    return parser


def run(arguments: Optional[list[str]] = None) -> dict[str, object]:
    options = build_parser().parse_args(arguments)
    request = HostReadinessRequest(
        catalog=options.catalog,
        platform=options.platform,
        artifact_store=options.artifact_store,
        parallelism=options.parallelism,
        minimum_free_disk_bytes=options.minimum_free_disk_bytes,
        expected_context=options.expected_context,
        organizer_images=tuple(options.organizer_image),
        practice_artifacts=tuple(options.practice_artifact),
        rehearsal_evidence=options.rehearsal_evidence,
    )
    return dict(diagnose_host_readiness(request))


def main(arguments: Optional[list[str]] = None) -> int:
    try:
        report = run(arguments)
    except ValueError as error:
        print("rps-doctor: " + str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
