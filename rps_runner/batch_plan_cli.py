"""Build organizer-selected Team sources into a reviewable Tournament plan."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence, TextIO

from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationInputs,
    certify_artifact_candidate,
)
from rps_runner.artifact_store import ArtifactSelection, preserve_artifact_set
from rps_runner.cli import unsigned_64_bit_integer
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import freeze_source_bundle, load_catalog


ERROR_EXIT_CODE = 2
MINIMUM_TEAMS = 4
MAXIMUM_TEAMS = 32
PLAN_FORMAT_VERSION = "tournament-plan-v1"
BATCH_REPORT_FORMAT_VERSION = "artifact-batch-report-v1"
_TEAM_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")


@dataclass(frozen=True)
class BatchOperations:
    """Operations that turn source into a Bot Artifact at the batch boundary."""

    freeze: Callable[..., Mapping[str, Any]]
    build: Callable[..., Mapping[str, Any]]
    certify: Callable[..., Mapping[str, Any]]
    preserve: Callable[[Path, Sequence[ArtifactSelection]], Mapping[str, Any]]


DEFAULT_OPERATIONS = BatchOperations(
    freeze_source_bundle,
    build_artifact_candidate,
    certify_artifact_candidate,
    preserve_artifact_set,
)


@dataclass(frozen=True)
class CompatibilityRepair:
    source_directory: Path
    explanation: str


@dataclass(frozen=True)
class TeamSource:
    team_id: str
    display_name: str
    source_directory: Path
    repair: Optional[CompatibilityRepair] = None


@dataclass(frozen=True)
class TeamResult:
    team: TeamSource
    candidate: Optional[Path] = None
    certification: Optional[Path] = None
    selected_source: Optional[Mapping[str, Any]] = None
    artifact_manifest: Optional[Mapping[str, Any]] = None
    error: Optional[str] = None

    @property
    def status(self) -> str:
        return "failed" if self.error is not None else "validated"


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rps-batch-plan",
        description=(
            "Build and validate organizer-selected local Team sources, preserve "
            "their Bot Artifacts, and write a draft JSON Tournament plan"
        ),
    )
    parser.add_argument("--teams", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--tournament-seed", required=True, type=unsigned_64_bit_integer
    )
    parser.add_argument(
        "--execution-mode", choices=("step", "continuous"), default="continuous"
    )
    parser.add_argument(
        "--parallelism",
        type=_positive_integer,
        help="planned Match parallelism (defaults to four in Continuous Mode)",
    )
    parser.add_argument(
        "--jobs",
        required=True,
        type=_positive_integer,
        help="maximum concurrently active Team build/validation workflows",
    )
    parser.add_argument(
        "--retain-practice-images",
        action="store_true",
        help="retain conformance practice images for organizer readiness evidence",
    )
    return parser


def _read_mapping(path: Path, description: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(description + " must be an existing non-symlink file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("could not read " + description + ": " + str(error))
    if not isinstance(value, dict):
        raise ValueError(description + " must be a JSON object")
    return value


def _required_string(value: Mapping[str, Any], field: str, location: str) -> str:
    selected = value.get(field)
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError(location + "." + field + " must be a non-empty string")
    return selected


def _load_teams(path: Path) -> tuple[TeamSource, ...]:
    root = _read_mapping(path, "Team source mapping")
    values = root.get("teams")
    if not isinstance(values, list):
        raise ValueError("Team source mapping.teams must be an array")
    if not MINIMUM_TEAMS <= len(values) <= MAXIMUM_TEAMS:
        raise ValueError(
            "Team source mapping must contain four through thirty-two Teams"
        )
    teams = []
    seen: set[str] = set()
    for ordinal, value in enumerate(values):
        location = "Team source mapping.teams[" + str(ordinal) + "]"
        if not isinstance(value, dict):
            raise ValueError(location + " must be an object")
        team_id = _required_string(value, "team_id", location)
        if _TEAM_ID.fullmatch(team_id) is None:
            raise ValueError(location + ".team_id is not a valid Team ID")
        if team_id in seen:
            raise ValueError("Team IDs must be unique: " + team_id)
        seen.add(team_id)
        display_name = _required_string(value, "display_name", location)
        source_directory = Path(
            _required_string(value, "source_directory", location)
        ).expanduser().absolute()
        repair = value.get("repair")
        compatibility_repair: Optional[CompatibilityRepair] = None
        if repair is not None:
            if not isinstance(repair, dict):
                raise ValueError(location + ".repair must be an object")
            repair_source = Path(
                _required_string(repair, "source_directory", location + ".repair")
            ).expanduser().absolute()
            repair_explanation = _required_string(
                repair, "explanation", location + ".repair"
            ).strip()
            compatibility_repair = CompatibilityRepair(
                repair_source, repair_explanation
            )
        teams.append(
            TeamSource(
                team_id,
                display_name.strip(),
                source_directory,
                compatibility_repair,
            )
        )
    return tuple(teams)


def _bundle_manifest(bundle: Path) -> Mapping[str, Any]:
    return _read_mapping(bundle / "source-bundle.json", "frozen source manifest")


def _artifact_manifest(certification: Path) -> Mapping[str, Any]:
    return _read_mapping(
        certification / "bot-artifact-manifest.json", "Bot Artifact Manifest"
    )


def _source_files(bundle: Path) -> Mapping[str, bytes]:
    source = bundle / "source"
    files: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        if path.is_file():
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def _complete_source_diff(original: Path, replacement: Path) -> str:
    before = _source_files(original)
    after = _source_files(replacement)
    output: list[str] = []
    for name in sorted(set(before) | set(after)):
        old = before.get(name)
        new = after.get(name)
        if old == new:
            continue
        if old is None and new == b"":
            output.extend(
                (
                    "--- /dev/null\n",
                    "+++ b/" + name + "\n",
                    "@@ empty file added @@\n",
                )
            )
            continue
        if old == b"" and new is None:
            output.extend(
                (
                    "--- a/" + name + "\n",
                    "+++ /dev/null\n",
                    "@@ empty file deleted @@\n",
                )
            )
            continue
        old_content = old or b""
        new_content = new or b""
        try:
            old_lines = old_content.decode("utf-8").splitlines(keepends=True)
            new_lines = new_content.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            output.extend(
                (
                    "--- a/" + name + "\n",
                    "+++ b/" + name + "\n",
                    "@@ binary content @@\n",
                    "-sha256:" + hashlib.sha256(old_content).hexdigest() + "\n",
                    "+sha256:" + hashlib.sha256(new_content).hexdigest() + "\n",
                    "-hex:" + old_content.hex() + "\n",
                    "+hex:" + new_content.hex() + "\n",
                )
            )
            continue
        output.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="a/" + name,
                tofile="b/" + name,
            )
        )
    return "".join(output)


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _process_team(
    team: TeamSource,
    team_root: Path,
    catalog: object,
    environment: object,
    operations: BatchOperations,
    retain_practice_images: bool = False,
) -> TeamResult:
    try:
        original_bundle = team_root / (
            "original-source" if team.repair else "selected-source"
        )
        original_manifest = operations.freeze(
            team.source_directory, original_bundle, catalog, environment
        )
        selected_bundle = original_bundle
        repair_record: Optional[Mapping[str, Any]] = None
        if team.repair is not None:
            selected_bundle = team_root / "selected-source"
            replacement_manifest = operations.freeze(
                team.repair.source_directory,
                selected_bundle,
                catalog,
                environment,
            )
            diff = _complete_source_diff(original_bundle, selected_bundle)
            repair_record = {
                "original_source_digest": original_manifest["source_digest"],
                "replacement_source_digest": replacement_manifest["source_digest"],
                "diff": diff,
                "diff_digest": _digest_text(diff),
                "explanation": team.repair.explanation,
            }
        selected_manifest = _bundle_manifest(selected_bundle)
        candidate = team_root / "candidate"
        operations.build(selected_bundle, candidate, catalog, "linux/arm64")
        certification = team_root / "certification"
        certification_arguments = (
            candidate,
            certification,
            catalog,
            CertificationInputs(
                "organizer-final", "linux/arm64", INITIAL_EXECUTION_PROFILE.version
            ),
        )
        if retain_practice_images:
            operations.certify(
                *certification_arguments,
                retain_practice_images=True,
            )
        else:
            operations.certify(*certification_arguments)
        artifact_manifest = _artifact_manifest(certification)
        if repair_record is not None:
            repair_record = {
                **repair_record,
                "final_validation_identity": artifact_manifest["validation_identity"],
            }
        selected_source: dict[str, Any] = {
            "source_digest": selected_manifest["source_digest"]
        }
        if repair_record is not None:
            selected_source["repair"] = repair_record
        return TeamResult(
            team,
            candidate=candidate,
            certification=certification,
            selected_source=selected_source,
            artifact_manifest=artifact_manifest,
        )
    except Exception as error:
        return TeamResult(team, error=str(error))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _batch_report(results: Sequence[TeamResult], jobs: int) -> Mapping[str, Any]:
    return {
        "batch_report_format_version": BATCH_REPORT_FORMAT_VERSION,
        "operational_limit": jobs,
        "status": (
            "passed"
            if all(result.status == "validated" for result in results)
            else "failed"
        ),
        "teams": [
            {
                "team_id": result.team.team_id,
                "status": result.status,
                **({"error": result.error} if result.error else {}),
            }
            for result in results
        ],
    }


def _canonical_artifact_identity(
    manifest: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Project Bot Artifact identity without operational Docker-cache references."""
    canonical = json.loads(json.dumps(manifest))
    canonical.pop("retention", None)
    image = canonical.get("image")
    if isinstance(image, dict):
        image.pop("local_image_id", None)
    return canonical


