from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Optional

from rps_runner.tournament.runner import (
    ArtifactDigestVerificationError,
    BotArtifactManifest,
    InfrastructureInterventionRequiredError,
    MatchLimits,
    MatchExecutionRequest,
    Team,
    TournamentCompatibilityError,
    TournamentConfig,
    TournamentRunner,
)
from rps_runner.tournament.match_executor import MatchExecutionResult
from rps_runner.tournament.storage import (
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
)


def artifact(marker: str) -> BotArtifactManifest:
    return BotArtifactManifest(
        artifact_digest=marker * 64,
        language_id="python",
        wrapper_version="python-wrapper-1",
        runtime_digest=(marker.upper() * 64),
        entrypoint=("python3", "bot.py"),
    )


def four_team_roster() -> tuple[Team, ...]:
    return (
        Team("delta", "Delta!", artifact("d")),
        Team("alpha", "Alpha Team", artifact("a")),
        Team("gamma", "Gamma", artifact("c")),
        Team("beta", "Beta", artifact("b")),
    )


def executor_result(
    request: MatchExecutionRequest,
    *,
    winner_team_id: Optional[str],
    score: tuple[int, int] = (0, 0),
    moves: Optional[dict[str, str]] = None,
    rounds: Optional[list[dict[str, object]]] = None,
    faults: Optional[dict[str, Optional[dict[str, object]]]] = None,
) -> MatchExecutionResult:
    return MatchExecutionResult(
        infrastructure_failure=False,
        competitive_outcome={
            "outcome": "draw" if winner_team_id is None else "win",
            "winner_team_id": winner_team_id,
            "score": {
                request.team_a_id: score[0],
                request.team_b_id: score[1],
                "draws": 0,
            },
            "moves": moves
            if moves is not None
            else {request.team_a_id: "", request.team_b_id: ""},
            "rounds": rounds if rounds is not None else [],
            "faults": faults
            if faults is not None
            else {request.team_a_id: None, request.team_b_id: None},
        },
        operational_telemetry={},
    )


class TournamentCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_creation_seals_canonical_roster_schedule_and_initial_projection(
        self,
    ) -> None:
        def must_not_execute(_request: object) -> object:
            self.fail("Tournament creation must not execute a Match")

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="summer-cup-2026",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=must_not_execute,
        )

        manifest = load_manifest(self.directory).manifest
        self.assertEqual(runner.status, "paused")
        self.assertEqual(manifest["tournament_id"], "summer-cup-2026")
        self.assertEqual(manifest["tournament_seed"], "123456789")
        self.assertEqual(manifest["protocol_version"], 1)
        self.assertEqual(manifest["seed_derivation_version"], 1)
        self.assertEqual(manifest["record_schema_version"], 1)
        self.assertEqual(manifest["scoreboard_version"], 1)
        self.assertEqual(manifest["scheduled_turns_per_match"], 300)
        self.assertEqual(manifest["execution_mode"], "step")
        self.assertEqual(
            manifest["match_limits"],
            {
                "first_move_timeout_ms": 250,
                "move_timeout_ms": 50,
                "total_timeout_ms": 2000,
                "stderr_limit_bytes": 65536,
                "stdout_limit_bytes": 4096,
                "cpu_limit_ms": 2000,
                "memory_limit_bytes": 268435456,
                "process_limit": 1,
                "filesystem_write_limit_bytes": 0,
                "network_access_allowed": False,
            },
        )
        self.assertEqual(
            [team["team_id"] for team in manifest["roster"]],
            ["alpha", "beta", "delta", "gamma"],
        )
        self.assertEqual(
            manifest["roster"][0],
            {
                "team_id": "alpha",
                "display_name": "Alpha Team",
                "bot_artifact": {
                    "artifact_digest": "a" * 64,
                    "language_id": "python",
                    "wrapper_version": "python-wrapper-1",
                    "runtime_digest": "A" * 64,
                    "entrypoint": ["python3", "bot.py"],
                },
            },
        )
        fixtures = [
            fixture
            for batch in manifest["qualifying_schedule"]
            for fixture in batch["fixtures"]
        ]
        self.assertEqual(len(fixtures), 6)
        self.assertEqual(
            fixtures[0],
            {
                "fixture_id": "qualifying-0001",
                "ordinal": 1,
                "batch_ordinal": 1,
                "team_ids": ["beta", "delta"],
                "fixture_seed": "12353042038433105865",
            },
        )
        self.assertEqual(
            load_scoreboard_projection(self.directory),
            {
                "version": 1,
                "tournament_id": "summer-cup-2026",
                "status": "paused",
                "phase": "qualifying",
                "teams": [
                    {"team_id": "alpha", "display_name": "Alpha Team"},
                    {"team_id": "beta", "display_name": "Beta"},
                    {"team_id": "delta", "display_name": "Delta!"},
                    {"team_id": "gamma", "display_name": "Gamma"},
                ],
                "fixtures": [
                    {
                        "fixture_id": fixture["fixture_id"],
                        "team_ids": fixture["team_ids"],
                        "status": "scheduled",
                        "matches": [],
                    }
                    for fixture in fixtures
                ],
                "standings": [
                    {
                        "team_id": team_id,
                        "standing_points": 0,
                        "series_wins": 0,
                        "match_differential": 0,
                        "round_differential": 0,
                        "protocol_fault_forfeits": 0,
                        "tie_break_key": tie_break_key,
                    }
                    for team_id, tie_break_key in (
                        ("beta", "1573384823173141085"),
                        ("gamma", "4121194754806403022"),
                        ("delta", "9828001670886502093"),
                        ("alpha", "10397659462510387600"),
                    )
                ],
                "champion": None,
            },
        )

    def test_creation_rejects_invalid_roster_and_artifact_inputs_before_sealing(
        self,
    ) -> None:
        valid = four_team_roster()
        invalid_cases = {
            "fewer than four Teams": valid[:3],
            "more than thirty-two Teams": tuple(
                Team(f"team-{index}", f"Team {index}", artifact("a"))
                for index in range(33)
            ),
            "duplicate Team IDs": valid[:3] + (valid[0],),
            "malformed Team ID": valid[:3]
            + (Team("Bad Team", "Bad", artifact("e")),),
            "empty display name": valid[:3]
            + (Team("empty-name", "", artifact("e")),),
            "non-SHA-256 artifact identity": valid[:3]
            + (
                Team(
                    "bad-artifact",
                    "Bad Artifact",
                    BotArtifactManifest(
                        "not-a-digest",
                        "python",
                        "wrapper-1",
                        "e" * 64,
                        ("python3", "bot.py"),
                    ),
                ),
            ),
            "incomplete immutable runtime identity": valid[:3]
            + (
                Team(
                    "bad-runtime",
                    "Bad Runtime",
                    BotArtifactManifest(
                        "e" * 64,
                        "python",
                        "wrapper-1",
                        "",
                        ("python3", "bot.py"),
                    ),
                ),
            ),
            "shell command instead of argument array": valid[:3]
            + (
                Team(
                    "bad-entrypoint",
                    "Bad Entrypoint",
                    BotArtifactManifest(
                        "e" * 64,
                        "python",
                        "wrapper-1",
                        "e" * 64,
                        "python3 bot.py",  # type: ignore[arg-type]
                    ),
                ),
            ),
        }

        for description, roster in invalid_cases.items():
            with self.subTest(description=description):
                with self.assertRaises(ValueError):
                    TournamentRunner.create(
                        self.directory,
                        tournament_id="invalid",
                        tournament_seed=1,
                        roster=roster,
                        match_executor=lambda request: request,
                    )
                self.assertFalse((self.directory / "manifest.json").exists())

    def test_creation_rejects_an_out_of_range_tournament_seed(self) -> None:
        for seed in (-1, 1 << 64, True):
            with self.subTest(seed=seed):
                with self.assertRaises((TypeError, ValueError)):
                    TournamentRunner.create(
                        self.directory,
                        tournament_id="invalid-seed",
                        tournament_seed=seed,
                        roster=four_team_roster(),
                        match_executor=lambda request: request,
                    )
                self.assertFalse((self.directory / "manifest.json").exists())

    def test_team_and_bot_artifact_inputs_are_immutable_values(self) -> None:
        team = four_team_roster()[0]

        with self.assertRaises(FrozenInstanceError):
            team.display_name = "Changed"  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            team.bot_artifact.wrapper_version = "changed"  # type: ignore[misc]

    def test_custom_config_is_immutable_sealed_and_applied_deterministically(
        self,
    ) -> None:
        limits = MatchLimits(
            first_move_timeout_ms=101,
            move_timeout_ms=102,
            total_timeout_ms=103,
            stderr_limit_bytes=104,
            stdout_limit_bytes=105,
            cpu_limit_ms=106,
            memory_limit_bytes=107,
            process_limit=2,
            filesystem_write_limit_bytes=108,
            network_access_allowed=False,
        )
        config = TournamentConfig(execution_mode="step", match_limits=limits)
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(request, winner_team_id="beta")

        with tempfile.TemporaryDirectory() as other_name:
            other_directory = Path(other_name)
            first = TournamentRunner.create(
                self.directory,
                tournament_id="configured-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                config=config,
                match_executor=execute,
            )
            TournamentRunner.create(
                other_directory,
                tournament_id="configured-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                config=config,
                match_executor=execute,
            )

            manifest = load_manifest(self.directory).manifest
            self.assertEqual(manifest["execution_mode"], "step")
            self.assertEqual(
                manifest["match_limits"],
                {
                    "first_move_timeout_ms": 101,
                    "move_timeout_ms": 102,
                    "total_timeout_ms": 103,
                    "stderr_limit_bytes": 104,
                    "stdout_limit_bytes": 105,
                    "cpu_limit_ms": 106,
                    "memory_limit_bytes": 107,
                    "process_limit": 2,
                    "filesystem_write_limit_bytes": 108,
                    "network_access_allowed": False,
                },
            )
            self.assertEqual(manifest["protocol_version"], 1)
            self.assertEqual(manifest["record_schema_version"], 1)
            self.assertEqual(manifest["seed_derivation_version"], 1)
            self.assertEqual(manifest["scoreboard_version"], 1)
            self.assertEqual(
                (self.directory / "manifest.json").read_bytes(),
                (other_directory / "manifest.json").read_bytes(),
            )

            first.play_next_match()

        self.assertEqual(requests[0].first_move_timeout_ms, 101)
        self.assertEqual(requests[0].move_timeout_ms, 102)
        self.assertEqual(requests[0].total_timeout_ms, 103)
        self.assertEqual(requests[0].stderr_limit_bytes, 104)
        self.assertEqual(requests[0].stdout_limit_bytes, 105)
        self.assertEqual(requests[0].cpu_limit_ms, 106)
        self.assertEqual(requests[0].memory_limit_bytes, 107)
        self.assertEqual(requests[0].process_limit, 2)
        self.assertEqual(requests[0].filesystem_write_limit_bytes, 108)
        self.assertFalse(requests[0].network_access_allowed)
        with self.assertRaises(FrozenInstanceError):
            config.execution_mode = "continuous"  # type: ignore[misc]


class TournamentStepModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_step_executes_exactly_the_next_canonical_match_and_commits_it(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []
        starting_projections: list[dict[str, object]] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            projection = load_scoreboard_projection(self.directory)
            assert projection is not None
            starting_projections.append(projection)
            return executor_result(
                request,
                winner_team_id="beta",
                score=(1, 0),
                moves={"beta": "RP", "delta": "SS"},
                rounds=[
                    {
                        "turn": 0,
                        "moves": {"beta": "R", "delta": "S"},
                        "winner_team_id": "beta",
                    },
                    {
                        "turn": 1,
                        "moves": {"beta": "P", "delta": "S"},
                        "winner_team_id": "delta",
                    },
                ],
                faults={
                    "beta": None,
                    "delta": {"kind": "timeout", "turn": 2},
                },
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="summer-cup-2026",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=execute,
        )

        stored = runner.play_next_match()

        self.assertEqual(len(requests), 1)
        self.assertEqual(starting_projections[0]["status"], "running")
        self.assertEqual(
            starting_projections[0]["fixtures"][0]["status"], "active"
        )
        self.assertEqual(
            requests[0],
            MatchExecutionRequest(
                tournament_id="summer-cup-2026",
                fixture_id="qualifying-0001",
                series_id="qualifying-0001-series",
                match_id="qualifying-0001-match-1",
                attempt_number=1,
                team_a_id="beta",
                team_b_id="delta",
                artifact_digest_a="b" * 64,
                artifact_digest_b="d" * 64,
                match_seed=4868274571950258215,
                bot_visible_seed_a=3184828834756874729,
                bot_visible_seed_b=2450140970035135183,
                protocol_version=1,
                scheduled_turns=300,
                first_move_timeout_ms=250,
                move_timeout_ms=50,
                total_timeout_ms=2000,
                stderr_limit_bytes=65536,
                stdout_limit_bytes=4096,
                cpu_limit_ms=2000,
                memory_limit_bytes=268435456,
                process_limit=1,
                filesystem_write_limit_bytes=0,
                network_access_allowed=False,
            ),
        )
        self.assertEqual(
            stored.record,
            {
                "type": "match_terminal",
                "phase": "qualifying",
                "fixture_id": "qualifying-0001",
                "match_id": "qualifying-0001-match-1",
                "match_ordinal": 1,
                "team_ids": ["beta", "delta"],
                "outcome": "win",
                "winner_team_id": "beta",
                "round_wins": {"beta": 1, "delta": 0},
                "protocol_forfeit_team_id": "delta",
                "moves": {"beta": "RP", "delta": "SS"},
                "rounds": [
                    {
                        "turn": 0,
                        "moves": {"beta": "R", "delta": "S"},
                        "winner_team_id": "beta",
                    },
                    {
                        "turn": 1,
                        "moves": {"beta": "P", "delta": "S"},
                        "winner_team_id": "delta",
                    },
                ],
                "faults": {
                    "beta": None,
                    "delta": {"kind": "timeout", "turn": 2},
                },
                "match_seed": "4868274571950258215",
                "bot_positions": {"a": "beta", "b": "delta"},
                "bot_visible_seeds": {
                    "beta": "3184828834756874729",
                    "delta": "2450140970035135183",
                },
                "artifact_digests": {"beta": "b" * 64, "delta": "d" * 64},
            },
        )
        self.assertEqual(load_competition_records(self.directory), [stored])
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "paused")
        self.assertEqual(
            projection["fixtures"][0],
            {
                "fixture_id": "qualifying-0001",
                "team_ids": ["beta", "delta"],
                "status": "in_progress",
                "matches": [
                    {
                        "match_id": "qualifying-0001-match-1",
                        "outcome": "win",
                        "winner_team_id": "beta",
                    }
                ],
            },
        )

    def test_double_forfeit_record_and_projection_keep_completed_rounds(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome={
                    "outcome": "double_forfeit",
                    "winner_team_id": None,
                    "score": {"beta": 3, "delta": 2, "draws": 1},
                    "moves": {"beta": "RPS", "delta": "SSR"},
                    "rounds": [],
                    "faults": {
                        "beta": {"kind": "timeout", "turn": 6},
                        "delta": {"kind": "invalid_move", "turn": 6},
                    },
                },
                operational_telemetry={},
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="double-forfeit-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=execute,
        )

        stored = runner.play_next_match()

        self.assertEqual(stored.record["round_wins"], {"beta": 3, "delta": 2})
        projection = load_scoreboard_projection(self.directory)
        standings = {
            standing["team_id"]: standing for standing in projection["standings"]
        }
        self.assertEqual(standings["beta"]["round_differential"], 1)
        self.assertEqual(standings["delta"]["round_differential"], -1)
        self.assertEqual(standings["beta"]["match_differential"], 0)
        self.assertEqual(standings["delta"]["match_differential"], 0)

    def test_resume_skips_committed_matches_and_early_finished_series(self) -> None:
        first_requests: list[str] = []

        def first_executor(request: MatchExecutionRequest) -> MatchExecutionResult:
            first_requests.append(request.match_id)
            return executor_result(request, winner_team_id="beta")

        created = TournamentRunner.create(
            self.directory,
            tournament_id="resume-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=first_executor,
        )
        created.play_next_match()

        second_requests: list[str] = []

        def second_executor(request: MatchExecutionRequest) -> MatchExecutionResult:
            second_requests.append(request.match_id)
            return executor_result(request, winner_team_id="beta")

        resumed = TournamentRunner.open(
            self.directory,
            match_executor=second_executor,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        resumed.play_next_match()

        third_requests: list[str] = []

        def third_executor(request: MatchExecutionRequest) -> MatchExecutionResult:
            third_requests.append(request.match_id)
            return executor_result(request, winner_team_id=None)

        resumed_again = TournamentRunner.open(
            self.directory,
            match_executor=third_executor,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        resumed_again.play_next_match()

        self.assertEqual(first_requests, ["qualifying-0001-match-1"])
        self.assertEqual(second_requests, ["qualifying-0001-match-2"])
        self.assertEqual(third_requests, ["qualifying-0002-match-1"])
        self.assertEqual(
            [
                stored.record["match_id"]
                for stored in load_competition_records(self.directory)
            ],
            [
                "qualifying-0001-match-1",
                "qualifying-0001-match-2",
                "qualifying-0002-match-1",
            ],
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["fixtures"][0]["status"], "complete")
        self.assertEqual(
            projection["fixtures"][1]["status"], "in_progress"
        )

    def test_infrastructure_failures_retry_three_identical_attempts_then_pause(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def fail(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=True,
                competitive_outcome=None,
                operational_telemetry={
                    "match_id": request.match_id,
                    "attempt_number": request.attempt_number,
                    "infrastructure_failure": {"kind": "worker_lost"},
                },
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="failure-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=fail,
        )

        with self.assertRaises(InfrastructureInterventionRequiredError) as caught:
            runner.play_next_match()

        self.assertEqual(caught.exception.match_id, "qualifying-0001-match-1")
        self.assertEqual(caught.exception.attempt_count, 3)
        self.assertEqual([request.attempt_number for request in requests], [1, 2, 3])
        first_without_attempt = requests[0].__dict__ | {"attempt_number": 0}
        self.assertEqual(
            [request.__dict__ | {"attempt_number": 0} for request in requests],
            [first_without_attempt, first_without_attempt, first_without_attempt],
        )
        self.assertEqual(load_competition_records(self.directory), [])
        telemetry = load_operational_telemetry(self.directory)
        self.assertEqual(
            [(entry["type"], entry["attempt_number"]) for entry in telemetry],
            [
                ("match_attempt_started", 1),
                ("match_attempt_failed", 1),
                ("match_attempt_started", 2),
                ("match_attempt_failed", 2),
                ("match_attempt_started", 3),
                ("match_attempt_failed", 3),
            ],
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "paused")
        self.assertEqual(projection["fixtures"][0]["status"], "scheduled")

        recovery_requests: list[MatchExecutionRequest] = []

        def recover(request: MatchExecutionRequest) -> MatchExecutionResult:
            recovery_requests.append(request)
            return executor_result(request, winner_team_id="beta")

        runner.match_executor = recover
        recovered = runner.play_next_match()

        self.assertEqual(recovery_requests[0].attempt_number, 4)
        self.assertEqual(recovered.record["match_id"], "qualifying-0001-match-1")

    def test_interrupted_started_attempt_is_consumed_when_resuming(self) -> None:
        interrupted_requests: list[MatchExecutionRequest] = []

        def interrupt(request: MatchExecutionRequest) -> MatchExecutionResult:
            interrupted_requests.append(request)
            raise RuntimeError("worker interrupted")

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="interrupted-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=interrupt,
        )

        with self.assertRaisesRegex(RuntimeError, "worker interrupted"):
            runner.play_next_match()

        self.assertEqual(interrupted_requests[0].attempt_number, 1)
        self.assertEqual(load_competition_records(self.directory), [])
        self.assertEqual(
            [
                (entry["type"], entry["attempt_number"])
                for entry in load_operational_telemetry(self.directory)
            ],
            [("match_attempt_started", 1)],
        )

        resumed_requests: list[MatchExecutionRequest] = []

        def succeed(request: MatchExecutionRequest) -> MatchExecutionResult:
            resumed_requests.append(request)
            return executor_result(request, winner_team_id="beta")

        resumed = TournamentRunner.open(
            self.directory,
            match_executor=succeed,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        resumed.play_next_match()

        self.assertEqual(resumed_requests[0].attempt_number, 2)
        self.assertEqual(
            [
                (entry["type"], entry["attempt_number"])
                for entry in load_operational_telemetry(self.directory)
            ],
            [
                ("match_attempt_started", 1),
                ("match_attempt_started", 2),
            ],
        )


class TournamentResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.runner = TournamentRunner.create(
            self.directory,
            tournament_id="resume-verification-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_open_rejects_incompatible_manifest_versions(self) -> None:
        manifest = load_manifest(self.directory).manifest
        manifest_path = self.directory / "manifest.json"
        manifest_path.unlink()
        seal_manifest(self.directory, manifest | {"protocol_version": 2})

        with self.assertRaises(TournamentCompatibilityError) as caught:
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

        self.assertEqual(caught.exception.field, "protocol_version")
        self.assertEqual(caught.exception.expected, 1)
        self.assertEqual(caught.exception.actual, 2)

    def test_open_requires_every_bot_artifact_digest_to_verify(self) -> None:
        checked: list[tuple[str, str]] = []

        def verify(team_id: str, digest: str) -> bool:
            checked.append((team_id, digest))
            return team_id != "delta"

        with self.assertRaises(ArtifactDigestVerificationError) as caught:
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=verify,
            )

        self.assertEqual(caught.exception.team_id, "delta")
        self.assertIn(("delta", "d" * 64), checked)

    def test_open_rebuilds_missing_and_corrupt_projection_from_records(
        self,
    ) -> None:
        self.runner.play_next_match()
        scoreboard_path = self.directory / "scoreboard.json"
        scoreboard_path.unlink()

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        rebuilt = load_scoreboard_projection(self.directory)
        self.assertEqual(
            rebuilt["fixtures"][0]["matches"][0]["match_id"],
            "qualifying-0001-match-1",
        )

        scoreboard_path.write_bytes(b"not-json")
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        rebuilt_again = load_scoreboard_projection(self.directory)
        self.assertEqual(rebuilt_again, rebuilt)
