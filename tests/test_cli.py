from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def bot_command(path: Path) -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(path))}"


class MatchEngineCliTests(unittest.TestCase):
    def run_match(
        self,
        bot_a: str,
        bot_b: str,
        *,
        rounds: int = 1,
        extra_arguments: list[str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, object] | None]:
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
            "12345",
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
        result = json.loads(output.read_text()) if output.exists() else None
        return completed, result

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_bot(self, name: str, source: str) -> Path:
        path = self.directory / name
        path.write_text(textwrap.dedent(source))
        return path

    def test_completed_match_records_rounds_score_histories_and_environment(self) -> None:
        bot_a = self.write_bot(
            "bot_a.py",
            """
            import os
            import sys

            expected = ("1", "3", "12345")
            actual = (
                os.environ["RPS_PROTOCOL_VERSION"],
                os.environ["RPS_ROUNDS"],
                os.environ["RPS_SEED"],
            )
            moves = ["R", "P", "S"]
            for turn, move in enumerate(moves):
                request = [sys.stdin.readline().rstrip("\\n") for _ in range(3)]
                if actual != expected or request[0] != str(turn):
                    print("invalid")
                else:
                    print(move)
                sys.stdout.flush()
            """,
        )
        bot_b = self.write_bot(
            "bot_b.py",
            """
            import sys

            for move in ["S", "P", "P"]:
                for _ in range(3):
                    sys.stdin.readline()
                print(move, flush=True)
            """,
        )

        completed, result = self.run_match(
            bot_command(bot_a), bot_command(bot_b), rounds=3
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["score"], {"a": 2, "b": 0, "draws": 1})
        self.assertEqual(result["moves"], {"a": "RPS", "b": "SPP"})
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
        bot_source = """
            import pathlib
            import sys
            import time

            mine = pathlib.Path({mine!r})
            other = pathlib.Path({other!r})
            for _ in range(3):
                sys.stdin.readline()
            mine.touch()
            deadline = time.monotonic() + 1
            while not other.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            print("R" if other.exists() else "invalid", flush=True)
        """
        bot_a = self.write_bot(
            "bot_a.py",
            bot_source.format(mine=str(ready_a), other=str(ready_b)),
        )
        bot_b = self.write_bot(
            "bot_b.py",
            bot_source.format(mine=str(ready_b), other=str(ready_a)),
        )

        completed, result = self.run_match(bot_command(bot_a), bot_command(bot_b))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["score"], {"a": 0, "b": 0, "draws": 1})

    def test_slow_bot_fault_does_not_make_fast_bot_fault(self) -> None:
        slow_bot = self.write_bot(
            "slow.py",
            """
            import sys
            import time

            for _ in range(3):
                sys.stdin.readline()
            time.sleep(0.2)
            print("R", flush=True)
            """,
        )
        fast_bot = self.write_bot(
            "fast.py",
            """
            import sys

            for _ in range(3):
                sys.stdin.readline()
            print("P", flush=True)
            """,
        )

        completed, result = self.run_match(
            bot_command(slow_bot),
            bot_command(fast_bot),
            extra_arguments=["--first-move-timeout-ms", "75"],
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "timeout")
        self.assertIsNone(result["faults"]["b"])

    def test_stderr_is_drained_and_capture_is_bounded(self) -> None:
        noisy_bot = self.write_bot(
            "noisy.py",
            """
            import sys

            sys.stderr.write("x" * 100_000)
            sys.stderr.flush()
            for _ in range(3):
                sys.stdin.readline()
            print("R", flush=True)
            """,
        )
        quiet_bot = self.write_bot(
            "quiet.py",
            """
            import sys

            for _ in range(3):
                sys.stdin.readline()
            print("S", flush=True)
            """,
        )

        completed, result = self.run_match(
            bot_command(noisy_bot),
            bot_command(quiet_bot),
            extra_arguments=["--stderr-limit-bytes", "128"],
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["bots"]["a"]["stderr"]), 128)
        self.assertTrue(result["bots"]["a"]["stderr_truncated"])

    def test_process_start_failure_is_an_infrastructure_failure(self) -> None:
        valid_bot = self.write_bot(
            "valid.py",
            """
            import sys

            for _ in range(3):
                sys.stdin.readline()
            print("R", flush=True)
            """,
        )

        completed, result = self.run_match(
            "/definitely/not/a/program", bot_command(valid_bot)
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(result["status"], "infrastructure_error")
        self.assertIn("start", result["error"].lower())

    def test_both_bot_processes_are_stopped_after_a_match(self) -> None:
        pid_a = self.directory / "a.pid"
        pid_b = self.directory / "b.pid"
        bot_source = """
            import os
            import pathlib
            import sys
            import time

            pathlib.Path({pid_path!r}).write_text(str(os.getpid()))
            for _ in range(3):
                sys.stdin.readline()
            print("R", flush=True)
            while True:
                time.sleep(1)
        """
        bot_a = self.write_bot(
            "bot_a.py", bot_source.format(pid_path=str(pid_a))
        )
        bot_b = self.write_bot(
            "bot_b.py", bot_source.format(pid_path=str(pid_b))
        )

        completed, result = self.run_match(bot_command(bot_a), bot_command(bot_b))

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
        eager_bot = self.write_bot(
            "eager.py",
            """
            import sys
            import time

            for _ in range(3):
                sys.stdin.readline()
            print("R", flush=True)
            time.sleep(0.02)
            print("P", flush=True)
            while True:
                time.sleep(1)
            """,
        )
        delaying_bot = self.write_bot(
            "delaying.py",
            """
            import sys
            import time

            for turn in range(2):
                for _ in range(3):
                    sys.stdin.readline()
                if turn == 0:
                    time.sleep(0.1)
                print("S", flush=True)
            """,
        )

        completed, result = self.run_match(
            bot_command(eager_bot), bot_command(delaying_bot), rounds=2
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "unexpected_output")
        self.assertEqual(result["faults"]["a"]["turn"], 1)

    def test_faulted_bot_is_terminated_while_opponent_response_is_pending(self) -> None:
        terminated_marker = self.directory / "terminated"
        faulting_bot = self.write_bot(
            "faulting.py",
            f"""
            import pathlib
            import signal
            import sys
            import time

            marker = pathlib.Path({str(terminated_marker)!r})
            signal.signal(signal.SIGTERM, lambda *_: (marker.touch(), sys.exit(0)))
            for _ in range(3):
                sys.stdin.readline()
            print("invalid", flush=True)
            while True:
                time.sleep(1)
            """,
        )
        observing_bot = self.write_bot(
            "observing.py",
            f"""
            import pathlib
            import sys
            import time

            marker = pathlib.Path({str(terminated_marker)!r})
            for _ in range(3):
                sys.stdin.readline()
            deadline = time.monotonic() + 0.2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            print("R" if marker.exists() else "invalid", flush=True)
            """,
        )

        completed, result = self.run_match(
            bot_command(faulting_bot), bot_command(observing_bot)
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
