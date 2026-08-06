from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from rps_runner.tournament.capacity import (
    CONTINUOUS_OBJECTIVE_SECONDS,
    MAXIMUM_MATCHES,
    MAXIMUM_QUALIFYING_FIXTURES,
    MAXIMUM_ROUNDS,
    STEP_OBJECTIVE_SECONDS,
    BenchmarkReport,
    conforming_draw_result,
    maximum_capacity_roster,
    print_report,
    run_step_preflight,
)
from rps_runner.tournament.match_executor import MatchExecutionRequest
from rps_runner.tournament.runner import SCHEDULED_TURNS_PER_MATCH
from rps_runner.tournament.storage import (
    load_competition_records,
    load_operational_telemetry,
    load_scoreboard_projection,
)


class CapacityWorkloadTests(unittest.TestCase):
    def test_maximum_workload_has_published_capacity(self) -> None:
        roster = maximum_capacity_roster()

        self.assertEqual(len(roster), 32)
        self.assertEqual(len({team.team_id for team in roster}), 32)
        self.assertEqual(MAXIMUM_QUALIFYING_FIXTURES, 496)
        self.assertEqual(MAXIMUM_MATCHES, 1_497)
        self.assertEqual(MAXIMUM_ROUNDS, 449_100)
        self.assertEqual(SCHEDULED_TURNS_PER_MATCH, 300)

    def test_conforming_executor_result_completes_every_scheduled_round_as_draw(
        self,
    ) -> None:
        request = MatchExecutionRequest(
            tournament_id="capacity-test",
            fixture_id="qualifying-fixture-001",
            series_id="qualifying-fixture-001",
            match_id="qualifying-fixture-001-match-1",
            attempt_number=1,
            team_a_id="team-01",
            team_b_id="team-02",
            artifact_digest_a="a" * 64,
            artifact_digest_b="b" * 64,
            match_seed=1,
            bot_visible_seed_a=2,
            bot_visible_seed_b=3,
            protocol_version=1,
            scheduled_turns=300,
            first_move_timeout_ms=250,
            move_timeout_ms=50,
            total_timeout_ms=2000,
            stderr_limit_bytes=65_536,
            stdout_limit_bytes=4_096,
            cpu_limit_ms=2_000,
            memory_limit_bytes=268_435_456,
            process_limit=1,
            filesystem_write_limit_bytes=0,
            network_access_allowed=False,
        )

        result = conforming_draw_result(request)

        self.assertFalse(result.infrastructure_failure)
        self.assertEqual(result.competitive_outcome["outcome"], "draw")
        self.assertIsNone(result.competitive_outcome["winner_team_id"])
        self.assertEqual(len(result.competitive_outcome["rounds"]), 300)
        self.assertEqual(
            [
                round_entry["turn"]
                for round_entry in result.competitive_outcome["rounds"]
            ],
            list(range(300)),
        )


class CapacityReportTests(unittest.TestCase):
    def test_overrun_is_reported_without_becoming_a_failure(self) -> None:
        report = BenchmarkReport(
            name="Step Mode preflight",
            workload="one conforming Match through Scoreboard Projection update",
            elapsed_seconds=3.25,
            objective_seconds=STEP_OBJECTIVE_SECONDS,
        )
        output = io.StringIO()

        print_report(report, output=output)

        self.assertFalse(report.met_objective)
        self.assertEqual(report.process_exit_code, 0)
        self.assertEqual(
            output.getvalue(),
            "Benchmark: Step Mode preflight\n"
            "Workload: one conforming Match through Scoreboard Projection update\n"
            "Elapsed: 3.250 seconds\n"
            "Objective: 3.000 seconds\n"
            "Result: EXCEEDED (non-binding)\n",
        )

    def test_met_continuous_objective_has_stable_report(self) -> None:
        report = BenchmarkReport(
            name="Continuous Mode capacity",
            workload="32 Teams; 499 Fixtures; 1,497 Matches; 449,100 Rounds",
            elapsed_seconds=1_199.5,
            objective_seconds=CONTINUOUS_OBJECTIVE_SECONDS,
        )
        output = io.StringIO()

        print_report(report, output=output)

        self.assertTrue(report.met_objective)
        self.assertEqual(
            output.getvalue().splitlines()[-1],
            "Result: MET",
        )

    def test_step_overrun_commits_match_and_projection_normally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            times = iter((10.0, 13.25))

            report = run_step_preflight(directory, clock=lambda: next(times))

            records = load_competition_records(directory)
            telemetry = load_operational_telemetry(directory)
            projection = load_scoreboard_projection(directory)
            self.assertEqual(report.elapsed_seconds, 3.25)
            self.assertFalse(report.met_objective)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].record["type"], "match_terminal")
            self.assertEqual(len(records[0].record["rounds"]), 300)
            self.assertNotIn("elapsed_seconds", records[0].record)
            self.assertEqual(
                telemetry[-1],
                {
                    "type": "capacity_benchmark",
                    "tournament_id": "capacity-step-preflight",
                    "benchmark": "step",
                    "elapsed_seconds": 3.25,
                    "objective_seconds": 3,
                    "objective_met": False,
                },
            )
            self.assertIsNotNone(projection)
            self.assertEqual(projection["status"], "paused")
            self.assertEqual(projection["fixtures"][0]["status"], "in_progress")


if __name__ == "__main__":
    unittest.main()
