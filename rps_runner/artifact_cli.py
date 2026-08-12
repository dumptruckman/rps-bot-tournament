from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from rps_runner.artifact_builder import (
    ArtifactBuildFailure,
    DEFAULT_MAX_DIAGNOSTICS_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    build_artifact_candidate,
)
from rps_runner.language_environment import (
    CatalogError,
    SourceValidationError,
    load_catalog,
)


BUILD_ERROR_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-build-artifact",
        description="Build one platform-specific Bot Artifact candidate",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--max-diagnostics-bytes", type=int, default=DEFAULT_MAX_DIAGNOSTICS_BYTES
    )
    return parser


def main(arguments: Optional[list[str]] = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        catalog = load_catalog(options.catalog)
        result = build_artifact_candidate(
            options.bundle,
            options.candidate,
            catalog,
            options.platform,
            timeout_seconds=options.timeout_seconds,
            maximum_diagnostics_bytes=options.max_diagnostics_bytes,
        )
    except (
        ArtifactBuildFailure,
        CatalogError,
        SourceValidationError,
        OSError,
    ) as error:
        print(
            "rps-build-artifact: non-competitive build failure: " + str(error),
            file=sys.stderr,
        )
        diagnostics = getattr(error, "diagnostics", "")
        if diagnostics:
            print(
                diagnostics,
                file=sys.stderr,
                end="" if diagnostics.endswith("\n") else "\n",
            )
        return BUILD_ERROR_EXIT_CODE
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