def _plan(
    results: Sequence[TeamResult],
    store_index: Mapping[str, Any],
    catalog: object,
    tournament_seed: int,
    execution_mode: str,
    parallelism: int,
) -> Mapping[str, Any]:
    index_identity = store_index["integrity"]["index_identity"]
    profile_values = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
    profile_values.pop("version")
    profile_values.pop("recommended_match_parallelism")
    teams = []
    for result in results:
        assert result.artifact_manifest is not None
        assert result.selected_source is not None
        teams.append(
            {
                "team_id": result.team.team_id,
                "display_name": result.team.display_name,
                "roster_ready": True,
                "selected_source": result.selected_source,
                "bot_artifact_manifest": result.artifact_manifest,
                "canonical_artifact_identity": _canonical_artifact_identity(
                    result.artifact_manifest
                ),
                "artifact_store_reference": {
                    "index_identity": index_identity,
                    "artifact_digest": result.artifact_manifest["artifact_digest"],
                    "platform": result.artifact_manifest["platform"],
                },
            }
        )
    return {
        "tournament_plan_format_version": PLAN_FORMAT_VERSION,
        "status": "draft",
        "tournament_seed": tournament_seed,
        "execution": {"mode": execution_mode, "parallelism": parallelism},
        "catalog": {"version": catalog.version, "identity": catalog.identity},
        "execution_profile": {
            "version": INITIAL_EXECUTION_PROFILE.version,
            "identity": INITIAL_EXECUTION_PROFILE.identity,
        },
        "global_resources": profile_values,
        "artifact_store": {"index_identity": index_identity},
        "teams": teams,
    }


