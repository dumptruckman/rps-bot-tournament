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
ISOLATION_STRATEGY = PROJECT_ROOT / "tests" / "fixtures" / "isolation_strategy.py"
CPU_EXHAUSTION_STRATEGY = (
    PROJECT_ROOT / "tests" / "fixtures" / "cpu_exhaustion_strategy.py"
)


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

    def test_public_match_applies_the_same_isolation_profile_to_both_positions(
        self,
    ) -> None:
        result = self.executor(
            {"red-team": "fixed-r", "blue-team": "fixed-s"}
        ).execute(request())

        self.assertFalse(result.infrastructure_failure)
        creates = [call for call in self.calls() if call["command"] == "create"]
        self.assertEqual(len(creates), 2)
        normalized: list[list[str]] = []
        for call in creates:
            arguments = list(call["arguments"])
            arguments[arguments.index("--name") + 1] = "<container>"
            for index, argument in enumerate(arguments):
                if argument == "--env" and arguments[index + 1].startswith(
                    "RPS_SEED="
                ):
                    arguments[index + 1] = "RPS_SEED=<bot-visible>"
            arguments[-1] = "<artifact>"
            normalized.append(arguments)

        self.assertEqual(normalized[0], normalized[1])
        arguments = normalized[0]
        for prohibited in (
            "--cap-add",
            "--env-file",
            "--mount",
            "--privileged",
            "--use-api-socket",
            "--volume",
        ):
            self.assertNotIn(prohibited, arguments)
        for expected in (
            ("--network", "none"),
            ("--read-only",),
            ("--user", "65532:65532"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges=true"),
            ("--pids-limit", "2"),
            ("--ulimit", "nofile=64:64"),
            ("--memory", "907"),
            ("--memory-swap", "907"),
            ("--cpus", "0.909"),
            ("--hostname", "rps-bot"),
            ("--ipc", "private"),
            ("--cgroupns", "private"),
        ):
            start = arguments.index(expected[0])
            self.assertEqual(arguments[start : start + len(expected)], list(expected))
        self.assertTrue(
            any(
                arguments[index] == "--security-opt"
                and arguments[index + 1].startswith("seccomp=")
                for index in range(len(arguments) - 1)
            )
        )
        self.assertIn("cpu=3:3", arguments)
        tmpfs = arguments[arguments.index("--tmpfs") + 1]
        self.assertEqual(
            tmpfs,
            "/tmp:rw,noexec,nosuid,nodev,size=908,mode=700,uid=65532,gid=65532",
        )
        self.assertIn(
            "/dev/shm:ro,noexec,nosuid,nodev,size=4096,mode=000", arguments
        )
        environments = [
            arguments[index + 1]
            for index, argument in enumerate(arguments)
            if argument == "--env"
        ]
        self.assertEqual(
            environments,
            [
                "LANG=C.UTF-8",
                "LC_ALL=C.UTF-8",
                "TZ=UTC",
                "HOME=/tmp",
                "TMPDIR=/tmp",
                "RPS_PROTOCOL_VERSION=1",
                "RPS_ROUNDS=300",
                "RPS_SEED=<bot-visible>",
            ],
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
        self,
        directory: Path,
        name: str,
        move: str,
        platform: str,
        *,
        strategy_source: bytes | None = None,
    ) -> dict[str, Any]:
        source = directory / (name + "-source")
        source.mkdir()
        if strategy_source is None:
            (source / "strategy.py").write_text(
                "def choose_move(turn, my_history, opponent_history, rng):\n"
                f"    return {move!r}\n"
            )
        else:
            (source / "strategy.py").write_bytes(strategy_source)
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
                cpu_limit_ms=2_000,
                cpu_quota_millis_per_second=1_000,
                memory_limit_bytes=268_435_456,
                process_limit=64,
                open_file_limit=64,
                filesystem_write_limit_bytes=16_777_216,
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

    def test_bot_artifact_cannot_escape_the_isolation_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
            candidates = {
                "red-team": self.build_candidate(
                    Path(temporary_name),
                    "isolation-probe",
                    "R",
                    platform,
                    strategy_source=ISOLATION_STRATEGY.read_bytes(),
                ),
                "blue-team": self.build_candidate(
                    Path(temporary_name), "opponent", "S", platform
                ),
                "cpu-team": self.build_candidate(
                    Path(temporary_name),
                    "cpu-exhaustion",
                    "R",
                    platform,
                    strategy_source=CPU_EXHAUSTION_STRATEGY.read_bytes(),
                ),
            }
            try:
                output = Path(temporary_name) / "isolation-match.json"
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rps_runner.cli",
                        "--container",
                        "--bot-a",
                        candidates["red-team"]["retention"]["local_image_id"],
                        "--bot-b",
                        candidates["blue-team"]["retention"]["local_image_id"],
                        "--rounds",
                        "300",
                        "--seed",
                        "333",
                        "--bot-a-seed",
                        "111",
                        "--bot-b-seed",
                        "222",
                        "--output",
                        str(output),
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(output.read_text())
                self.assertFalse(
                    result["infrastructure_failure"],
                    result["operational_telemetry"],
                )
                self.assertEqual(
                    result["competitive_outcome"]["winner_team_id"],
                    "bot-a",
                    result["operational_telemetry"],
                )
                self.assertEqual(
                    result["operational_telemetry"]["bots"]["bot-a"]["stderr"],
                    "",
                )

                cpu_output = Path(temporary_name) / "cpu-exhaustion-match.json"
                cpu_completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rps_runner.cli",
                        "--container",
                        "--bot-a",
                        candidates["cpu-team"]["retention"]["local_image_id"],
                        "--bot-b",
                        candidates["blue-team"]["retention"]["local_image_id"],
                        "--rounds",
                        "300",
                        "--seed",
                        "333",
                        "--first-move-timeout-ms",
                        "5000",
                        "--total-timeout-ms",
                        "5000",
                        "--output",
                        str(cpu_output),
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(cpu_completed.returncode, 0, cpu_completed.stderr)
                cpu_result = json.loads(cpu_output.read_text())
                self.assertEqual(
                    cpu_result["competitive_outcome"]["winner_team_id"], "bot-b"
                )
                self.assertEqual(
                    cpu_result["competitive_outcome"]["status"], "forfeit"
                )
                self.assertIn(
                    cpu_result["competitive_outcome"]["faults"]["bot-a"]["kind"],
                    {"timeout", "unexpected_exit"},
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
