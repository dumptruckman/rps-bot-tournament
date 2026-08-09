"""Bounded concurrent Team source-to-Bot-Artifact workflows."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

from rps_runner.artifact_certification import CertificationInputs
from rps_runner.batch_artifacts import ExactValidatedBotArtifactManifest
from rps_runner.batch_repair import CompatibilityRepair
from rps_runner.batch_team_sources import TeamSource
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE


@dataclass(frozen=True)
class BatchOperations:
    """Operations that turn source into a Bot Artifact at the batch seam."""

    freeze: Callable[..., Mapping[str, Any]]
    build: Callable[..., Mapping[str, Any]]
    certify: Callable[..., Mapping[str, Any]]
    preserve: Callable[..., Mapping[str, Any]]


class TeamWorkflowStatus(str, Enum):
    VALIDATED = "validated"
    FAILED = "failed"


@dataclass(frozen=True)
class SelectedSource:
    source_digest: str
    repair: Optional[CompatibilityRepair] = None


@dataclass(frozen=True)
class TeamWorkflowResult:
    team: TeamSource
    status: TeamWorkflowStatus
    candidate: Optional[Path] = None
    certification: Optional[Path] = None
    selected_source: Optional[SelectedSource] = None
    artifact_manifest: Optional[ExactValidatedBotArtifactManifest] = None
    error: Optional[str] = None

    @classmethod
    def validated(
        cls,
        team: TeamSource,
        candidate: Path,
        certification: Path,
        selected_source: SelectedSource,
        artifact_manifest: ExactValidatedBotArtifactManifest,
    ) -> "TeamWorkflowResult":
        return cls(
            team=team,
            status=TeamWorkflowStatus.VALIDATED,
            candidate=candidate,
            certification=certification,
            selected_source=selected_source,
            artifact_manifest=artifact_manifest,
        )

    @classmethod
    def failed(cls, team: TeamSource, error: Exception) -> "TeamWorkflowResult":
        return cls(team=team, status=TeamWorkflowStatus.FAILED, error=str(error))


class BatchExecutor:
    """Coordinate Team workflows under one explicit concurrency limit."""

    def __init__(
        self,
        catalog: object,
        environment: object,
        operations: BatchOperations,
        retain_practice_images: bool = False,
    ) -> None:
        self._catalog = catalog
        self._environment = environment
        self._operations = operations
        self._retain_practice_images = retain_practice_images

    def execute(
        self, teams: Sequence[TeamSource], team_directory: Path, jobs: int
    ) -> tuple[TeamWorkflowResult, ...]:
        futures = []
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            for team in teams:
                root = team_directory / str(team.team_id)
                root.mkdir()
                futures.append(executor.submit(self._execute_team, team, root))
            return tuple(future.result() for future in as_completed(futures))

    def _execute_team(self, team: TeamSource, team_root: Path) -> TeamWorkflowResult:
        try:
            original_bundle = team_root / (
                "original-source" if team.repair else "selected-source"
            )
            original_manifest = self._operations.freeze(
                team.source_directory,
                original_bundle,
                self._catalog,
                self._environment,
            )
            selected_bundle = original_bundle
            replacement_manifest = original_manifest
            if team.repair is not None:
                selected_bundle = team_root / "selected-source"
                replacement_manifest = self._operations.freeze(
                    team.repair.source_directory,
                    selected_bundle,
                    self._catalog,
                    self._environment,
                )

            selected_manifest = _read_manifest(
                selected_bundle / "source-bundle.json", "frozen source manifest"
            )
            candidate = team_root / "candidate"
            self._operations.build(
                selected_bundle, candidate, self._catalog, "linux/arm64"
            )
            certification = team_root / "certification"
            arguments = (
                candidate,
                certification,
                self._catalog,
                CertificationInputs(
                    "organizer-final",
                    "linux/arm64",
                    INITIAL_EXECUTION_PROFILE.version,
                ),
            )
            if self._retain_practice_images:
                self._operations.certify(*arguments, retain_practice_images=True)
            else:
                self._operations.certify(*arguments)
            artifact_manifest = ExactValidatedBotArtifactManifest(
                _read_manifest(
                    certification / "bot-artifact-manifest.json",
                    "Bot Artifact Manifest",
                )
            )

            retained_repair = team.repair
            if retained_repair is not None:
                retained_repair = retained_repair.retain(
                    original_bundle=original_bundle,
                    replacement_bundle=selected_bundle,
                    original_source_digest=str(original_manifest["source_digest"]),
                    replacement_source_digest=str(
                        replacement_manifest["source_digest"]
                    ),
                    final_validation_identity=artifact_manifest.validation_identity,
                )
            return TeamWorkflowResult.validated(
                team,
                candidate,
                certification,
                SelectedSource(
                    source_digest=str(selected_manifest["source_digest"]),
                    repair=retained_repair,
                ),
                artifact_manifest,
            )
        except Exception as error:
            return TeamWorkflowResult.failed(team, error)


def _read_manifest(path: Path, description: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(description + " must be an existing non-symlink file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("could not read " + description + ": " + str(error))
    if not isinstance(value, dict):
        raise ValueError(description + " must be a JSON object")
    return value