def main(
    arguments: Optional[list[str]] = None,
    *,
    operations: BatchOperations = DEFAULT_OPERATIONS,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    options = build_parser().parse_args(arguments)
    output = stdout or sys.stdout
    error_output = stderr or sys.stderr
    try:
        teams = _load_teams(options.teams)
        catalog = load_catalog(options.catalog)
        environment = catalog.environment("python")
        destination = options.output.expanduser().resolve()
        if destination.exists() or destination.is_symlink():
            raise ValueError(
                "output destination already exists and will not be replaced"
            )
        destination.mkdir(parents=True)
        team_directory = destination / "teams"
        team_directory.mkdir()
        futures = {}
        with ThreadPoolExecutor(max_workers=options.jobs) as executor:
            for team in teams:
                root = team_directory / team.team_id
                root.mkdir()
                future = executor.submit(
                    _process_team,
                    team,
                    root,
                    catalog,
                    environment,
                    operations,
                    options.retain_practice_images,
                )
                futures[future] = team.team_id
            completed = [future.result() for future in as_completed(futures)]
        results = sorted(completed, key=lambda result: result.team.team_id)
        report = _batch_report(results, options.jobs)
        _write_json(destination / "batch-report.json", report)
        if report["status"] != "passed":
            print(
                "rps-batch-plan: one or more Team workflows failed; "
                "see batch-report.json",
                file=error_output,
            )
            return ERROR_EXIT_CODE

        selections = []
        seen_artifacts: set[str] = set()
        for result in results:
            assert result.candidate is not None
            assert result.certification is not None
            assert result.artifact_manifest is not None
            artifact_digest = str(result.artifact_manifest["artifact_digest"])
            if artifact_digest not in seen_artifacts:
                selections.append(
                    ArtifactSelection(result.candidate, result.certification)
                )
                seen_artifacts.add(artifact_digest)
        store_index = operations.preserve(destination / "artifact-store", selections)
        parallelism = options.parallelism or (
            INITIAL_EXECUTION_PROFILE.recommended_match_parallelism
            if options.execution_mode == "continuous"
            else 1
        )
        plan = _plan(
            results,
            store_index,
            catalog,
            options.tournament_seed,
            options.execution_mode,
            parallelism,
        )
        _write_json(destination / "tournament-plan.json", plan)
        print(json.dumps(plan, indent=2, sort_keys=True), file=output)
        return 0
    except (KeyError, OSError, TypeError, ValueError) as error:
        print("rps-batch-plan: " + str(error), file=error_output)
        return ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
