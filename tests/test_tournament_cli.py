from __future__ import annotations

from collections.abc import Callable
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Optional
import unittest

from rps_runner.tournament.match_executor import (
    MatchExecutionRequest,
    MatchExecutionResult,
)
from rps_runner.tournament.runner import TournamentRunner
from rps_runner.tournament.storage import (
    canonical_json_bytes,
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
)
from rps_runner.tournament_cli import main


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def winning_result(
    request: MatchExecutionRequest,
    *,
    winner_team_id: Optional[str] = None,
) -> MatchExecutionResult:
    winner = winner_team_id or request.team_a_id
    loser = (
        request.team_b_id if winner == request.team_a_id else request.team_a_id
    )
    round_moves = {
        winner: "R",
        loser: "S",
    }
    moves = {
        team_id: move * request.scheduled_turns
        for team_id, move in round_moves.items()
    }
    return MatchExecutionResult(
        infrastructure_failure=False,
        competitive_outcome={
            "outcome": "win",
            "winner_team_id": winner,
            "score": {
                winner: request.scheduled_turns,
                loser: 0,
                "draws": 0,
            },
            "moves": moves,
            "rounds": [
                {
                    "turn": turn,
                    "moves": round_moves,
                    "winner_team_id": winner,
                }
                for turn in range(request.scheduled_turns)
            ],
            "faults": {request.team_a_id: None, request.team_b_id: None},
        },
        operational_telemetry={"type": "match_attempt_completed"},
    )


def recording_winner_executor(
    requests: list[MatchExecutionRequest],
) -> Callable[[MatchExecutionRequest], MatchExecutionResult]:
    def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
        requests.append(request)
        return winning_result(request)

    return execute


class TournamentDemoCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name) / "demo-tournament"
        self.stdout = StringIO()
        self.stderr = StringIO()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def rewrite_sealed_manifest(
        self, mutate: Callable[[dict[str, Any]], None]
    ) -> None:
        manifest_path = self.directory / "manifest.json"
        envelope = json.loads(manifest_path.read_bytes())
        mutate(envelope["manifest"])
        envelope["checksum"] = hashlib.sha256(
            canonical_json_bytes(envelope["manifest"])
        ).hexdigest()
        manifest_path.chmod(0o644)
        manifest_path.write_bytes(canonical_json_bytes(envelope))

    def run_demo(
        self,
        *extra_arguments: str,
        match_executor=winning_result,
        project_root: Path = PROJECT_ROOT,
        python_executable: Path = Path(sys.executable),
        seed: str = "12345",
    ) -> int:
        return main(
            [
                "demo",
                "--directory",
                str(self.directory),
                "--seed",
                seed,
                *extra_arguments,
            ],
            match_executor=match_executor,
            project_root=project_root,
            python_executable=python_executable,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def test_new_demo_creates_and_commits_one_match_with_summary(self) -> None:
        requests: list[MatchExecutionRequest] = []

        exit_code = self.run_demo(
            match_executor=recording_winner_executor(requests)
        )

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].scheduled_turns, 300)
        self.assertEqual(requests[0].match_id, "qualifying-0001-match-1")

        manifest = load_manifest(self.directory).manifest
        self.assertEqual(len(manifest["roster"]), 4)
        self.assertEqual(
            {team["team_id"] for team in manifest["roster"]},
            {"copycat-alpha", "copycat-beta", "random-alpha", "random-beta"},
        )
        for team in manifest["roster"]:
            digest = team["bot_artifact"]["artifact_digest"]
            self.assertRegex(digest, r"\A[0-9a-f]{64}\Z")
            self.assertNotEqual(digest, digest[0] * 64)

        records = load_competition_records(self.directory)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].record["match_id"], "qualifying-0001-match-1"
        )
        self.assertTrue(load_operational_telemetry(self.directory))
        self.assertIsNotNone(load_scoreboard_projection(self.directory))

        output = self.stdout.getvalue()
        self.assertIn("Tournament: created", output)
        self.assertIn("Committed Match: qualifying-0001-match-1", output)
        self.assertIn("Teams:", output)
        self.assertIn("Outcome:", output)
        self.assertIn("Match Seed:", output)
        self.assertIn("Qualifying Fixtures:", output)
        self.assertIn("Standings:", output)
        self.assertIn(str(self.directory / "manifest.json"), output)
        self.assertIn(str(self.directory / "records"), output)
        self.assertIn(str(self.directory / "telemetry"), output)
        self.assertIn(str(self.directory / "scoreboard.json"), output)

    def test_abort_is_attributable_terminal_and_does_not_execute_a_match(self) -> None:
        requests: list[MatchExecutionRequest] = []

        exit_code = self.run_demo(
            "--abort",
            "--organizer-id",
            "organizer-cli",
            "--abort-note",
            "Severe weather",
            match_executor=recording_winner_executor(requests),
        )

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(requests, [])
        records = load_competition_records(self.directory)
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0].record,
            {
                "type": "tournament_aborted",
                "phase": "qualifying",
                "organizer_id": "organizer-cli",
                "reason_code": "operator_requested",
                "note": "Severe weather",
            },
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "aborted")
        self.assertIsNone(projection["champion"])
        self.assertIn("Tournament aborted by organizer-cli", self.stdout.getvalue())
        self.assertIn("Reason: operator_requested", self.stdout.getvalue())
        canonical = canonical_json_bytes(records[0].record).lower()
        for prohibited in (
            b"timestamp",
            b"telemetry",
            b"launch",
            b"diagnostic",
            b"stderr",
        ):
            self.assertNotIn(prohibited, canonical)

    def test_abort_requires_valid_audit_inputs_and_excludes_running_scopes(
        self,
    ) -> None:
        missing_identity = self.run_demo("--abort")

        self.assertEqual(missing_identity, 2)
        self.assertIn("organizer identity", self.stderr.getvalue().lower())
        self.assertFalse(self.directory.exists())

        for arguments in (
            (
                "--abort",
                "--organizer-id",
                "organizer-cli",
                "--abort-reason",
                "free-text",
            ),
            ("--abort", "--organizer-id", "organizer-cli", "--all"),
        ):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rps_runner.tournament_cli",
                        "demo",
                        "--directory",
                        str(self.directory),
                        "--seed",
                        "12345",
                        *arguments,
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertFalse(self.directory.exists())

    def test_existing_demo_verifies_resumes_and_skips_committed_match(self) -> None:
        requests: list[MatchExecutionRequest] = []

        executor = recording_winner_executor(requests)
        first_exit_code = self.run_demo(match_executor=executor)
        second_exit_code = self.run_demo(match_executor=executor)

        self.assertEqual(first_exit_code, 0, self.stderr.getvalue())
        self.assertEqual(second_exit_code, 0, self.stderr.getvalue())
        self.assertEqual(
            [request.match_id for request in requests],
            ["qualifying-0001-match-1", "qualifying-0001-match-2"],
        )
        self.assertEqual(
            [
                stored.record["match_id"]
                for stored in load_competition_records(self.directory)
            ],
            ["qualifying-0001-match-1", "qualifying-0001-match-2"],
        )
        self.assertIn("Tournament: resumed", self.stdout.getvalue())

    def test_all_qualification_finishes_fixtures_without_declaring_champion(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def stable_winner_executor(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            requests.append(request)
            return winning_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        exit_code = self.run_demo(
            "--all-qualification", match_executor=stable_winner_executor
        )

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(len(requests), 12)
        projection = load_scoreboard_projection(self.directory)
        assert projection is not None
        self.assertTrue(
            all(fixture["status"] == "complete" for fixture in projection["fixtures"])
        )
        self.assertIsNone(projection["champion"])
        output = self.stdout.getvalue()
        self.assertIn("Qualifying Fixtures: 6/6 complete", output)
        self.assertIn("Qualification has no unresolved Match", output)
        self.assertIn("Playoff Fixtures: 0/3 complete", output)
        self.assertIn("No Tournament Champion has been declared", output)

    def test_all_finishes_tournament_and_reports_champion(self) -> None:
        requests: list[MatchExecutionRequest] = []

        def stable_winner_executor(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            requests.append(request)
            return winning_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        exit_code = self.run_demo("--all", match_executor=stable_winner_executor)

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(len(requests), 18)
        projection = load_scoreboard_projection(self.directory)
        assert projection is not None
        self.assertEqual(projection["status"], "complete")
        self.assertEqual(projection["champion"], "copycat-alpha")
        self.assertEqual(
            [fixture["status"] for fixture in projection["bracket"]["fixtures"]],
            ["complete", "complete", "complete"],
        )
        records = load_competition_records(self.directory)
        self.assertEqual(records[-1].record["type"], "tournament_champion_declared")
        output = self.stdout.getvalue()
        self.assertIn("Playoff Fixtures: 3/3 complete", output)
        self.assertIn("Tournament Champion: copycat-alpha", output)
        self.assertNotIn("artifact_digest", output)
        self.assertNotIn("entrypoint", output)

    def test_all_finishes_reduced_direct_final_and_sole_champion(self) -> None:
        for eligible_team_count in (2, 1, 0):
            with self.subTest(eligible_team_count=eligible_team_count):
                with tempfile.TemporaryDirectory() as directory_name:
                    self.directory = Path(directory_name) / "demo-tournament"
                    self.stdout = StringIO()
                    self.stderr = StringIO()
                    self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())

                    def suspect(
                        request: MatchExecutionRequest,
                    ) -> MatchExecutionResult:
                        return MatchExecutionResult(
                            infrastructure_failure=False,
                            competitive_outcome=None,
                            operational_telemetry={
                                "raw_security_evidence": "variable"
                            },
                            suspected_security_violation_team_id=request.team_a_id,
                            evidence_link=f"evidence:cli-reduced/{request.match_id}",
                        )

                    runner = TournamentRunner.open(
                        self.directory,
                        match_executor=suspect,
                        artifact_digest_verifier=lambda team_id, digest: True,
                    )
                    single_disqualifications = (
                        2 if eligible_team_count == 0 else 4 - eligible_team_count
                    )
                    for ordinal in range(single_disqualifications):
                        runner.play_next_match()
                        runner.confirm_security_violation(
                            organizer_id=f"organizer-{ordinal + 1}"
                        )
                    if eligible_team_count == 0:
                        def suspect_both(
                            request: MatchExecutionRequest,
                        ) -> MatchExecutionResult:
                            return MatchExecutionResult(
                                infrastructure_failure=False,
                                competitive_outcome=None,
                                operational_telemetry={
                                    "raw_security_evidence": "double-incident"
                                },
                                evidence_link=(
                                    f"evidence:cli-reduced/{request.match_id}"
                                ),
                                suspected_security_violation_team_ids=(
                                    request.team_a_id,
                                    request.team_b_id,
                                ),
                            )

                        runner.match_executor = suspect_both
                        incident = runner.play_next_match()
                        for team_id in incident.record["suspected_team_ids"]:
                            runner.confirm_security_violation(
                                organizer_id="organizer-3", team_id=team_id
                            )

                    requests: list[MatchExecutionRequest] = []

                    def stable_winner(
                        request: MatchExecutionRequest,
                    ) -> MatchExecutionResult:
                        requests.append(request)
                        return winning_result(
                            request,
                            winner_team_id=min(
                                request.team_a_id, request.team_b_id
                            ),
                        )

                    self.stdout = StringIO()
                    self.assertEqual(
                        self.run_demo("--all", match_executor=stable_winner),
                        0,
                        self.stderr.getvalue(),
                    )
                    projection = load_scoreboard_projection(self.directory)
                    assert projection is not None
                    self.assertEqual(projection["status"], "complete")
                    if eligible_team_count:
                        self.assertIsNotNone(projection["champion"])
                    else:
                        self.assertIsNone(projection["champion"])
                        self.assertEqual(
                            projection["completion_reason"],
                            "no_eligible_teams",
                        )
                    self.assertEqual(
                        len(
                            [
                                request
                                for request in requests
                                if request.fixture_id.startswith("playoff-")
                            ]
                        ),
                        2 if eligible_team_count == 2 else 0,
                    )
                    self.assertIn(
                        f"Playoff Fixtures: {1 if eligible_team_count == 2 else 0}/"
                        f"{1 if eligible_team_count == 2 else 0} complete",
                        self.stdout.getvalue(),
                    )
                    if eligible_team_count:
                        self.assertIn(
                            "Tournament Champion:", self.stdout.getvalue()
                        )
                    else:
                        self.assertIn(
                            "without a Tournament Champion",
                            self.stdout.getvalue(),
                        )

    def test_corrupt_existing_tournament_fails_without_overwriting_it(self) -> None:
        self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())
        manifest_path = self.directory / "manifest.json"
        manifest_path.chmod(0o644)
        corrupt_content = b"not a Tournament Manifest\n"
        manifest_path.write_bytes(corrupt_content)

        exit_code = self.run_demo()

        self.assertNotEqual(exit_code, 0)
        self.assertIn("Tournament Manifest", self.stderr.getvalue())
        self.assertEqual(manifest_path.read_bytes(), corrupt_content)
        self.assertEqual(len(list((self.directory / "records").glob("*.json"))), 1)

    def test_resume_rejects_changed_bot_artifact_bytes(self) -> None:
        demo_inputs = Path(self.temporary_directory.name) / "demo-inputs"
        shutil.copytree(PROJECT_ROOT / "bots", demo_inputs / "bots")
        self.assertEqual(
            self.run_demo(project_root=demo_inputs), 0, self.stderr.getvalue()
        )
        random_bot = demo_inputs / "bots" / "random_bot.py"
        random_bot.write_text(random_bot.read_text() + "\n# changed\n")

        exit_code = self.run_demo(project_root=demo_inputs)

        self.assertNotEqual(exit_code, 0)
        self.assertIn(
            "Bot Artifact digest verification failed for random-alpha",
            self.stderr.getvalue(),
        )
        self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_resume_rejects_a_different_tournament_seed(self) -> None:
        self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())

        exit_code = self.run_demo(seed="54321")

        self.assertNotEqual(exit_code, 0)
        diagnostic = self.stderr.getvalue()
        self.assertIn("incompatible with the bundled demo", diagnostic)
        self.assertIn("tournament_seed", diagnostic)
        self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_resume_rejects_a_different_sealed_tournament_identity(self) -> None:
        def change_tournament_id(manifest: dict[str, Any]) -> None:
            manifest["tournament_id"] = "different-tournament"

        self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())
        self.rewrite_sealed_manifest(change_tournament_id)

        exit_code = self.run_demo()

        self.assertNotEqual(exit_code, 0)
        self.assertIn("incompatible with the bundled demo", self.stderr.getvalue())
        self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_resume_rejects_changed_schedule_and_tie_break_keys(self) -> None:
        def change_schedule(manifest: dict[str, Any]) -> None:
            manifest["qualifying_schedule"][0]["fixtures"][0][
                "fixture_id"
            ] = "qualifying-altered"

        def change_tie_break_keys(manifest: dict[str, Any]) -> None:
            first_team_id = next(iter(manifest["tie_break_keys"]))
            manifest["tie_break_keys"][first_team_id] = "0"

        for name, mutate in (
            ("schedule", change_schedule),
            ("tie-break-keys", change_tie_break_keys),
        ):
            with self.subTest(field=name):
                self.directory = (
                    Path(self.temporary_directory.name) / f"altered-{name}"
                )
                self.stdout = StringIO()
                self.stderr = StringIO()
                self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())
                self.rewrite_sealed_manifest(mutate)

                exit_code = self.run_demo()

                self.assertNotEqual(exit_code, 0)
                self.assertIn(
                    "incompatible with the bundled demo", self.stderr.getvalue()
                )
                self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_resume_rejects_a_different_python_runtime_digest(self) -> None:
        self.assertEqual(self.run_demo(), 0, self.stderr.getvalue())
        different_runtime = Path(self.temporary_directory.name) / "python-runtime"
        different_runtime.write_bytes(b"different executable runtime")

        exit_code = self.run_demo(python_executable=different_runtime)

        self.assertNotEqual(exit_code, 0)
        self.assertIn("incompatible with the bundled demo", self.stderr.getvalue())
        self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_invalid_seed_diagnostics_are_nonzero_and_create_nothing(self) -> None:
        for seed in ("-1", str(2**64), "not-a-seed"):
            with self.subTest(seed=seed):
                directory = self.directory.with_name(f"invalid-{seed}")
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "rps_runner.tournament_cli",
                        "demo",
                        "--directory",
                        str(directory),
                        "--seed",
                        seed,
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertFalse(directory.exists())

    def test_exhausted_infrastructure_retries_return_a_concise_diagnostic(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def unavailable_executor(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=True,
                competitive_outcome=None,
                operational_telemetry={"error": "demo process unavailable"},
            )

        exit_code = self.run_demo(match_executor=unavailable_executor)

        self.assertNotEqual(exit_code, 0)
        self.assertEqual([request.attempt_number for request in requests], [1, 2, 3])
        self.assertEqual(
            {request.match_id for request in requests},
            {"qualifying-0001-match-1"},
        )
        self.assertEqual(len(load_competition_records(self.directory)), 0)
        self.assertIn(
            "failed 3 Match Attempts; infrastructure intervention is required",
            self.stderr.getvalue(),
        )

    def test_real_bundled_bot_artifacts_commit_a_300_turn_match(self) -> None:
        exit_code = main(
            [
                "demo",
                "--directory",
                str(self.directory),
                "--seed",
                "12345",
            ],
            project_root=PROJECT_ROOT,
            python_executable=Path(sys.executable),
            stdout=self.stdout,
            stderr=self.stderr,
        )

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        records = load_competition_records(self.directory)
        self.assertEqual(len(records), 1)
        record = records[0].record
        self.assertEqual(len(record["rounds"]), 300)
        self.assertEqual(
            {team_id: len(moves) for team_id, moves in record["moves"].items()},
            {team_id: 300 for team_id in record["team_ids"]},
        )


if __name__ == "__main__":
    unittest.main()
