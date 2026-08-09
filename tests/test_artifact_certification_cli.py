from __future__ import annotations

import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from rps_runner.certification_cli import main
from rps_runner.language_environment import load_catalog
from rps_runner.language_environment import SourceValidationError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


class ArtifactCertificationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def candidate(self, *, platform: str = "linux/amd64") -> Path:
        candidate = self.directory / "candidate"
        candidate.mkdir()
        manifest = {
            "artifact_candidate_format_version": "artifact-candidate-v1",
            "status": "suite-candidate",
            "source_digest": "sha256:" + "1" * 64,
            "artifact_digest": "sha256:" + "2" * 64,
            "build_identity": "build-v1@sha256:" + "3" * 64,
            "runtime_digest": "sha256:" + "4" * 64,
            "runtime": {
                "reference": "python@sha256:" + "4" * 64,
                "digest": "sha256:" + "4" * 64,
                "identity": "python-runtime-v1@sha256:" + "4" * 64,
            },
            "language": "python",
            "platform": platform,
            "entrypoint": ["python3", "-I", "/opt/rps/wrapper.py"],
            "identities": {
                "catalog": "catalog-v1@sha256:" + "5" * 64,
                "core_tool": "core-v1@sha256:" + "6" * 64,
                "entrypoint": "entrypoint-v1@sha256:" + "7" * 64,
                "language_environment": "python-v1@sha256:" + "8" * 64,
                "platform": "platform-v1@sha256:" + "9" * 64,
                "recipe": "recipe-v1@sha256:" + "a" * 64,
                "suite_candidate": "python-conformance-v1@sha256:" + "b" * 64,
                "wrapper": "wrapper-v1@sha256:" + "c" * 64,
            },
            "image": {
                "manifest_digest": "sha256:" + "2" * 64,
                "local_image_id": "sha256:" + "d" * 64,
            },
            "retention": {
                "authority": "sha256:" + "2" * 64,
                "local_image_id": "sha256:" + "d" * 64,
                "local_image_reference": "candidate:mutable",
                "store": "active-docker-context",
            },
        }
        (candidate / "artifact-candidate.json").write_text(json.dumps(manifest))
        return candidate

    def catalog_candidate(self, *, platform: str = "linux/amd64") -> Path:
        candidate = self.candidate(platform=platform)
        manifest_path = candidate / "artifact-candidate.json"
        manifest = json.loads(manifest_path.read_text())
        catalog = load_catalog(CATALOG)
        environment = catalog.environment("python")
        manifest["identities"].update(
            {
                "catalog": catalog.identity,
                "entrypoint": environment.assets["entrypoint"].identity,
                "language_environment": environment.descriptor_identity,
                "platform": environment.assets["platform"].identity,
                "recipe": environment.assets["recipe"].identity,
                "suite_candidate": environment.assets["conformance"].identity,
                "wrapper": environment.assets["wrapper"].identity,
            }
        )
        manifest_path.write_text(json.dumps(manifest))
        return candidate

    def run_certifier(self, candidate: Path, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.certification_cli",
                "--catalog",
                str(CATALOG),
                "--candidate",
                str(candidate),
                "--mode",
                mode,
                "--platform",
                "linux/amd64",
                "--profile",
                "docker-execution-v1",
                "--output",
                str(self.directory / "certified"),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_organizer_final_rejects_non_arm64_before_execution(self) -> None:
        completed = self.run_certifier(self.candidate(), "organizer-final")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("organizer-final requires platform 'linux/arm64'", completed.stderr)
        self.assertFalse((self.directory / "certified").exists())

    def test_advisory_report_records_practice_artifacts_without_gating_on_winner(self) -> None:
        candidate = self.catalog_candidate()
        output = self.directory / "certified"
        smoke = {
            "attempts": 2,
            "same_seed_repeated": True,
            "scheduled_turns": 300,
            "outcome_observed_not_gated": {"winner_team_id": "practice-fixed"},
            "practice_artifacts": {
                name: {"status": "passed", "candidate_won": False}
                for name in ("fixed-move", "random", "copycat", "protocol-test")
            },
            "diagnostic_fixtures": {
                name: {"status": "passed", "actionable_diagnostic": name}
                for name in (
                    "syntax-build",
                    "import-time",
                    "nondeterministic",
                    "protocol-fault",
                    "slow-response",
                    "memory",
                    "process",
                    "filesystem",
                    "premature-output",
                )
            },
        }

        with (
            mock.patch("rps_runner.artifact_certification._verify_candidate_identities"),
            mock.patch("rps_runner.artifact_certification._verify_frozen_source"),
            mock.patch(
                "rps_runner.artifact_certification._inspect_image",
                return_value={
                    "Id": "sha256:" + "d" * 64,
                    "Os": "linux",
                    "Architecture": "amd64",
                    "Config": {
                        "Entrypoint": ["python3", "-I", "/opt/rps/wrapper.py"]
                    },
                },
            ) as image_inspect,
            mock.patch(
                "rps_runner.artifact_certification._run_smoke_matches",
                return_value=smoke,
            ),
            redirect_stdout(io.StringIO()),
        ):
            code = main(
                [
                    "--catalog",
                    str(CATALOG),
                    "--candidate",
                    str(candidate),
                    "--mode",
                    "github-advisory",
                    "--platform",
                    "linux/amd64",
                    "--profile",
                    "docker-execution-v1",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(code, 0)
        image_inspect.assert_called_once_with("sha256:" + "d" * 64)
        report = json.loads((output / "validation-report.json").read_text())
        self.assertTrue(report["advisory"])
        self.assertFalse(report["canonical_tournament_eligible"])
        self.assertEqual(
            set(report["smoke_match"]["practice_artifacts"]),
            {"fixed-move", "random", "copycat", "protocol-test"},
        )
        self.assertEqual(report["checks"]["practice_match_result_gate"], "not-applicable")
        self.assertIn("insufficient", report["host_process_evidence"])

    def test_source_validation_failure_is_an_actionable_conformance_diagnostic(self) -> None:
        diagnostics = io.StringIO()
        with (
            mock.patch(
                "rps_runner.certification_cli.certify_artifact_candidate",
                side_effect=SourceValidationError(
                    "strategy.py", "participant_contract", "invalid syntax"
                ),
            ),
            redirect_stderr(diagnostics),
        ):
            code = main(
                [
                    "--catalog",
                    str(CATALOG),
                    "--candidate",
                    str(self.directory / "candidate"),
                    "--mode",
                    "github-advisory",
                    "--platform",
                    "linux/amd64",
                    "--profile",
                    "docker-execution-v1",
                    "--output",
                    str(self.directory / "certified"),
                ]
            )

        self.assertEqual(code, 2)
        self.assertIn("conformance failure", diagnostics.getvalue())
        self.assertIn("strategy.py", diagnostics.getvalue())


if __name__ == "__main__":
    unittest.main()
