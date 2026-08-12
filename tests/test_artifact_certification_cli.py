from __future__ import annotations

import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from rps_runner.certification_cli import main
from rps_runner.artifact_certification import (
    _conformance_match_request,
    _execute_conforming_match,
    _run_diagnostic_artifacts,
    _run_smoke_matches,
)
from rps_runner.tournament.match_executor import MatchExecutionResult
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
            "build_toolchain": {
                "reference": "python@sha256:" + "4" * 64,
                "digest": "sha256:" + "4" * 64,
                "identity": "python-runtime-v1@sha256:" + "4" * 64,
            },
            "language": "python",
            "environment": "python",
            "platform": platform,
            "entrypoint": ["python3", "-I", "/opt/rps/wrapper.py"],
            "identities": {
                "catalog": "catalog-v1@sha256:" + "5" * 64,
                "build_toolchain": "build-toolchain-v1@sha256:" + "5" * 64,
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
                "build_toolchain": environment.assets["build_toolchain"].identity,
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

    def test_successful_match_fault_slots_do_not_fail_certification(self) -> None:
        executor = mock.Mock()
        executor.execute.return_value = MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome={
                "status": "completed",
                "faults": {"candidate-a": None, "candidate-b": None},
            },
            operational_telemetry={},
        )

        outcome = _execute_conforming_match(executor, mock.sentinel.request, "smoke")

        self.assertEqual(outcome["status"], "completed")

    def test_parallel_certifications_have_distinct_match_ownership(self) -> None:
        first = _conformance_match_request(
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            8675309,
            1,
            namespace="certification-a",
        )
        second = _conformance_match_request(
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            8675309,
            1,
            namespace="certification-b",
        )

        self.assertNotEqual(first.tournament_id, second.tournament_id)
        self.assertEqual(first.match_id, second.match_id)

    def test_parallel_certifications_serialize_resource_diagnostics(self) -> None:
        fixtures = {
            name: {"artifact_digest": "sha256:" + character * 64}
            for name, character in zip(
                (
                    "import-time",
                    "protocol-fault",
                    "slow-response",
                    "memory",
                    "premature-output",
                    "process",
                    "filesystem",
                    "nondeterministic",
                ),
                "12345678",
            )
        }
        fixed = {"artifact_digest": "sha256:" + "9" * 64}
        active = 0
        maximum_active = 0
        nondeterministic_call = 0
        guard = threading.Lock()
        start = threading.Barrier(2)
        fault_kinds = {
            "import-time": "unexpected_exit",
            "protocol-fault": "invalid_response",
            "slow-response": "timeout",
            "memory": "resource_oom",
            "premature-output": "unexpected_output",
        }

        def execute(_executor: object, _request: object, name: str) -> dict[str, object]:
            nonlocal active, maximum_active, nondeterministic_call
            if name in {"memory", "process", "filesystem"}:
                with guard:
                    active += 1
                    maximum_active = max(maximum_active, active)
                time.sleep(0.03)
                with guard:
                    active -= 1
            if name == "nondeterministic":
                with guard:
                    nondeterministic_call += 1
                    move = str(nondeterministic_call)
                return {"moves": {"candidate-a": move}, "faults": {}}
            kind = fault_kinds.get(name)
            fault = {"kind": kind, "turn": 0} if kind is not None else None
            return {"faults": {"candidate-a": fault}}

        def run(namespace: str) -> object:
            start.wait()
            return _run_diagnostic_artifacts(
                mock.sentinel.executor,
                fixtures,
                fixed,
                namespace=namespace,
            )

        with (
            mock.patch(
                "rps_runner.artifact_certification._execute_fixture_match",
                side_effect=execute,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            list(executor.map(run, ("certification-a", "certification-b")))

        self.assertEqual(maximum_active, 1)

    def test_parallel_certifications_serialize_live_conformance_suites(self) -> None:
        active = 0
        maximum_active = 0
        guard = threading.Lock()
        start = threading.Barrier(2)

        def execute(*_args: object, **_kwargs: object) -> dict[str, object]:
            nonlocal active, maximum_active
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with guard:
                active -= 1
            return {}

        def run(_ordinal: int) -> object:
            start.wait()
            return _run_smoke_matches(
                {}, mock.sentinel.catalog, "linux/arm64"
            )

        with (
            mock.patch(
                "rps_runner.artifact_certification._run_smoke_matches_exclusively",
                side_effect=execute,
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            list(executor.map(run, (1, 2)))

        self.assertEqual(maximum_active, 1)

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

    def test_certification_preserves_the_candidate_selected_environment(self) -> None:
        candidate = self.catalog_candidate()
        manifest_path = candidate / "artifact-candidate.json"
        manifest = json.loads(manifest_path.read_text())
        catalog = load_catalog(CATALOG)
        environment = catalog.environment("internal-shell")
        manifest["language"] = environment.language
        manifest["environment"] = environment.name
        manifest["entrypoint"] = ["/bin/sh", "/opt/rps/wrapper.sh"]
        manifest["identities"].update(
            {
                "language_environment": environment.descriptor_identity,
                "build_toolchain": environment.assets["build_toolchain"].identity,
                "suite_candidate": environment.assets["conformance"].identity,
            }
        )
        manifest_path.write_text(json.dumps(manifest))
        smoke = {
            "attempts": 2,
            "same_seed_repeated": True,
            "scheduled_turns": 300,
            "outcome_observed_not_gated": {},
            "practice_artifacts": {},
            "diagnostic_fixtures": {},
        }
        output = self.directory / "shell-certified"

        with (
            mock.patch("rps_runner.artifact_certification._verify_candidate_identities"),
            mock.patch("rps_runner.artifact_certification._verify_frozen_source"),
            mock.patch("rps_runner.artifact_certification._verify_image"),
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
        certified = json.loads((output / "bot-artifact-manifest.json").read_text())
        report = json.loads((output / "validation-report.json").read_text())
        self.assertEqual(certified["language"], "shell-fixture")
        self.assertEqual(
            certified["identities"]["language_environment"],
            environment.descriptor_identity,
        )
        self.assertTrue(
            report["identities"]["suite"].startswith(
                "internal-shell-artifact-conformance-v1@sha256:"
            )
        )


if __name__ == "__main__":
    unittest.main()
