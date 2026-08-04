from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Any, get_type_hints, Optional
import unittest

from rps_runner.cli import main


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
        command = [
            sys.executable,
            "-m",
            "rps_runner.cli",
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
        command.extend(extra_arguments or [])
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if not output.exists():
            self.fail(
                "CLI did not write a result file.\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        result: dict[str, Any] = json.loads(output.read_text())
        return completed, result

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
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["score"], {"a": 2, "b": 0, "draws": 1})
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

    def test_stderr_is_drained_and_capture_is_bounded(self) -> None:
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
        self.assertEqual(result["status"], "completed")
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

    def test_python_starter_bot_runs_deterministically(self) -> None:
        random_bot = PROJECT_ROOT / "bots" / "random_bot.py"
        copycat_bot = PROJECT_ROOT / "bots" / "copycat_bot.py"

        first_completed, first_result = self.run_match(
            bot_command(random_bot), bot_command(copycat_bot), rounds=10
        )
        second_completed, second_result = self.run_match(
            bot_command(random_bot), bot_command(copycat_bot), rounds=10
        )

        self.assertEqual(first_completed.returncode, 0, first_completed.stderr)
        self.assertEqual(second_completed.returncode, 0, second_completed.stderr)
        self.assertEqual(first_result["status"], "completed")
        self.assertEqual(first_result["moves"], second_result["moves"])
        self.assertEqual(first_result["score"], second_result["score"])

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
        random_bot = PROJECT_ROOT / "bots" / "random_bot.py"
        copycat_bot = PROJECT_ROOT / "bots" / "copycat_bot.py"

        completed, result = self.run_match(
            bot_command(random_bot), bot_command(copycat_bot), rounds=2
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(set(result["timing"]["total_response_ns"]), {"a", "b"})
        for duration in result["timing"]["total_response_ns"].values():
            self.assertIsInstance(duration, int)
            self.assertGreaterEqual(duration, 0)
        for played_round in result["rounds"]:
            self.assertEqual(set(played_round["response_time_ns"]), {"a", "b"})
            for duration in played_round["response_time_ns"].values():
                self.assertIsInstance(duration, int)
                self.assertGreaterEqual(duration, 0)


if __name__ == "__main__":
    unittest.main()
