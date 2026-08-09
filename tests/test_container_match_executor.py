from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest

from rps_runner.engine.container_session import ContainerOperations
from rps_runner.tournament.match_executor import (
    ContainerMatchExecutor,
    LocalMatchExecutor,
)
from tests.test_tournament_match_executor import checking_bot, request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FAKE_DOCKER = PROJECT_ROOT / "tests" / "fixtures" / "fake_docker.py"
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


class ContainerMatchExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.state = Path(self.temporary.name)
        self.previous_state = os.environ.get("FAKE_DOCKER_STATE")
        os.environ["FAKE_DOCKER_STATE"] = str(self.state)

    def tearDown(self) -> None:
        if self.previous_state is None:
            os.environ.pop("FAKE_DOCKER_STATE", None)
        else:
            os.environ["FAKE_DOCKER_STATE"] = self.previous_state
        self.temporary.cleanup()

    def executor(self, images: dict[str, str]) -> ContainerMatchExecutor:
        return ContainerMatchExecutor(
            lambda team_id, digest: images[team_id],
            operations=ContainerOperations(
                docker_command=(sys.executable, str(FAKE_DOCKER)),
                startup_timeout_seconds=0.3,
                command_timeout_seconds=0.3,
                shutdown_timeout_seconds=0.3,
            ),
        )

    def calls(self) -> list[dict[str, object]]:
        log = self.state / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def test_ready_containers_start_together_and_match_host_outcome(self) -> None:
        container = self.executor(
            {"red-team": "barrier-r", "blue-team": "barrier-s"}
        ).execute(request())
        host = LocalMatchExecutor(
            lambda team_id, digest: checking_bot(
                "R" * 300 if team_id == "red-team" else "S" * 300,
                111 if team_id == "red-team" else 222,
            )
        ).execute(request())

        self.assertFalse(container.infrastructure_failure)
        self.assertEqual(container.competitive_outcome, host.competitive_outcome)
        starts = [call for call in self.calls() if call["command"] == "start"]
        self.assertEqual(len(starts), 2)
        self.assertLess(abs(starts[0]["time_ns"] - starts[1]["time_ns"]), 100_000_000)
        self.assertEqual(
            sorted(call["command"] for call in self.calls()).count("rm"), 2
        )

    def test_split_readiness_is_removed_from_bounded_artifact_stderr(self) -> None:
        result = self.executor(
            {"red-team": "diagnostic-r", "blue-team": "fixed-s"}
        ).execute(request(stderr_limit_bytes=13))

        self.assertFalse(result.infrastructure_failure)
        red = result.operational_telemetry["bots"]["red-team"]
        self.assertEqual(red["stderr"], "before\nafter\n")
        self.assertFalse(red["stderr_truncated"])
        self.assertNotIn("RPS_READY", red["stderr"])

    def test_only_wrapper_readiness_is_removed_from_artifact_stderr(self) -> None:
        result = self.executor(
            {"red-team": "repeated-marker-r", "blue-team": "fixed-s"}
        ).execute(request(stderr_limit_bytes=5))

        self.assertFalse(result.infrastructure_failure)
        red = result.operational_telemetry["bots"]["red-team"]
        self.assertEqual(red["stderr"], "RPS_R")
        self.assertTrue(red["stderr_truncated"])

    def test_unterminated_pre_readiness_stderr_stays_bounded(self) -> None:
        result = self.executor(
            {"red-team": "unterminated-diagnostic-r", "blue-team": "fixed-s"}
        ).execute(request(stderr_limit_bytes=5))

        self.assertFalse(result.infrastructure_failure)
        red = result.operational_telemetry["bots"]["red-team"]
        self.assertEqual(red["stderr"], "xxxxx")
        self.assertTrue(red["stderr_truncated"])

    def test_escaped_import_marker_is_counted_before_readiness(self) -> None:
        result = self.executor(
            {"red-team": "escaped-import-r", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertFalse(result.infrastructure_failure)
        red = result.operational_telemetry["bots"]["red-team"]
        self.assertEqual(red["stderr"], "RPS_READY_V1\n")

    def test_final_stderr_is_drained_only_by_the_readiness_capture(self) -> None:
        result = self.executor(
            {"red-team": "final-diagnostic-r", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertFalse(result.infrastructure_failure)
        red = result.operational_telemetry["bots"]["red-team"]
        self.assertEqual(red["stderr"], "final diagnostic\n")

    def test_missing_readiness_is_an_infrastructure_failure_and_cleans_up(self) -> None:
        result = self.executor(
            {"red-team": "missing-readiness", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIn(
            "readiness",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )
        self.assertEqual(
            sorted(call["command"] for call in self.calls()).count("rm"), 2
        )

    def test_early_stdout_and_exit_are_competitive_faults(self) -> None:
        for image, kind in (
            ("early-stdout", "unexpected_output"),
            ("early-exit", "unexpected_exit"),
        ):
            with self.subTest(image=image):
                result = self.executor(
                    {"red-team": image, "blue-team": "fixed-s"}
                ).execute(request())

                self.assertFalse(result.infrastructure_failure)
                self.assertEqual(result.competitive_outcome["status"], "forfeit")
                self.assertEqual(
                    result.competitive_outcome["faults"]["red-team"]["kind"],
                    kind,
                )

    def test_container_creation_failure_is_an_infrastructure_failure(self) -> None:
        result = self.executor(
            {"red-team": "create-failure", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIn(
            "Docker create failed",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )
        created = [call for call in self.calls() if call["command"] == "create"]
        removed = [call for call in self.calls() if call["command"] == "rm"]
        self.assertEqual(len(created), 2)
        self.assertEqual(len(removed), 2)

    def test_uncertain_container_creation_is_cleaned_up_by_assigned_name(self) -> None:
        for image in ("malformed-create", "timeout-create"):
            with self.subTest(image=image):
                result = self.executor(
                    {"red-team": image, "blue-team": "fixed-s"}
                ).execute(request())

                self.assertTrue(result.infrastructure_failure)
                remaining_state = [
                    path.name
                    for path in self.state.iterdir()
                    if path.name != "calls.jsonl"
                ]
                self.assertEqual(remaining_state, [])

    def test_container_attachment_failure_is_an_infrastructure_failure(self) -> None:
        result = self.executor(
            {"red-team": "attach-failure", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIn(
            "Docker attach failed",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )
        self.assertEqual(
            sorted(call["command"] for call in self.calls()).count("rm"), 2
        )

@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class ContainerMatchDockerIntegrationTests(unittest.TestCase):
    def build_candidate(
        self, directory: Path, name: str, move: str, platform: str
    ) -> dict[str, Any]:
        source = directory / (name + "-source")
        source.mkdir()
        (source / "strategy.py").write_text(
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            f"    return {move!r}\n"
        )
        bundle = directory / (name + "-bundle")
        validation = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.source_cli",
                "--catalog",
                str(CATALOG),
                "--environment",
                "python",
                "--source",
                str(source),
                "--bundle",
                str(bundle),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(validation.returncode, 0, validation.stderr)
        candidate = directory / (name + "-candidate")
        build = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.artifact_cli",
                "--catalog",
                str(CATALOG),
                "--bundle",
                str(bundle),
                "--platform",
                platform,
                "--candidate",
                str(candidate),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        self.assertEqual(build.returncode, 0, build.stderr)
        return json.loads(build.stdout)

    def test_builder_candidates_play_an_equivalent_container_match(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
            candidates = {
                "red-team": self.build_candidate(
                    Path(temporary_name), "red", "R", platform
                ),
                "blue-team": self.build_candidate(
                    Path(temporary_name), "blue", "S", platform
                ),
            }
            match_request = request(
                artifact_digest_a=candidates["red-team"]["artifact_digest"],
                artifact_digest_b=candidates["blue-team"]["artifact_digest"],
            )
            try:
                container = ContainerMatchExecutor(
                    lambda team_id, digest: candidates[team_id]["retention"][
                        "local_image_reference"
                    ]
                ).execute(match_request)
                host = LocalMatchExecutor(
                    lambda team_id, digest: checking_bot(
                        "R" * 300 if team_id == "red-team" else "S" * 300,
                        111 if team_id == "red-team" else 222,
                    )
                ).execute(match_request)

                self.assertFalse(container.infrastructure_failure)
                self.assertEqual(
                    container.competitive_outcome, host.competitive_outcome
                )
            finally:
                for candidate in candidates.values():
                    subprocess.run(
                        [
                            "docker",
                            "image",
                            "rm",
                            candidate["retention"]["local_image_reference"],
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )


if __name__ == "__main__":
    unittest.main()
