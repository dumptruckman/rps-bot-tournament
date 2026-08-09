from __future__ import annotations

import hashlib
from io import StringIO
import json
from pathlib import Path
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import load_catalog
from rps_runner.tournament.match_executor import (
    ContainerMatchExecutor,
    MatchExecutionRequest,
    MatchExecutionResult,
)
from rps_runner.tournament.immutable import thaw_json
from rps_runner.tournament.storage import (
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
)
from rps_runner.tournament_cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = (
    PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"
)


class RecordingContainerExecutor(ContainerMatchExecutor):
    def __init__(self) -> None:
        self.requests: list[MatchExecutionRequest] = []

    def execute(self, request: MatchExecutionRequest) -> MatchExecutionResult:
        self.requests.append(request)
        winner = request.team_a_id
        loser = request.team_b_id
        return MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome={
                "outcome": "win",
                "winner_team_id": winner,
                "score": {winner: 300, loser: 0, "draws": 0},
                "moves": {winner: "R" * 300, loser: "S" * 300},
                "rounds": [
                    {
                        "turn": turn,
                        "moves": {winner: "R", loser: "S"},
                        "winner_team_id": winner,
                    }
                    for turn in range(300)
                ],
                "faults": {winner: None, loser: None},
            },
            operational_telemetry={
                "type": "match_attempt_completed",
                "container_ids": {"a": "variable-a", "b": "variable-b"},
            },
        )


class TournamentPlanCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.directory = self.root / "tournament"
        self.store = self.root / "artifact-store"
        self.store.mkdir()
        self.catalog = load_catalog(CATALOG_PATH)
        self.plan = self._plan()
        self.plan_path = self.root / "tournament-plan.json"
        self.plan_path.write_text(json.dumps(self.plan))
        self.index = {
            "integrity": {"index_identity": "artifact-set-index-v1@" + self.digest("f")}
        }
        self.executor = RecordingContainerExecutor()
        self.stdout = StringIO()
        self.stderr = StringIO()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def digest(character: str) -> str:
        return "sha256:" + character * 64

    @staticmethod
    def identity(name: str, character: str) -> str:
        return name + "@sha256:" + character * 64

    def _artifact(self, ordinal: int) -> dict[str, Any]:
        character = chr(ord("a") + ordinal)
        environment = self.catalog.environment("python")
        runtime_definitions = json.loads(
            environment.assets["base_runtime"].content
        )
        pinned = runtime_definitions["platforms"]["linux/arm64"]
        runtime_digest = pinned["image"].rsplit("@", 1)[1]
        artifact_digest = self.digest(character)
        source_digest = self.digest(str(ordinal + 1))
        manifest = {
            "bot_artifact_manifest_format_version": "bot-artifact-manifest-v1",
            "status": "validated",
            "authority": "canonical",
            "artifact_digest": artifact_digest,
            "source_digest": source_digest,
            "runtime_digest": runtime_digest,
            "runtime": {
                "reference": pinned["image"],
                "digest": runtime_digest,
                "identity": pinned["version"] + "@" + runtime_digest,
            },
            "language": "python",
            "platform": "linux/arm64",
            "profile": INITIAL_EXECUTION_PROFILE.version,
            "entrypoint": json.loads(environment.assets["entrypoint"].content)[
                "argv"
            ],
            "build_identity": self.identity("build-v1", character),
            "validation_identity": "pending",
            "identities": {
                "source": source_digest,
                "image": artifact_digest,
                "runtime": pinned["version"] + "@" + runtime_digest,
                "wrapper": environment.assets["wrapper"].identity,
                "recipe": environment.assets["recipe"].identity,
                "entrypoint": environment.assets["entrypoint"].identity,
                "catalog": self.catalog.identity,
                "suite": (
                    "python-artifact-conformance-v1@"
                    + environment.assets["conformance"].identity.split("@", 1)[1]
                ),
                "platform": environment.assets["platform"].identity,
                "profile": INITIAL_EXECUTION_PROFILE.identity,
                "core_tool": self.identity("rps-core-tool-v1", character),
                "builder_core_tool": self.identity("rps-core-tool-v1", character),
            },
            "image": {
                "manifest_digest": artifact_digest,
                "local_image_id": self.digest("e"),
            },
            "retention": {
                "authority": artifact_digest,
                "local_image_id": self.digest("e"),
                "local_image_reference": "mutable:operational-only",
                "store": "active-docker-context",
            },
        }
        validation_basis = {
            "format": "bot-artifact-certification-v1",
            "mode": "organizer-final",
            "authority": "canonical",
            "platform": manifest["platform"],
            "profile": manifest["profile"],
            "identities": manifest["identities"],
        }
        canonical = json.dumps(
            validation_basis, sort_keys=True, separators=(",", ":")
        ).encode()
        manifest["validation_identity"] = (
            "validation-report-v1@sha256:" + hashlib.sha256(canonical).hexdigest()
        )
        return manifest

    @staticmethod
    def _canonical(manifest: dict[str, Any]) -> dict[str, Any]:
        value = json.loads(json.dumps(manifest))
        value.pop("retention")
        value["image"].pop("local_image_id")
        return value

    def _plan(self) -> dict[str, Any]:
        resources = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
        resources.pop("version")
        resources.pop("recommended_match_parallelism")
        teams = []
        for ordinal in range(4):
            manifest = self._artifact(ordinal)
            digest = manifest["artifact_digest"]
            teams.append(
                {
                    "team_id": "team-" + chr(ord("a") + ordinal),
                    "display_name": "Team " + chr(ord("A") + ordinal),
                    "roster_ready": True,
                    "selected_source": {
                        "source_digest": manifest["source_digest"]
                    },
                    "bot_artifact_manifest": manifest,
                    "canonical_artifact_identity": self._canonical(manifest),
                    "artifact_store_reference": {
                        "index_identity": "artifact-set-index-v1@" + self.digest("f"),
                        "artifact_digest": digest,
                        "platform": "linux/arm64",
                    },
                }
            )
        return {
            "tournament_plan_format_version": "tournament-plan-v1",
            "status": "draft",
            "tournament_seed": 8675309,
            "execution": {"mode": "step", "parallelism": 4},
            "catalog": {
                "version": self.catalog.version,
                "identity": self.catalog.identity,
            },
            "execution_profile": {
                "version": INITIAL_EXECUTION_PROFILE.version,
                "identity": INITIAL_EXECUTION_PROFILE.identity,
            },
            "global_resources": resources,
            "artifact_store": {
                "index_identity": "artifact-set-index-v1@" + self.digest("f")
            },
            "teams": teams,
        }

    def run_plan(
        self,
        *extra: str,
        report_override: dict[str, Any] | None = None,
    ) -> int:
        manifests = {
            team["bot_artifact_manifest"]["artifact_digest"]: team[
                "bot_artifact_manifest"
            ]
            for team in self.plan["teams"]
        }
        reports = {
            (digest, "linux/arm64"): self._report(manifest)
            for digest, manifest in manifests.items()
        }
        if report_override is not None:
            first = next(iter(reports.values()))
            first.update(report_override)
        with (
            patch("rps_runner.tournament.plan.verify_artifact_store", return_value=self.index),
            patch(
                "rps_runner.tournament.plan.load_retained_artifact_manifests",
                return_value={
                    (digest, "linux/arm64"): manifest
                    for digest, manifest in manifests.items()
                },
            ),
            patch(
                "rps_runner.tournament.plan.load_retained_validation_reports",
                return_value=reports,
            ),
            patch("rps_runner.tournament_cli.resolve_artifact", return_value=self.digest("e")),
        ):
            return main(
                [
                    "plan",
                    "--plan",
                    str(self.plan_path),
                    "--catalog",
                    str(CATALOG_PATH),
                    "--artifact-store",
                    str(self.store),
                    "--directory",
                    str(self.directory),
                    "--tournament-id",
                    "summer-cup-2026",
                    *extra,
                ],
                container_match_executor=self.executor.execute,
                stdout=self.stdout,
                stderr=self.stderr,
            )

    @staticmethod
    def _report(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "validation_report_format_version": "validation-report-v1",
            "status": "passed",
            "mode": "organizer-final",
            "authority": "canonical",
            "advisory": False,
            "canonical_tournament_eligible": True,
            "platform": manifest["platform"],
            "profile": manifest["profile"],
            "validation_identity": manifest["validation_identity"],
            "identities": manifest["identities"],
            "checks": {
                "source_validation": "passed-by-frozen-bundle",
                "networkless_build": "passed-by-verified-current-builder-record",
                "image_identity": "passed",
                "readiness": "passed",
                "clean_shutdown": "passed",
                "protocol_transcripts": "passed",
                "same_seed_behavior": "passed",
                "timing_and_stream_limits": "passed",
                "resource_enforcement": "passed-through-profile",
                "isolation": "passed-through-profile",
                "diagnostics": "passed",
                "complete_smoke_match": "passed",
                "practice_match_result_gate": "not-applicable",
            },
        }

    def test_public_plan_command_seals_exact_identities_and_steps_one_match(self) -> None:
        code = self.run_plan()

        self.assertEqual(code, 0, self.stderr.getvalue())
        self.assertEqual(len(self.executor.requests), 1)
        manifest = load_manifest(self.directory).manifest
        self.assertEqual(manifest["executor_kind"], "container")
        self.assertEqual(manifest["catalog_identity"], self.catalog.identity)
        self.assertEqual(
            manifest["artifact_store_index_identity"],
            self.index["integrity"]["index_identity"],
        )
        self.assertEqual(
            manifest["roster"][0]["bot_artifact"],
            self.plan["teams"][0]["canonical_artifact_identity"],
        )
        self.assertEqual(len(load_competition_records(self.directory)), 1)
        telemetry = load_operational_telemetry(self.directory)
        completed = next(item for item in telemetry if "container_ids" in item)
        self.assertEqual(completed["container_ids"]["a"], "variable-a")
        record_bytes = (self.directory / "records" / "00000001.json").read_bytes()
        self.assertNotIn(b"container", record_bytes.lower())
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["fixtures"][0]["status"], "in_progress")

    def test_creation_only_resolves_every_image_without_executing_a_match(self) -> None:
        code = self.run_plan("--create-only")

        self.assertEqual(code, 0, self.stderr.getvalue())
        self.assertEqual(self.executor.requests, [])
        self.assertEqual(load_competition_records(self.directory), [])
        self.assertIsNotNone(load_scoreboard_projection(self.directory))

    def test_resume_uses_sealed_manifest_when_draft_plan_is_unavailable(self) -> None:
        code = self.run_plan("--create-only")
        self.assertEqual(code, 0, self.stderr.getvalue())
        self.plan_path.unlink()
        self.stdout = StringIO()
        self.stderr = StringIO()
        manifests = {
            team["bot_artifact_manifest"]["artifact_digest"]: team[
                "bot_artifact_manifest"
            ]
            for team in self.plan["teams"]
        }
        reports = {
            (digest, "linux/arm64"): self._report(manifest)
            for digest, manifest in manifests.items()
        }

        with (
            patch(
                "rps_runner.tournament.plan.verify_artifact_store",
                return_value=self.index,
            ),
            patch(
                "rps_runner.tournament.plan.load_retained_artifact_manifests",
                return_value={
                    (digest, "linux/arm64"): manifest
                    for digest, manifest in manifests.items()
                },
            ),
            patch(
                "rps_runner.tournament.plan.load_retained_validation_reports",
                return_value=reports,
            ),
            patch(
                "rps_runner.tournament_cli.resolve_artifact",
                return_value=self.digest("e"),
            ) as resolve,
        ):
            code = main(
                [
                    "plan",
                    "--catalog",
                    str(CATALOG_PATH),
                    "--artifact-store",
                    str(self.store),
                    "--directory",
                    str(self.directory),
                    "--tournament-id",
                    "summer-cup-2026",
                ],
                container_match_executor=self.executor.execute,
                stdout=self.stdout,
                stderr=self.stderr,
            )

        self.assertEqual(code, 0, self.stderr.getvalue())
        self.assertEqual(len(self.executor.requests), 1)
        self.assertEqual(resolve.call_count, 4)
        self.assertIn("Tournament: resumed", self.stdout.getvalue())

    def test_resume_rejects_an_artifact_store_with_another_index_identity(self) -> None:
        self.assertEqual(self.run_plan("--create-only"), 0)
        self.index["integrity"]["index_identity"] = (
            "artifact-set-index-v1@" + self.digest("9")
        )
        self.stderr = StringIO()

        code = self.run_plan()

        self.assertEqual(code, 2)
        self.assertIn("artifact-store index identity mismatch", self.stderr.getvalue())
        self.assertEqual(self.executor.requests, [])

    def test_resume_rejects_a_stale_catalog_identity(self) -> None:
        self.assertEqual(self.run_plan("--create-only"), 0)
        manifest = thaw_json(load_manifest(self.directory).manifest)
        (self.directory / "manifest.json").unlink()
        seal_manifest(
            self.directory,
            manifest
            | {"catalog_identity": self.identity("catalog-v1", "9")},
        )
        self.stderr = StringIO()

        code = self.run_plan()

        self.assertEqual(code, 2)
        self.assertIn("catalog", self.stderr.getvalue())
        self.assertEqual(self.executor.requests, [])

    def test_resume_rejects_a_stale_execution_profile_identity(self) -> None:
        self.assertEqual(self.run_plan("--create-only"), 0)
        manifest = thaw_json(load_manifest(self.directory).manifest)
        (self.directory / "manifest.json").unlink()
        seal_manifest(
            self.directory,
            manifest | {"startup_timeout_seconds": 99.0},
        )
        self.stderr = StringIO()

        code = self.run_plan()

        self.assertEqual(code, 2)
        self.assertIn("execution-profile", self.stderr.getvalue())
        self.assertEqual(self.executor.requests, [])

    def test_resume_rejects_a_changed_final_validation_identity(self) -> None:
        self.assertEqual(self.run_plan("--create-only"), 0)
        self.stderr = StringIO()

        code = self.run_plan(
            report_override={"validation_identity": self.identity("validation-v1", "9")}
        )

        self.assertEqual(code, 2)
        self.assertIn("final validation identity mismatch", self.stderr.getvalue())
        self.assertEqual(self.executor.requests, [])

    def test_one_step_preserves_a_continuous_plan_as_the_current_mode(self) -> None:
        self.plan["execution"]["mode"] = "continuous"
        self.plan_path.write_text(json.dumps(self.plan))

        code = self.run_plan()

        self.assertEqual(code, 0, self.stderr.getvalue())
        self.assertEqual(len(self.executor.requests), 1)
        self.assertIn("Current Mode: Continuous", self.stdout.getvalue())

    def test_rejects_stale_profile_before_sealing(self) -> None:
        self.plan["global_resources"]["memory_limit_bytes"] += 1
        self.plan_path.write_text(json.dumps(self.plan))

        code = self.run_plan()

        self.assertEqual(code, 2)
        self.assertIn("profile identity is stale", self.stderr.getvalue())
        self.assertFalse(self.directory.exists())

    def test_rejects_noncanonical_final_validation_before_sealing(self) -> None:
        code = self.run_plan(report_override={"authority": "advisory"})

        self.assertEqual(code, 2)
        self.assertIn("final validation authority is invalid", self.stderr.getvalue())
        self.assertFalse(self.directory.exists())

    def test_rejects_unvalidated_wrong_platform_and_digest_mismatch(self) -> None:
        mutations = (
            ("status", "built", "status is invalid"),
            ("platform", "linux/amd64", "platform is invalid"),
            ("artifact_digest", self.digest("9"), "canonical Bot Artifact identity mismatch"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field):
                self.stderr = StringIO()
                manifest = self.plan["teams"][0]["bot_artifact_manifest"]
                original = manifest[field]
                original_canonical = self.plan["teams"][0][
                    "canonical_artifact_identity"
                ]
                manifest[field] = value
                if field != "artifact_digest":
                    self.plan["teams"][0][
                        "canonical_artifact_identity"
                    ] = self._canonical(manifest)
                self.plan_path.write_text(json.dumps(self.plan))

                code = self.run_plan()

                self.assertEqual(code, 2)
                self.assertIn(message, self.stderr.getvalue())
                self.assertFalse(self.directory.exists())
                manifest[field] = original
                self.plan["teams"][0][
                    "canonical_artifact_identity"
                ] = original_canonical

    def test_host_executor_cannot_create_an_official_tournament(self) -> None:
        manifests = {
            team["bot_artifact_manifest"]["artifact_digest"]: team[
                "bot_artifact_manifest"
            ]
            for team in self.plan["teams"]
        }
        reports = {
            (digest, "linux/arm64"): self._report(manifest)
            for digest, manifest in manifests.items()
        }
        with (
            patch("rps_runner.tournament.plan.verify_artifact_store", return_value=self.index),
            patch(
                "rps_runner.tournament.plan.load_retained_artifact_manifests",
                return_value={
                    (digest, "linux/arm64"): manifest
                    for digest, manifest in manifests.items()
                },
            ),
            patch(
                "rps_runner.tournament.plan.load_retained_validation_reports",
                return_value=reports,
            ),
            patch("rps_runner.tournament_cli.resolve_artifact", return_value=self.digest("e")),
        ):
            code = main(
                [
                    "plan",
                    "--plan",
                    str(self.plan_path),
                    "--catalog",
                    str(CATALOG_PATH),
                    "--artifact-store",
                    str(self.store),
                    "--directory",
                    str(self.directory),
                    "--tournament-id",
                    "summer-cup-2026",
                ],
                container_match_executor=lambda _request: None,
                stdout=self.stdout,
                stderr=self.stderr,
            )

        self.assertEqual(code, 2)
        self.assertIn("requires the container executor", self.stderr.getvalue())
        self.assertFalse((self.directory / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
