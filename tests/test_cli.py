from __future__ import annotations

import json
from contextlib import redirect_stderr
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Any, get_type_hints, Optional
import unittest
from unittest.mock import patch

from rps_runner.cli import main
from rps_runner.tournament.match_executor import MatchExecutionResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_BOTS = PROJECT_ROOT / "tests" / "fixtures" / "bots"


def bot_command(path: Path, *arguments: object) -> str:
    return shlex.join(
        [sys.executable, str(path)]
        + [str(argument) for argument in arguments]
    )


def test_bot(name: str, *arguments: object) -> str:
    return bot_command(TEST_BOTS / name, *arguments)


class MatchEngineCliTests(unittest.TestCase):
    def test_public_container_match_uses_the_hardened_executor(self) -> None:
        output = self.directory / "container-result.json"
        execution_result = MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome={"status": "completed", "winner_team_id": "bot-a"},
            operational_telemetry={"profile": "docker-execution-v1"},
        )
        with patch("rps_runner.cli.ContainerMatchExecutor") as executor_type:
            executor_type.return_value.execute.return_value = execution_result

            exit_code = main(
                [
                    "--container",
                    "--bot-a",
                    "sha256:" + "a" * 64,
                    "--bot-b",
                    "sha256:" + "b" * 64,
                    "--rounds",
                    "300",
                    "--seed",
                    "12345",
                    "--bot-a-seed",
                    "111",
                    "--bot-b-seed",
                    "222",
                    "--output",
                    str(output),
                ]
            )

        self.assertEqual(exit_code, 0)
        request = executor_type.return_value.execute.call_args.args[0]
        self.assertEqual(request.bot_visible_seed_a, 111)
        self.assertEqual(request.bot_visible_seed_b, 222)
        self.assertEqual(request.execution_profile_version, "docker-execution-v1")
        self.assertEqual(request.cpu_quota_millis_per_second, 1000)
        result = json.loads(output.read_text())
        self.assertEqual(result["competitive_outcome"]["winner_team_id"], "bot-a")

    def test_public_container_match_rejects_mutable_image_tags(self) -> None:
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(
                    [
                        "--container",
                        "--bot-a",
                        "candidate:latest",
                        "--bot-b",
                        "sha256:" + "b" * 64,
                        "--rounds",
                        "300",
                        "--seed",
                        "1",
                        "--output",
                        str(self.directory / "result.json"),
                    ]
                )

    def test_cli_type_hints_resolve_on_supported_python_versions(self) -> None:
        hints = get_type_hints(main)

        self.assertEqual(hints["return"], int)

    def run_match(
        self,
        bot_a: str,
        bot_b: str,
        *,
        rounds: int = 1,
        seed: int = 12345,
        extra_arguments: Optional[list[str]] = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        output = self.directory / "result.json"
        arguments = [
            "--bot-a",
            bot_a,
            "--bot-b",
            bot_b,
            "--rounds",
            str(rounds),
            "--seed",
            str(seed),
            "--output",
            str(output),
        ]
        arguments.extend(extra_arguments or [])
        completed = self.run_cli(*arguments)
        if not output.exists():
            self.fail(
                "CLI did not write a result file.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        result: dict[str, Any] = json.loads(output.read_text())
        return completed, result

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "rps_runner.cli", *arguments],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_completed_match_records_rounds_score_histories_and_environment(self) -> None:
        protocol_version = 1
        rounds = 3
        seed = 12345
        bot_a_moves = "RPS"
        bot_b_moves = "SPP"

        completed, result = self.run_match(
            test_bot(
                "checks_protocol.py",
                bot_a_moves,
                protocol_version,
                rounds,
                seed,
            ),
            test_bot("plays_moves.py", bot_b_moves),
            rounds=rounds,
            seed=seed,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["protocol_version"], protocol_version)
        self.assertEqual(result["scheduled_rounds"], rounds)
        self.assertEqual(result["seed"], seed)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["score"], {"a": 2, "b": 0, "draws": 1})
        self.assertEqual(result["completed_rounds"], rounds)
        self.assertEqual(result["faults"], {"a": None, "b": None})
        self.assertEqual(
            result["moves"], {"a": bot_a_moves, "b": bot_b_moves}
        )
        self.assertEqual(
            [
                {
                    key: value
                    for key, value in played_round.items()
                    if key != "response_time_ns"
                }
                for played_round in result["rounds"]
            ],
            [
                {"turn": 0, "a": "R", "b": "S", "winner": "a"},
                {"turn": 1, "a": "P", "b": "P", "winner": "draw"},
                {"turn": 2, "a": "S", "b": "P", "winner": "a"},
            ],
        )

    def test_all_round_outcomes_are_scored(self) -> None:
        cases = [
            ("R", "R", "draw", {"a": 0, "b": 0, "draws": 1}),
            ("R", "P", "b", {"a": 0, "b": 1, "draws": 0}),
            ("R", "S", "a", {"a": 1, "b": 0, "draws": 0}),
            ("P", "R", "a", {"a": 1, "b": 0, "draws": 0}),
            ("P", "P", "draw", {"a": 0, "b": 0, "draws": 1}),
            ("P", "S", "b", {"a": 0, "b": 1, "draws": 0}),
            ("S", "R", "b", {"a": 0, "b": 1, "draws": 0}),
            ("S", "P", "a", {"a": 1, "b": 0, "draws": 0}),
            ("S", "S", "draw", {"a": 0, "b": 0, "draws": 1}),
        ]

        for move_a, move_b, expected_winner, expected_score in cases:
            with self.subTest(move_a=move_a, move_b=move_b):
                completed, result = self.run_match(
                    test_bot("plays_moves.py", move_a),
                    test_bot("plays_moves.py", move_b),
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["winner"], expected_winner)
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(
                    result["rounds"][0]["winner"], expected_winner
                )

    def test_requests_contain_each_bots_completed_histories(self) -> None:
        bot_a_moves = "RPS"
        bot_b_moves = "SPR"

        completed, result = self.run_match(
            test_bot("checks_requests.py", bot_a_moves, bot_b_moves),
            test_bot("checks_requests.py", bot_b_moves, bot_a_moves),
            rounds=3,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            result["moves"], {"a": bot_a_moves, "b": bot_b_moves}
        )

    def test_sends_both_requests_before_waiting_for_responses(self) -> None:
        ready_a = self.directory / "a.ready"
        ready_b = self.directory / "b.ready"
        move = "R"

        completed, result = self.run_match(
            test_bot("waits_for_peer.py", ready_a, ready_b, move),
            test_bot("waits_for_peer.py", ready_b, ready_a, move),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["score"], {"a": 0, "b": 0, "draws": 1})

    def test_slow_bot_fault_does_not_make_fast_bot_fault(self) -> None:
        slow_bot_move = "R"
        fast_bot_move = "P"
        slow_response_seconds = 0.2
        first_move_timeout_ms = 75

        completed, result = self.run_match(
            test_bot(
                "responds_slowly.py",
                slow_bot_move,
                slow_response_seconds,
            ),
            test_bot("plays_moves.py", fast_bot_move),
            extra_arguments=[
                "--first-move-timeout-ms",
                str(first_move_timeout_ms),
            ],
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "timeout")
        self.assertIsNone(result["faults"]["b"])

    def test_stderr_overflow_is_bounded_and_forfeits_the_match(self) -> None:
        noisy_bot_move = "R"
        quiet_bot_move = "S"
        emitted_stderr_bytes = 100_000
        captured_stderr_bytes = 128

        completed, result = self.run_match(
            test_bot(
                "writes_excessive_stderr.py",
                noisy_bot_move,
                emitted_stderr_bytes,
            ),
            test_bot("plays_moves.py", quiet_bot_move),
            extra_arguments=[
                "--stderr-limit-bytes",
                str(captured_stderr_bytes),
            ],
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "excessive_stderr")
        self.assertEqual(
            len(result["bots"]["a"]["stderr"]), captured_stderr_bytes
        )
        self.assertTrue(result["bots"]["a"]["stderr_truncated"])

    def test_process_start_failure_is_an_infrastructure_failure(self) -> None:
        valid_bot = test_bot("plays_moves.py", "R")

        completed, result = self.run_match(
            "/definitely/not/a/program", valid_bot
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertIn("start", result["error"].lower())

    def test_first_bot_is_stopped_when_second_bot_cannot_start(self) -> None:
        pid_file = self.directory / "bot-a.pid"
        # Delay bot B's parse failure long enough for bot A to record its PID.
        slowly_invalid_command = '"' + "x" * 100_000

        completed, result = self.run_match(
            test_bot("stays_alive.py", pid_file, "R"),
            slowly_invalid_command,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(result["status"], "infrastructure_error")
        pid = int(pid_file.read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_invalid_numeric_arguments_are_rejected(self) -> None:
        valid_bot = test_bot("plays_moves.py", "R")
        cases = [
            ("zero-rounds", "--rounds", "0"),
            ("negative-seed", "--seed", "-1"),
            ("overflowing-seed", "--seed", str(2**64)),
            ("negative-stderr-limit", "--stderr-limit-bytes", "-1"),
        ]

        for name, option, invalid_value in cases:
            with self.subTest(option=option, value=invalid_value):
                output = self.directory / f"{name}.json"
                arguments = [
                    "--bot-a",
                    valid_bot,
                    "--bot-b",
                    valid_bot,
                    "--rounds",
                    "1",
                    "--seed",
                    "0",
                    "--output",
                    str(output),
                    "--stderr-limit-bytes",
                    "128",
                ]
                arguments[arguments.index(option) + 1] = invalid_value

                completed = self.run_cli(*arguments)

                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertFalse(output.exists())

    def test_unsigned_seed_boundaries_are_accepted(self) -> None:
        valid_bot = test_bot("plays_moves.py", "R")

        for seed in (0, 2**64 - 1):
            with self.subTest(seed=seed):
                completed, result = self.run_match(
                    valid_bot,
                    valid_bot,
                    seed=seed,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["seed"], seed)

    def test_result_write_failure_returns_an_infrastructure_exit_code(self) -> None:
        valid_bot = test_bot("plays_moves.py", "R")

        completed = self.run_cli(
            "--bot-a",
            valid_bot,
            "--bot-b",
            valid_bot,
            "--rounds",
            "1",
            "--seed",
            "12345",
            "--output",
            str(self.directory),
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("could not write result", completed.stderr.lower())

    def test_result_parent_directories_are_created(self) -> None:
        valid_bot = test_bot("plays_moves.py", "R")
        output = self.directory / "nested" / "results" / "match.json"

        completed = self.run_cli(
            "--bot-a",
            valid_bot,
            "--bot-b",
            valid_bot,
            "--rounds",
            "1",
            "--seed",
            "12345",
            "--output",
            str(output),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(output.read_text())["status"], "completed")

    def test_both_bot_processes_are_stopped_after_a_match(self) -> None:
        pid_a = self.directory / "a.pid"
        pid_b = self.directory / "b.pid"
        move = "R"

        completed, result = self.run_match(
            test_bot("stays_alive.py", pid_a, move),
            test_bot("stays_alive.py", pid_b, move),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        for pid_path in (pid_a, pid_b):
            pid = int(pid_path.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_protocol_fixtures_run_deterministically(self) -> None:
        first_completed, first_result = self.run_match(
            test_bot("plays_seeded_random.py"),
            test_bot("copies_opponent.py"),
            rounds=10,
        )
        second_completed, second_result = self.run_match(
            test_bot("plays_seeded_random.py"),
            test_bot("copies_opponent.py"),
            rounds=10,
        )

        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertEqual(first_result["status"], "completed")
        self.assertEqual(first_result["moves"], second_result["moves"])
        self.assertEqual(first_result["score"], second_result["score"])

    def test_protocol_fixture_uses_the_configured_seed(self) -> None:
        first_completed, first_result = self.run_match(
            test_bot("plays_seeded_random.py"),
            test_bot("copies_opponent.py"),
            rounds=10,
            seed=1,
        )
        second_completed, second_result = self.run_match(
            test_bot("plays_seeded_random.py"),
            test_bot("copies_opponent.py"),
            rounds=10,
            seed=2,
        )

        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertNotEqual(
            first_result["moves"]["a"], second_result["moves"]["a"]
        )

    def test_output_between_requests_is_a_protocol_fault(self) -> None:
        early_bot_moves = "RP"
        opponent_moves = "SS"
        delay_between_early_responses_seconds = 0.02
        opponent_first_response_delay_seconds = 0.1

        completed, result = self.run_match(
            test_bot(
                "responds_before_request.py",
                early_bot_moves,
                delay_between_early_responses_seconds,
            ),
            test_bot(
                "delays_first_response.py",
                opponent_moves,
                opponent_first_response_delay_seconds,
            ),
            rounds=2,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "unexpected_output")
        self.assertEqual(result["faults"]["a"]["turn"], 1)

    def test_invalid_utf8_response_is_a_protocol_fault(self) -> None:
        completed, result = self.run_match(
            test_bot("commits_protocol_fault.py", "invalid_utf8"),
            test_bot("plays_moves.py", "R"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "invalid_response")
        self.assertIsNone(result["faults"]["b"])

    def test_multiple_responses_for_one_request_are_a_protocol_fault(self) -> None:
        completed, result = self.run_match(
            test_bot("commits_protocol_fault.py", "multiple_responses"),
            test_bot("plays_moves.py", "R"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "unexpected_output")
        self.assertIsNone(result["faults"]["b"])

    def test_excessive_stdout_is_a_protocol_fault(self) -> None:
        completed, result = self.run_match(
            test_bot("commits_protocol_fault.py", "excessive_output"),
            test_bot("plays_moves.py", "R"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "excessive_output")
        self.assertIsNone(result["faults"]["b"])

    def test_bot_exit_before_response_is_a_protocol_fault(self) -> None:
        completed, result = self.run_match(
            test_bot("commits_protocol_fault.py", "exits_early"),
            test_bot("plays_moves.py", "R"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "unexpected_exit")
        self.assertEqual(result["bots"]["a"]["stderr"], "")
        self.assertIsNone(result["faults"]["b"])

    def test_bot_b_fault_awards_the_match_to_bot_a(self) -> None:
        completed, result = self.run_match(
            test_bot("plays_moves.py", "R"),
            test_bot("commits_protocol_fault.py", "invalid_utf8"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "a")
        self.assertIsNone(result["faults"]["a"])
        self.assertEqual(result["faults"]["b"]["kind"], "invalid_response")

    def test_both_bot_faults_are_a_double_forfeit(self) -> None:
        completed, result = self.run_match(
            test_bot("commits_protocol_fault.py", "invalid_utf8"),
            test_bot("commits_protocol_fault.py", "invalid_utf8"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "double_forfeit")
        self.assertIsNone(result["winner"])
        self.assertEqual(result["faults"]["a"]["kind"], "invalid_response")
        self.assertEqual(result["faults"]["b"]["kind"], "invalid_response")

    def test_faulted_bot_is_terminated_while_opponent_response_is_pending(self) -> None:
        terminated_marker = self.directory / "terminated"
        faulting_response = "invalid"
        observing_bot_move = "R"
        observation_timeout_seconds = 0.2

        completed, result = self.run_match(
            test_bot(
                "marks_when_terminated.py",
                terminated_marker,
                faulting_response,
            ),
            test_bot(
                "waits_for_termination.py",
                terminated_marker,
                observing_bot_move,
                observation_timeout_seconds,
            ),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "invalid_response")
        self.assertIsNone(result["faults"]["b"])

    def test_replay_contains_monotonic_response_durations(self) -> None:
        completed, result = self.run_match(
            test_bot("plays_seeded_random.py"),
            test_bot("copies_opponent.py"),
            rounds=2,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["timing"]["clock"], "monotonic")
        self.assertEqual(set(result["timing"]["total_response_ns"]), {"a", "b"})
        for duration in result["timing"]["total_response_ns"].values():
            self.assertIsInstance(duration, int)
            self.assertGreaterEqual(duration, 0)
        for played_round in result["rounds"]:
            self.assertEqual(set(played_round["response_time_ns"]), {"a", "b"})
            for duration in played_round["response_time_ns"].values():
                self.assertIsInstance(duration, int)
                self.assertGreaterEqual(duration, 0)
        for label in ("a", "b"):
            self.assertEqual(
                result["timing"]["total_response_ns"][label],
                sum(
                    played_round["response_time_ns"][label]
                    for played_round in result["rounds"]
                ),
            )


if __name__ == "__main__":
    unittest.main()
