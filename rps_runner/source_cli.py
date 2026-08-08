from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

from rps_runner.language_environment import (
    CatalogError,
    SourceValidationError,
    freeze_source_bundle,
    load_catalog,
)


VALIDATION_ERROR_EXIT_CODE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-validate-source",
        description=(
            "Validate and freeze Team source using a Language Environment catalog"
        ),
    )
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    return parser


def main(arguments: Optional[list[str]] = None) -> int:
    options = build_parser().parse_args(arguments)
    try:
        catalog = load_catalog(options.catalog)
        environment = catalog.environment(options.environment)
        result = freeze_source_bundle(
            options.source, options.bundle, catalog, environment
        )
    except (CatalogError, SourceValidationError, OSError) as error:
        print("rps-validate-source: " + str(error), file=sys.stderr)
        return VALIDATION_ERROR_EXIT_CODE
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
