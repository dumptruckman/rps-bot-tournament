from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from rps_runner.batch_plan_cli import BatchOperations, main
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import load_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


def digest(character: str) -> str:
    return "sha256:" + character * 64


class FakeBatchPipeline:
    def __init__(self, failing_team: str | None = None) -> None:
        self.failing_team = failing_team
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def freeze(
        self,
        source: Path,
        bundle: Path,
        _catalog: object,
        _environment: object,
    ) -> dict[str, object]:
        if source.is_symlink():
            raise ValueError("selected source directory must not be a symbolic link")
        bundle.mkdir(parents=True)
        target = bundle / "source"
        target.mkdir()
        content = (source / "strategy.py").read_text()
        source_files = []
        for source_file in sorted(source.rglob("*")):
            if source_file.is_file():
                relative = source_file.relative_to(source)
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source_file.read_bytes())
                source_files.append(relative.as_posix())
        source_digest = digest(content[0].lower())
        manifest = {
            "bundle_format_version": "source-bundle-v1",
            "source_digest": source_digest,
            "files": source_files,
        }
        (bundle / "source-bundle.json").write_text(json.dumps(manifest))
        return manifest

    def build(
        self,
        bundle: Path,
        candidate: Path,
        _catalog: object,
        _platform: str,
    ) -> dict[str, object]:
        team_id = candidate.parent.name
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            time.sleep(0.02)
            if team_id == self.failing_team:
                raise ValueError("synthetic build failure")
            candidate.mkdir()
            source_digest = json.loads(
                (bundle / "source-bundle.json").read_text()
            )["source_digest"]
            character = team_id[-1]
            manifest = {
                "artifact_digest": digest(character),
                "source_digest": source_digest,
                "platform": "linux/arm64",
            }
            (candidate / "artifact-candidate.json").write_text(json.dumps(manifest))
            return manifest
        finally:
            with self.lock:
                self.active -= 1

    def certify(
        self,
        candidate: Path,
        certification: Path,
        _catalog: object,
        _inputs: object,
    ) -> dict[str, object]:
        certification.mkdir()
        candidate_manifest = json.loads(
            (candidate / "artifact-candidate.json").read_text()
        )
        validation_identity = "validation-report-v1@" + digest(
            candidate.parent.name[-1]
        )
        manifest = {
            "bot_artifact_manifest_format_version": "bot-artifact-manifest-v1",
            "status": "validated",
            "authority": "canonical",
            **candidate_manifest,
            "language": "python",
            "environment": "python",
            "profile": "docker-execution-v1",
            "validation_identity": validation_identity,
            "identities": {
                "catalog": load_catalog(CATALOG).identity,
                "profile": INITIAL_EXECUTION_PROFILE.identity,
            },
            "image": {
                "manifest_digest": candidate_manifest["artifact_digest"],
                "local_image_id": digest("e"),
            },
            "retention": {
                "local_image_reference": "team:mutable",
                "store": "active-docker-context",
            },
        }
        (certification / "bot-artifact-manifest.json").write_text(json.dumps(manifest))
        (certification / "validation-report.json").write_text(
            json.dumps({"validation_identity": validation_identity})
        )
        return manifest

    @staticmethod
    def preserve(_store: Path, selections: list[object]) -> dict[str, object]:
        return {
            "integrity": {"index_identity": "artifact-set-index-v1@" + digest("f")},
            "artifacts": [
                {
                    "artifact_digest": json.loads(
                        (selection.candidate / "artifact-candidate.json").read_text()
                    )["artifact_digest"],
                    "platform": "linux/arm64",
                }
                for selection in selections
            ],
        }

    @property
    def operations(self) -> BatchOperations:
        return BatchOperations(self.freeze, self.build, self.certify, self.preserve)


class BatchPlanCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def source(self, name: str, marker: str) -> Path:
        source = self.directory / name
        source.mkdir()
        (source / "strategy.py").write_text(marker + " strategy\n")
        return source

    def mapping(self, teams: list[dict[str, object]]) -> Path:
        path = self.directory / "teams.json"
        path.write_text(json.dumps({"teams": teams}))
        return path

    def run_batch(
        self, mapping: Path, pipeline: FakeBatchPipeline, *, jobs: int = 2
    ) -> tuple[int, Path]:
        output = self.directory / "output"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "--teams",
                    str(mapping),
                    "--catalog",
                    str(CATALOG),
                    "--environment",
                    "python",
                    "--output",
                    str(output),
                    "--tournament-seed",
                    "8675309",
                    "--execution-mode",
                    "continuous",
                    "--jobs",
                    str(jobs),
                ],
                operations=pipeline.operations,
            )
        return code, output

    def test_builds_concurrently_and_writes_a_stably_ordered_plan(self) -> None:
        teams = [
            {
                "team_id": team_id,
                "display_name": "Team " + team_id[-1],
                "source_directory": str(
                    self.source(team_id, team_id[-1].upper())
                ),
            }
            for team_id in ("team-d", "team-b", "team-a", "team-c")
        ]
        pipeline = FakeBatchPipeline()

        code, output = self.run_batch(self.mapping(teams), pipeline, jobs=2)

        self.assertEqual(code, 0)
        self.assertEqual(pipeline.maximum_active, 2)
        plan = json.loads((output / "tournament-plan.json").read_text())
        self.assertEqual(
            [team["team_id"] for team in plan["teams"]],
            ["team-a", "team-b", "team-c", "team-d"],
        )
        self.assertEqual(plan["tournament_seed"], 8675309)
        self.assertEqual(plan["execution"], {"mode": "continuous", "parallelism": 4})
        self.assertEqual(plan["catalog"]["identity"], load_catalog(CATALOG).identity)
        self.assertEqual(
            plan["execution_profile"]["identity"],
            INITIAL_EXECUTION_PROFILE.identity,
        )
        self.assertEqual(plan["global_resources"]["memory_limit_bytes"], 268_435_456)
        self.assertTrue(all(team["roster_ready"] for team in plan["teams"]))
        serialized = json.dumps(plan)
        self.assertNotIn(str(self.directory), serialized)
        self.assertNotIn("github", serialized.lower())
        artifact = plan["teams"][0]
        self.assertEqual(
            artifact["bot_artifact_manifest"]["retention"][
                "local_image_reference"
            ],
            "team:mutable",
        )
        canonical = json.dumps(artifact["canonical_artifact_identity"])
        self.assertNotIn("mutable", canonical)
        self.assertNotIn("local_image_id", canonical)
        self.assertNotIn("active-docker-context", canonical)
        report = json.loads((output / "batch-report.json").read_text())
        self.assertEqual(report["operational_limit"], 2)
        self.assertEqual(
            [item["team_id"] for item in report["teams"]],
            ["team-a", "team-b", "team-c", "team-d"],
        )

    def test_preserves_challenger_roles_and_defaults_competitors(self) -> None:
        teams = [
            {
                "team_id": team_id,
                "display_name": "Team " + team_id[-1],
                "source_directory": str(
                    self.source(team_id, team_id[-1].upper())
                ),
                **({"role": "challenger"} if team_id == "team-d" else {}),
            }
            for team_id in ("team-a", "team-b", "team-c", "team-d")
        ]

        code, output = self.run_batch(
            self.mapping(teams), FakeBatchPipeline(), jobs=2
        )

        self.assertEqual(code, 0)
        plan = json.loads((output / "tournament-plan.json").read_text())
        self.assertEqual(
            {team["team_id"]: team["role"] for team in plan["teams"]},
            {
                "team-a": "competitor",
                "team-b": "competitor",
                "team-c": "competitor",
                "team-d": "challenger",
            },
        )

    def test_rejects_an_invalid_team_role(self) -> None:
        for invalid_role in ("spectator", None):
            with self.subTest(role=invalid_role):
                teams = [
                    {
                        "team_id": team_id,
                        "display_name": team_id,
                        "source_directory": str(
                            self.source(
                                team_id + str(invalid_role),
                                team_id[-1].upper(),
                            )
                        ),
                        **(
                            {"role": invalid_role}
                            if team_id == "team-d"
                            else {}
                        ),
                    }
                    for team_id in ("team-a", "team-b", "team-c", "team-d")
                ]

                code, output = self.run_batch(
                    self.mapping(teams), FakeBatchPipeline()
                )

                self.assertEqual(code, 2)
                self.assertFalse(output.exists())

    def test_reports_failures_without_writing_a_roster_ready_plan(self) -> None:
        teams = [
            {
                "team_id": team_id,
                "display_name": team_id,
                "source_directory": str(
                    self.source(team_id, team_id[-1].upper())
                ),
            }
            for team_id in ("team-a", "team-b", "team-c", "team-d")
        ]

        code, output = self.run_batch(self.mapping(teams), FakeBatchPipeline("team-c"))

        self.assertEqual(code, 2)
        self.assertFalse((output / "tournament-plan.json").exists())
        report = json.loads((output / "batch-report.json").read_text())
        by_team = {item["team_id"]: item for item in report["teams"]}
        self.assertEqual(by_team["team-c"]["status"], "failed")
        self.assertIn("synthetic build failure", by_team["team-c"]["error"])
        self.assertEqual(by_team["team-a"]["status"], "validated")

    def test_rejects_a_symbolic_link_as_the_selected_source_root(self) -> None:
        actual = self.source("actual-team-a", "A")
        linked = self.directory / "team-a-link"
        linked.symlink_to(actual, target_is_directory=True)
        teams = [
            {
                "team_id": "team-a",
                "display_name": "team-a",
                "source_directory": str(linked),
            },
            *[
                {
                    "team_id": team_id,
                    "display_name": team_id,
                    "source_directory": str(
                        self.source(team_id, team_id[-1].upper())
                    ),
                }
                for team_id in ("team-b", "team-c", "team-d")
            ],
        ]

        code, output = self.run_batch(
            self.mapping(teams), FakeBatchPipeline()
        )

        self.assertEqual(code, 2)
        report = json.loads((output / "batch-report.json").read_text())
        by_team = {item["team_id"]: item for item in report["teams"]}
        self.assertEqual(by_team["team-a"]["status"], "failed")
        self.assertIn("symbolic link", by_team["team-a"]["error"])
        self.assertFalse((output / "tournament-plan.json").exists())

    def test_repair_retains_original_diff_and_final_identities(self) -> None:
        original = self.source("team-a-original", "A")
        repaired = self.source("team-a-repaired", "Z")
        repair_resources = repaired / "resources"
        repair_resources.mkdir()
        (repair_resources / "empty.txt").write_bytes(b"")
        teams = [
            {
                "team_id": "team-a",
                "display_name": "Team A",
                "source_directory": str(original),
                "repair": {
                    "source_directory": str(repaired),
                    "explanation": "Use a portable import on ARM64.",
                },
            },
            *[
                {
                    "team_id": team_id,
                    "display_name": team_id,
                    "source_directory": str(
                        self.source(team_id, team_id[-1].upper())
                    ),
                }
                for team_id in ("team-b", "team-c", "team-d")
            ],
        ]

        code, output = self.run_batch(self.mapping(teams), FakeBatchPipeline())

        self.assertEqual(code, 0)
        plan = json.loads((output / "tournament-plan.json").read_text())
        repair = plan["teams"][0]["selected_source"]["repair"]
        self.assertEqual(repair["explanation"], "Use a portable import on ARM64.")
        self.assertEqual(repair["original_source_digest"], digest("a"))
        self.assertEqual(repair["replacement_source_digest"], digest("z"))
        self.assertIn("-A strategy", repair["diff"])
        self.assertIn("+Z strategy", repair["diff"])
        self.assertIn("+++ b/resources/empty.txt", repair["diff"])
        self.assertRegex(repair["diff_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            repair["final_validation_identity"],
            plan["teams"][0]["bot_artifact_manifest"]["validation_identity"],
        )
        self.assertTrue(
            (
                output
                / "teams"
                / "team-a"
                / "original-source"
                / "source"
                / "strategy.py"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
