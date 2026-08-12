from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from rps_runner.artifact_certification import (
    CERTIFICATION_MODES,
    CertificationFailure,
    CertificationInputs,
    certify_artifact_candidate,
)
from rps_runner.language_environment import (
    CatalogError,
    SourceValidationError,
    load_catalog,
)


CERTIFICATION_ERROR_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-certify-artifact",
        description="Run the selected versioned Bot Artifact conformance suite",
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--mode",
        required=True,
        choices=CERTIFICATION_MODES,
    )
    parser.add_argument("--platform", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(arguments: Optional[list[str]] = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        inputs = CertificationInputs(options.mode, options.platform, options.profile)
        inputs.validate()
        catalog = load_catalog(options.catalog)
        result = certify_artifact_candidate(
            options.candidate, options.output, catalog, inputs
        )
    except (
        CertificationFailure,
        CatalogError,
        SourceValidationError,
        OSError,
    ) as error:
        print("rps-certify-artifact: conformance failure: " + str(error), file=sys.stderr)
        return CERTIFICATION_ERROR_EXIT_CODE
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
