from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Optional

from rps_runner.tournament.runner import (
    ArtifactDigestVerificationError,
    BotArtifactManifest,
    InfrastructureInterventionRequiredError,
    MatchLimits,
    MatchExecutionRequest,
    SecurityRulingRequiredError,
    Team,
    TournamentCompatibilityError,
    TournamentConfig,
    TournamentRunner,
)
from rps_runner.tournament.state import (
    TournamentStateError,
    build_security_violation_ruling_record,
    fold_tournament_state,
)
from rps_runner.tournament.seeding import derive_fixture_seed
from rps_runner.tournament.match_executor import MatchExecutionResult
from rps_runner.tournament.immutable import thaw_json
from rps_runner.tournament.locking import (
    TournamentRunLock,
    TournamentRunLockHeldError,
)
from rps_runner.tournament.storage import (
    StoredCompetitionRecord,
    append_competition_record,
    append_operational_telemetry,
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
    write_scoreboard_projection,
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
    score: Optional[tuple[int, int]] = None,
    moves: Optional[dict[str, str]] = None,
    rounds: Optional[list[dict[str, object]]] = None,
    faults: Optional[dict[str, Optional[dict[str, object]]]] = None,
) -> MatchExecutionResult:
    if moves is None and rounds is None:
        team_a_move = "R"
        team_b_move = "R" if winner_team_id is None else "S"
        if winner_team_id == request.team_b_id:
            team_a_move, team_b_move = team_b_move, team_a_move
        round_moves = {
            request.team_a_id: team_a_move,
            request.team_b_id: team_b_move,
        }
        moves = {
            team_id: move * request.scheduled_turns
            for team_id, move in round_moves.items()
        }
        rounds = [
            {
                "turn": turn,
                "moves": round_moves,
                "winner_team_id": winner_team_id,
            }
            for turn in range(request.scheduled_turns)
        ]
    if score is None:
        score = (
            request.scheduled_turns
            * int(winner_team_id == request.team_a_id),
            request.scheduled_turns
            * int(winner_team_id == request.team_b_id),
        )
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
            "moves": moves,
            "rounds": rounds,
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
        self.assertEqual(manifest["record_schema_version"], 2)
        self.assertEqual(manifest["scoreboard_version"], 1)
        self.assertEqual(manifest["scheduled_turns_per_match"], 300)
        self.assertEqual(manifest["execution_mode"], "step")
        self.assertEqual(
            manifest["rules"],
            {
                "scoring": {
                    "series": {
                        "maximum_matches": 3,
                        "match_wins_to_end_early": 2,
                        "series_points": {
                            "match_win": {"numerator": 1, "denominator": 1},
                            "match_draw": {
                                "numerator": 1,
                                "denominator": 2,
                            },
                            "double_forfeit": {
                                "numerator": 0,
                                "denominator": 1,
                            },
                        },
                        "winner": "most_series_points",
                        "qualifying_tie": "series_draw",
                        "playoff_tie": "higher_qualifying_seed_advances",
                    },
                    "qualifying_standing_points": {
                        "series_win": 3,
                        "series_draw": 1,
                        "series_loss": 0,
                    },
                    "protocol_fault_forfeit": {
                        "opponent_receives_match_win": True,
                        "opponent_receives_series_point": True,
                        "retain_completed_rounds_only": True,
                        "counts_in_match_differential": True,
                        "counts_in_protocol_fault_forfeits": True,
                        "synthesize_unplayed_rounds": False,
                    },
                    "double_forfeit": {
                        "winner": None,
                        "series_points_each": {
                            "numerator": 0,
                            "denominator": 1,
                        },
                        "consumes_match_ordinal": True,
                        "retain_completed_rounds_only": True,
                    },
                    "administrative_series_win": {
                        "standing_points": 3,
                        "series_wins": 1,
                        "match_statistics": False,
                        "round_statistics": False,
                        "timing_statistics": False,
                        "fault_statistics": False,
                    },
                },
                "tie_breaks": {
                    "phase": "qualifying",
                    "criteria": [
                        {"field": "standing_points", "direction": "descending"},
                        {"field": "series_wins", "direction": "descending"},
                        {
                            "field": "head_to_head_series_result",
                            "direction": "winner_first",
                            "applies_when": "exactly_two_teams_remain_tied",
                        },
                        {
                            "field": "match_differential",
                            "direction": "descending",
                            "definition": "match_wins_minus_match_losses",
                        },
                        {
                            "field": "round_differential",
                            "direction": "descending",
                            "definition": "round_wins_minus_round_losses",
                        },
                        {
                            "field": "protocol_fault_forfeits",
                            "direction": "ascending",
                        },
                        {"field": "tie_break_key", "direction": "ascending"},
                    ],
                    "disqualified_team_series": {
                        "preserve_played_records": True,
                        "exclude_match_statistics": True,
                        "exclude_round_statistics": True,
                        "exclude_timing_statistics": True,
                        "exclude_fault_statistics": True,
                    },
                    "administrative_series_wins_excluded_from_lower_statistics": True,
                },
                "disqualification": {
                    "cause": "confirmed_security_violation",
                    "scope": "entire_tournament",
                    "rejected_attribution": "infrastructure_failure",
                    "qualifying": {
                        "eligible_opponents_receive_administrative_series_win": True,
                        "skip_future_fixtures": True,
                        "preserve_played_records": True,
                        "exclude_affected_lower_tie_break_statistics": True,
                    },
                    "before_bracket_lock": {
                        "remove_disqualified_team": True,
                        "reselect_playoff_field": True,
                        "reseed_playoff_field": True,
                    },
                    "after_bracket_lock": {
                        "allow_new_qualifying_team": False,
                        "reseed": False,
                        "current_series_opponent_receives_administrative_win": True,
                        (
                            "reinstate_most_recently_eliminated_team_when_next_"
                            "series_not_started"
                        ): True,
                        "after_final_starts_remaining_finalist_is_champion": True,
                    },
                },
                "playoffs": {
                    "field_selection": "highest_ranked_eligible_teams",
                    "maximum_field_size": 4,
                    "bracket_lock": "start_of_first_playoff_match",
                    "formats": {
                        "four_or_more_eligible": {
                            "semifinals": [[1, 4], [2, 3]],
                            "semifinal_winners_play_final": True,
                        },
                        "three_eligible": {
                            "seed_one_advances_to_final": True,
                            "semifinal": [2, 3],
                        },
                        "two_eligible": {"direct_final": [1, 2]},
                        "one_eligible": {
                            "declare_tournament_champion": True,
                            "play_matches": False,
                        },
                        "no_eligible": {
                            "abort_without_champion": True,
                        },
                    },
                },
            },
        )
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
            self.assertEqual(manifest["record_schema_version"], 2)
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

    def _runner_at_playoffs(
        self,
        playoff_executor,
    ) -> TournamentRunner:
        strength = {"alpha": 0, "beta": 1, "gamma": 2, "delta": 3}

        def qualifying_executor(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            winner = min(
                (request.team_a_id, request.team_b_id),
                key=strength.__getitem__,
            )
            return executor_result(request, winner_team_id=winner)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="playoff-step-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=qualifying_executor,
        )
        for _ in range(12):
            runner.play_next_match()
        runner.match_executor = playoff_executor
        return runner

    def test_first_playoff_step_locks_bracket_before_running_canonical_semifinal(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            records = load_competition_records(self.directory)
            self.assertEqual(
                records[-1].record,
                {
                    "type": "playoff_bracket_locked",
                    "phase": "playoff",
                    "fixture_id": "playoff-semifinal-1",
                    "match_id": "playoff-semifinal-1-match-1",
                },
            )
            return executor_result(request, winner_team_id="alpha")

        runner = self._runner_at_playoffs(execute)

        committed = runner.play_next_match()

        self.assertEqual(committed.record["phase"], "playoff")
        self.assertEqual(
            [
                record.record["type"]
                for record in load_competition_records(self.directory)[-2:]
            ],
            ["playoff_bracket_locked", "match_terminal"],
        )
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.fixture_id, "playoff-semifinal-1")
        self.assertEqual(request.series_id, "playoff-semifinal-1-series")
        self.assertEqual(request.match_id, "playoff-semifinal-1-match-1")
        self.assertEqual(request.attempt_number, 1)
        self.assertEqual((request.team_a_id, request.team_b_id), ("delta", "alpha"))
        self.assertEqual(request.match_seed, 3331983333925575056)
        self.assertEqual(request.bot_visible_seed_a, 17977130509488424725)
        self.assertEqual(request.bot_visible_seed_b, 5192250245818424774)
        self.assertEqual(request.artifact_digest_a, "d" * 64)
        self.assertEqual(request.artifact_digest_b, "a" * 64)
        self.assertEqual(request.protocol_version, 1)
        self.assertEqual(request.scheduled_turns, 300)

    def test_playoff_projection_shows_locked_active_and_completed_semifinal(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            projection = load_scoreboard_projection(self.directory)
            self.assertTrue(projection["bracket"]["locked"])
            semifinal = projection["bracket"]["fixtures"][0]
            self.assertEqual(semifinal["status"], "active")
            self.assertEqual(
                semifinal["active_match_id"],
                "playoff-semifinal-1-match-1",
            )
            self.assertNotIn("match_seed", str(projection))
            self.assertNotIn("artifact_digest", str(projection))
            self.assertNotIn("attempt_number", str(projection))
            return executor_result(request, winner_team_id="alpha")

        runner = self._runner_at_playoffs(execute)

        runner.play_next_match()

        projection = load_scoreboard_projection(self.directory)
        semifinal = projection["bracket"]["fixtures"][0]
        self.assertEqual(semifinal["status"], "in_progress")
        self.assertNotIn("active_match_id", semifinal)
        self.assertEqual(
            semifinal["matches"],
            [
                {
                    "match_id": "playoff-semifinal-1-match-1",
                    "outcome": "win",
                    "winner_team_id": "alpha",
                }
            ],
        )

    def test_interrupted_playoff_attempt_preserves_lock_and_restarts_same_match(
        self,
    ) -> None:
        interrupted_requests: list[MatchExecutionRequest] = []

        def interrupt(request: MatchExecutionRequest) -> MatchExecutionResult:
            interrupted_requests.append(request)
            raise RuntimeError("executor interrupted before terminal commit")

        runner = self._runner_at_playoffs(interrupt)

        with self.assertRaisesRegex(RuntimeError, "before terminal commit"):
            runner.play_next_match()

        records_after_interruption = load_competition_records(self.directory)
        self.assertEqual(
            records_after_interruption[-1].record["type"],
            "playoff_bracket_locked",
        )
        self.assertEqual(
            sum(
                record.record["type"] == "playoff_bracket_locked"
                for record in records_after_interruption
            ),
            1,
        )
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Opening must not execute an interrupted playoff Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        resumed_requests: list[MatchExecutionRequest] = []

        def resume(request: MatchExecutionRequest) -> MatchExecutionResult:
            resumed_requests.append(request)
            return executor_result(request, winner_team_id="alpha")

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=resume,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened.play_next_match()

        self.assertEqual(len(interrupted_requests), 1)
        self.assertEqual(len(resumed_requests), 1)
        self.assertEqual(interrupted_requests[0].match_id, resumed_requests[0].match_id)
        self.assertEqual(
            interrupted_requests[0].match_seed,
            resumed_requests[0].match_seed,
        )
        self.assertEqual(
            interrupted_requests[0].team_a_id,
            resumed_requests[0].team_a_id,
        )
        self.assertEqual(
            interrupted_requests[0].team_b_id,
            resumed_requests[0].team_b_id,
        )
        self.assertEqual(interrupted_requests[0].attempt_number, 1)
        self.assertEqual(resumed_requests[0].attempt_number, 2)
        final_records = load_competition_records(self.directory)
        self.assertEqual(
            sum(
                record.record["type"] == "playoff_bracket_locked"
                for record in final_records
            ),
            1,
        )

        next_requests: list[MatchExecutionRequest] = []

        def execute_next(request: MatchExecutionRequest) -> MatchExecutionResult:
            next_requests.append(request)
            return executor_result(request, winner_team_id="alpha")

        reopened_after_commit = TournamentRunner.open(
            self.directory,
            match_executor=execute_next,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened_after_commit.play_next_match()
        self.assertEqual(
            [request.match_id for request in next_requests],
            ["playoff-semifinal-1-match-2"],
        )

    def test_open_does_not_infer_bracket_lock_from_projection_or_telemetry(
        self,
    ) -> None:
        runner = self._runner_at_playoffs(
            lambda request: executor_result(request, winner_team_id="alpha")
        )
        stale_projection = load_scoreboard_projection(self.directory)
        stale_projection["bracket"]["locked"] = True
        stale_projection["bracket"]["fixtures"][0]["status"] = "active"
        write_scoreboard_projection(self.directory, stale_projection)
        append_operational_telemetry(
            self.directory,
            {
                "type": "match_attempt_started",
                "tournament_id": "playoff-step-cup",
                "fixture_id": "playoff-semifinal-1",
                "match_id": "playoff-semifinal-1-match-1",
                "attempt_number": 1,
            },
        )

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="alpha"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        projection = load_scoreboard_projection(self.directory)
        self.assertFalse(projection["bracket"]["locked"])
        self.assertFalse(
            any(
                record.record["type"] == "playoff_bracket_locked"
                for record in load_competition_records(self.directory)
            )
        )
        reopened.play_next_match()
        lock_records = [
            record.record
            for record in load_competition_records(self.directory)
            if record.record["type"] == "playoff_bracket_locked"
        ]
        self.assertEqual(len(lock_records), 1)

    def test_step_mode_completes_standard_playoffs_in_canonical_series_order(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            winner = None if request.fixture_id == "playoff-semifinal-1" else "beta"
            return executor_result(request, winner_team_id=winner)

        runner = self._runner_at_playoffs(execute)

        for expected_request_count in range(1, 8):
            committed = runner.play_next_match()
            self.assertIsNotNone(committed)
            self.assertEqual(len(requests), expected_request_count)

        self.assertEqual(
            [(request.fixture_id, request.match_id) for request in requests],
            [
                ("playoff-semifinal-1", "playoff-semifinal-1-match-1"),
                ("playoff-semifinal-1", "playoff-semifinal-1-match-2"),
                ("playoff-semifinal-1", "playoff-semifinal-1-match-3"),
                ("playoff-semifinal-2", "playoff-semifinal-2-match-1"),
                ("playoff-semifinal-2", "playoff-semifinal-2-match-2"),
                ("playoff-final", "playoff-final-match-1"),
                ("playoff-final", "playoff-final-match-2"),
            ],
        )
        self.assertIsNone(runner.play_next_match())
        self.assertEqual(len(requests), 7)
        records = load_competition_records(self.directory)
        playoff_matches = [
            record.record
            for record in records
            if record.record.get("type") == "match_terminal"
            and record.record.get("phase") == "playoff"
        ]
        self.assertEqual(len(playoff_matches), 7)
        self.assertEqual(
            records[-1].record,
            {
                "type": "tournament_champion_declared",
                "phase": "playoff",
                "fixture_id": "playoff-final",
                "team_id": "beta",
            },
        )
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(
            [series.winner for series in state.playoff_series],
            ["alpha", "beta", "beta"],
        )
        self.assertEqual(state.champion_team_id, "beta")
        self.assertIsNone(state.next_playoff_match)
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(
            [fixture["status"] for fixture in projection["bracket"]["fixtures"]],
            ["complete", "complete", "complete"],
        )
        self.assertEqual(projection["status"], "complete")
        self.assertEqual(projection["champion"], "beta")
        self.assertEqual(
            projection["bracket"]["fixtures"][2]["team_ids"],
            ["alpha", "beta"],
        )

    def test_three_match_tied_final_declares_higher_qualifying_seed(self) -> None:
        requests: list[MatchExecutionRequest] = []
        final_winners = iter(("alpha", "beta", None))

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            if request.fixture_id == "playoff-semifinal-1":
                winner = "alpha"
            elif request.fixture_id == "playoff-semifinal-2":
                winner = "beta"
            else:
                winner = next(final_winners)
            return executor_result(request, winner_team_id=winner)

        runner = self._runner_at_playoffs(execute)
        for expected_count in range(1, 8):
            runner.play_next_match()
            self.assertEqual(len(requests), expected_count)

        final_requests = [
            request for request in requests if request.fixture_id == "playoff-final"
        ]
        self.assertEqual(
            [request.match_id for request in final_requests],
            [
                "playoff-final-match-1",
                "playoff-final-match-2",
                "playoff-final-match-3",
            ],
        )
        self.assertEqual(
            [request.attempt_number for request in final_requests], [1, 1, 1]
        )
        self.assertEqual(
            [
                (
                    request.match_seed,
                    request.team_a_id,
                    request.team_b_id,
                    request.bot_visible_seed_a,
                    request.bot_visible_seed_b,
                    request.artifact_digest_a,
                    request.artifact_digest_b,
                )
                for request in final_requests
            ],
            [
                (
                    11911741057564611374,
                    "alpha",
                    "beta",
                    14822862918095397444,
                    11126564879036148063,
                    "a" * 64,
                    "b" * 64,
                ),
                (
                    12067585609778501959,
                    "beta",
                    "alpha",
                    12378939776820723690,
                    10777591539846445942,
                    "b" * 64,
                    "a" * 64,
                ),
                (
                    6091937764040474637,
                    "alpha",
                    "beta",
                    2402231786463244854,
                    16393763229817431993,
                    "a" * 64,
                    "b" * 64,
                ),
            ],
        )
        state = fold_tournament_state(
            load_manifest(self.directory).manifest,
            load_competition_records(self.directory),
        )
        self.assertEqual(state.playoff_series[-1].series_points["alpha"], 1.5)
        self.assertEqual(state.playoff_series[-1].series_points["beta"], 1.5)
        self.assertEqual(state.champion_team_id, "alpha")

    def test_open_recovers_champion_after_final_terminal_commit_without_reexecution(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            winner = (
                "alpha"
                if request.fixture_id != "playoff-semifinal-2"
                else "beta"
            )
            return executor_result(request, winner_team_id=winner)

        runner = self._runner_at_playoffs(execute)
        for _ in range(5):
            runner.play_next_match()

        def fail_champion_append(
            directory: Path, record: dict[str, object]
        ) -> object:
            if record.get("type") == "tournament_champion_declared":
                raise RuntimeError("interrupted before champion commit")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=fail_champion_append,
        ):
            with self.assertRaisesRegex(RuntimeError, "before champion commit"):
                runner.play_next_match()

        interrupted_records = load_competition_records(self.directory)
        self.assertEqual(
            interrupted_records[-1].record["match_id"], "playoff-final-match-2"
        )
        self.assertFalse(
            any(
                record.record["type"] == "tournament_champion_declared"
                for record in interrupted_records
            )
        )

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not rerun the committed final Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        recovered_records = load_competition_records(self.directory)
        self.assertEqual(
            recovered_records[-1].record["type"],
            "tournament_champion_declared",
        )
        self.assertEqual(reopened.status, "complete")
        self.assertIsNone(reopened.play_next_match())
        completed_projection = load_scoreboard_projection(self.directory)
        (self.directory / "scoreboard.json").unlink()
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Completed Tournament must execute nothing"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(load_competition_records(self.directory), recovered_records)
        self.assertEqual(
            load_scoreboard_projection(self.directory), completed_projection
        )

    def test_final_match_retry_reuses_canonical_execution_identity(self) -> None:
        final_attempts: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.fixture_id == "playoff-semifinal-1":
                return executor_result(request, winner_team_id="alpha")
            if request.fixture_id == "playoff-semifinal-2":
                return executor_result(request, winner_team_id="beta")
            final_attempts.append(request)
            final_projection = load_scoreboard_projection(self.directory)["bracket"][
                "fixtures"
            ][2]
            self.assertEqual(final_projection["status"], "active")
            self.assertEqual(final_projection["active_match_id"], request.match_id)
            if len(final_attempts) == 1:
                return MatchExecutionResult(
                    infrastructure_failure=True,
                    competitive_outcome=None,
                    operational_telemetry={"error": "transient final failure"},
                )
            return executor_result(request, winner_team_id="alpha")

        runner = self._runner_at_playoffs(execute)
        for _ in range(5):
            runner.play_next_match()

        self.assertEqual(
            [request.attempt_number for request in final_attempts], [1, 2]
        )
        first, retry = final_attempts
        self.assertEqual(first.match_id, "playoff-final-match-1")
        self.assertEqual(first.match_seed, retry.match_seed)
        self.assertEqual(
            (first.team_a_id, first.team_b_id),
            (retry.team_a_id, retry.team_b_id),
        )
        self.assertEqual(
            (first.bot_visible_seed_a, first.bot_visible_seed_b),
            (retry.bot_visible_seed_a, retry.bot_visible_seed_b),
        )
        self.assertEqual(
            (first.artifact_digest_a, first.artifact_digest_b),
            (retry.artifact_digest_a, retry.artifact_digest_b),
        )
        final_projection = load_scoreboard_projection(self.directory)["bracket"][
            "fixtures"
        ][2]
        self.assertEqual(final_projection["status"], "in_progress")
        self.assertEqual(
            final_projection["matches"],
            [
                {
                    "match_id": "playoff-final-match-1",
                    "outcome": "win",
                    "winner_team_id": "alpha",
                }
            ],
        )

    def test_fold_rejects_invalid_champion_histories(self) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            winner = (
                "alpha"
                if request.fixture_id != "playoff-semifinal-2"
                else "beta"
            )
            return executor_result(request, winner_team_id=winner)

        runner = self._runner_at_playoffs(execute)
        for _ in range(6):
            runner.play_next_match()
        manifest = load_manifest(self.directory).manifest
        valid = load_competition_records(self.directory)
        champion = thaw_json(valid[-1].record)

        contradictory = dict(champion, team_id="beta")
        malformed = dict(champion, reason="score")
        invalid_histories = (
            (
                "duplicate",
                "more than once",
                valid
                + [
                    StoredCompetitionRecord(
                        len(valid) + 1, champion, "duplicate"
                    )
                ],
            ),
            (
                "contradictory",
                "non-canonical",
                valid[:-1]
                + [
                    StoredCompetitionRecord(
                        len(valid), contradictory, "contradictory"
                    )
                ],
            ),
            (
                "malformed",
                "non-canonical",
                valid[:-1]
                + [StoredCompetitionRecord(len(valid), malformed, "malformed")],
            ),
            (
                "premature",
                "before the final completed",
                valid[:-2]
                + [
                    StoredCompetitionRecord(
                        len(valid) - 1, champion, "premature"
                    )
                ],
            ),
        )
        for description, message, records in invalid_histories:
            with self.subTest(description=description):
                with self.assertRaisesRegex(TournamentStateError, message):
                    fold_tournament_state(manifest, records)

    def test_final_qualifying_step_creates_playoff_bracket_without_running_playoff_match(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []
        strength = {"alpha": 0, "beta": 1, "gamma": 2, "delta": 3}

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            winner = min(
                (request.team_a_id, request.team_b_id),
                key=strength.__getitem__,
            )
            return executor_result(request, winner_team_id=winner)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="playoff-transition-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=execute,
        )

        for _ in range(12):
            committed = runner.play_next_match()
            self.assertIsNotNone(committed)

        self.assertEqual(len(requests), 12)
        self.assertTrue(
            all(request.fixture_id.startswith("qualifying-") for request in requests)
        )
        records = load_competition_records(self.directory)
        self.assertEqual(len(records), 13)
        bracket_record = records[-1].record
        self.assertEqual(
            bracket_record,
            {
                "type": "playoff_bracket_created",
                "phase": "playoff",
                "seeds": [
                    {"seed": 1, "team_id": "alpha"},
                    {"seed": 2, "team_id": "beta"},
                    {"seed": 3, "team_id": "gamma"},
                    {"seed": 4, "team_id": "delta"},
                ],
                "fixtures": [
                    {
                        "fixture_id": "playoff-semifinal-1",
                        "stage": "semifinal",
                        "team_ids": ["alpha", "delta"],
                        "fixture_seed": str(
                            derive_fixture_seed(
                                123456789, "playoff-semifinal-1"
                            )
                        ),
                    },
                    {
                        "fixture_id": "playoff-semifinal-2",
                        "stage": "semifinal",
                        "team_ids": ["beta", "gamma"],
                        "fixture_seed": str(
                            derive_fixture_seed(
                                123456789, "playoff-semifinal-2"
                            )
                        ),
                    },
                    {
                        "fixture_id": "playoff-final",
                        "stage": "final",
                        "team_ids": [None, None],
                        "fixture_seed": str(
                            derive_fixture_seed(123456789, "playoff-final")
                        ),
                    },
                ],
            },
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["phase"], "playoff")
        self.assertFalse(projection["bracket"]["locked"])
        self.assertEqual(projection["bracket"]["seeds"], bracket_record["seeds"])
        self.assertEqual(
            projection["bracket"]["fixtures"],
            [
                {**fixture, "status": "scheduled", "matches": []}
                for fixture in bracket_record["fixtures"]
            ],
        )

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Opening a Tournament must not execute a playoff Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        self.assertEqual(load_competition_records(self.directory), records)
        self.assertEqual(
            load_scoreboard_projection(self.directory)["bracket"],
            projection["bracket"],
        )

    def test_resume_recovers_missing_playoff_transition_before_the_next_step(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="interrupted-playoff-transition-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=execute,
        )
        for _ in range(11):
            runner.play_next_match()

        def fail_bracket_append(
            directory: Path, record: dict[str, object]
        ) -> object:
            if record.get("type") == "playoff_bracket_created":
                raise RuntimeError("interrupted before bracket commit")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=fail_bracket_append,
        ):
            with self.assertRaisesRegex(RuntimeError, "before bracket commit"):
                runner.play_next_match()

        self.assertEqual(len(requests), 12)
        self.assertEqual(len(load_competition_records(self.directory)), 12)
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Resuming a phase transition must not execute a Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        recovered_records = load_competition_records(self.directory)
        self.assertEqual(len(recovered_records), 13)
        self.assertEqual(
            recovered_records[-1].record["type"], "playoff_bracket_created"
        )
        self.assertEqual(
            load_scoreboard_projection(self.directory)["phase"], "playoff"
        )

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Repeated resume must not execute a Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(load_competition_records(self.directory), recovered_records)

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
                score=(1, 1),
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
                "round_wins": {"beta": 1, "delta": 1},
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
                    "moves": {"beta": "RPSRPS", "delta": "SRPPSS"},
                    "rounds": [
                        {
                            "turn": turn,
                            "moves": {"beta": beta, "delta": delta},
                            "winner_team_id": winner,
                        }
                        for turn, (beta, delta, winner) in enumerate(
                            (
                                ("R", "S", "beta"),
                                ("P", "R", "beta"),
                                ("S", "P", "beta"),
                                ("R", "P", "delta"),
                                ("P", "S", "delta"),
                                ("S", "S", None),
                            )
                        )
                    ],
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

    def test_suspected_security_violation_pauses_with_evidence_only_in_telemetry(
        self,
    ) -> None:
        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={
                    "raw_security_evidence": {"blocked_host": "169.254.1.1"}
                },
                suspected_security_violation_team_id="beta",
                evidence_link="evidence:security-cup/incident-1",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="security-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )

        incident = runner.play_next_match()

        self.assertEqual(
            incident.record,
            {
                "type": "security_violation_suspected",
                "phase": "qualifying",
                "fixture_id": "qualifying-0001",
                "match_id": "qualifying-0001-match-1",
                "match_ordinal": 1,
                "team_ids": ["beta", "delta"],
                "suspected_team_id": "beta",
                "evidence_link": "evidence:security-cup/incident-1",
            },
        )
        with self.assertRaises(SecurityRulingRequiredError):
            runner.play_next_match()
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "awaiting_security_ruling")
        self.assertEqual(
            projection["security_review"],
            {
                "fixture_id": "qualifying-0001",
                "match_id": "qualifying-0001-match-1",
                "suspected_team_id": "beta",
            },
        )
        self.assertNotIn("evidence", str(projection))
        self.assertIn(
            "raw_security_evidence",
            load_operational_telemetry(self.directory)[1],
        )
        write_scoreboard_projection(self.directory, {"status": "stale"})
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "A pending ruling must survive recovery"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(reopened.status, "awaiting_security_ruling")
        with self.assertRaises(SecurityRulingRequiredError):
            reopened.play_next_match()

    def test_security_evidence_variance_does_not_change_canonical_incident(self) -> None:
        incidents = []
        telemetry_values = []
        for suffix, raw_evidence in (("one", "host-a"), ("two", "host-b")):
            directory = self.directory / suffix
            runner = TournamentRunner.create(
                directory,
                tournament_id="evidence-separation-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                match_executor=lambda request, raw=raw_evidence: MatchExecutionResult(
                    infrastructure_failure=False,
                    competitive_outcome=None,
                    operational_telemetry={"raw_security_evidence": raw},
                    suspected_security_violation_team_id="beta",
                    evidence_link="evidence:evidence-separation-cup/incident-1",
                ),
            )
            runner.play_next_match()
            incidents.append(load_competition_records(directory)[0])
            telemetry_values.append(load_operational_telemetry(directory)[1])

        self.assertEqual(incidents[0], incidents[1])
        self.assertNotEqual(telemetry_values[0], telemetry_values[1])

    def test_playoff_suspicion_never_appends_a_qualifying_incident(self) -> None:
        runner = self._runner_at_playoffs(
            lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:playoff/incident-1",
            )
        )

        with self.assertRaisesRegex(
            NotImplementedError, "Playoff Security Violation"
        ):
            runner.play_next_match()

        records = load_competition_records(self.directory)
        self.assertEqual(records[-1].record["type"], "playoff_bracket_locked")
        self.assertNotIn(
            "security_violation_suspected",
            [record.record["type"] for record in records],
        )
        fold_tournament_state(load_manifest(self.directory).manifest, records)

    def test_rejected_attribution_retries_identical_match_with_absolute_attempt(
        self,
    ) -> None:
        requests: list[MatchExecutionRequest] = []

        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id="beta",
                evidence_link="evidence:rejected-cup/incident-1",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="rejected-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )
        runner.play_next_match()
        ruling = runner.reject_security_violation(
            organizer_id="organizer-7", note="host agent caused the request"
        )
        runner.match_executor = lambda request: (
            requests.append(request) or executor_result(request, winner_team_id="beta")
        )

        terminal = runner.play_next_match()

        self.assertEqual(ruling.record["decision"], "rejected")
        self.assertEqual(ruling.record["organizer_id"], "organizer-7")
        self.assertEqual(ruling.record["reason_code"], "attribution_not_confirmed")
        self.assertEqual(terminal.record["match_id"], "qualifying-0001-match-1")
        self.assertEqual([request.attempt_number for request in requests], [1, 2])
        first = requests[0].__dict__ | {"attempt_number": 0}
        self.assertEqual(requests[1].__dict__ | {"attempt_number": 0}, first)

    def test_confirmed_violation_disqualifies_and_canonically_skips_fixtures(
        self,
    ) -> None:
        attempts: list[MatchExecutionRequest] = []

        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            attempts.append(request)
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id="beta",
                evidence_link="evidence:confirmed-cup/incident-1",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="confirmed-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )
        runner.play_next_match()
        ruling = runner.confirm_security_violation(
            organizer_id="organizer-9", note="network policy escape confirmed"
        )

        records = load_competition_records(self.directory)
        self.assertEqual(
            [record.record["type"] for record in records],
            [
                "security_violation_suspected",
                "security_violation_ruling",
                "administrative_series_win",
                "administrative_series_win",
                "administrative_series_win",
            ],
        )
        self.assertEqual(
            [record.record["fixture_id"] for record in records[2:]],
            ["qualifying-0001", "qualifying-0003", "qualifying-0005"],
        )
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(state.disqualified_team_ids, ("beta",))
        self.assertEqual(state.next_qualifying_match.fixture_id, "qualifying-0002")
        self.assertNotIn("beta", {standing.team_id for standing in state.standings})
        self.assertTrue(all(item.standing_points == 3 for item in state.standings))
        projection = load_scoreboard_projection(self.directory)
        beta = next(team for team in projection["teams"] if team["team_id"] == "beta")
        self.assertEqual(beta["status"], "disqualified")
        self.assertEqual(
            projection["fixtures"][0]["administrative_series_win"],
            {"winner_team_id": "delta", "reason_code": "opponent_disqualified"},
        )
        self.assertEqual(ruling.record["organizer_id"], "organizer-9")

    def test_open_finishes_canonical_admin_records_after_confirmed_ruling(self) -> None:
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="ruling-recovery-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id="beta",
                evidence_link="evidence:ruling-recovery-cup/incident-1",
            ),
        )
        runner.play_next_match()
        records = load_competition_records(self.directory)
        pending = fold_tournament_state(
            load_manifest(self.directory).manifest, records
        ).pending_security_ruling
        append_competition_record(
            self.directory,
            build_security_violation_ruling_record(
                pending,
                decision="confirmed",
                organizer_id="organizer-11",
                reason_code="confirmed_prohibited_behavior",
            ),
        )

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not execute a skipped Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        recovered = load_competition_records(self.directory)
        self.assertEqual(
            [record.record["fixture_id"] for record in recovered[2:]],
            ["qualifying-0001", "qualifying-0003", "qualifying-0005"],
        )

    def test_disqualification_preserves_played_match_but_excludes_its_statistics(
        self,
    ) -> None:
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="played-evidence-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
        )
        played = runner.play_next_match()
        runner.match_executor = lambda request: MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=None,
            operational_telemetry={"raw_security_evidence": "variable"},
            suspected_security_violation_team_id="beta",
            evidence_link="evidence:played-evidence-cup/incident-1",
        )
        runner.play_next_match()
        runner.confirm_security_violation(organizer_id="organizer-12")

        records = load_competition_records(self.directory)
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        first_series = state.qualifying_series[0]
        self.assertEqual(first_series.match_count, 1)
        self.assertEqual(first_series.matches[0].winner, "beta")
        self.assertEqual(records[0], played)
        standings = {standing.team_id: standing for standing in state.standings}
        self.assertEqual(standings["delta"].match_losses, 0)
        self.assertEqual(standings["delta"].round_losses, 0)
        self.assertEqual(standings["delta"].standing_points, 3)

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

    def test_open_rejects_changed_nested_manifest_rule(self) -> None:
        manifest = thaw_json(load_manifest(self.directory).manifest)
        manifest["rules"]["scoring"]["qualifying_standing_points"][
            "series_win"
        ] = 2
        manifest_path = self.directory / "manifest.json"
        manifest_path.unlink()
        seal_manifest(self.directory, manifest)

        with self.assertRaises(TournamentCompatibilityError) as caught:
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

        self.assertEqual(caught.exception.field, "rules")

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

    def test_open_rejects_a_hashed_but_semantically_impossible_record(self) -> None:
        fixture = load_manifest(self.directory).manifest[
            "qualifying_schedule"
        ][0]["fixtures"][0]
        team_one_id, team_two_id = fixture["team_ids"]
        append_competition_record(
            self.directory,
            {
                "type": "match_terminal",
                "phase": "qualifying",
                "fixture_id": fixture["fixture_id"],
                "match_id": f"{fixture['fixture_id']}-match-2",
                "match_ordinal": 2,
                "team_ids": [team_one_id, team_two_id],
                "outcome": "win",
                "winner_team_id": team_one_id,
                "round_wins": {team_one_id: 1, team_two_id: 0},
                "protocol_forfeit_team_id": None,
            },
        )

        with self.assertRaisesRegex(TournamentStateError, "Match ordinal"):
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

    def test_open_rebuilds_a_valid_but_stale_projection_from_records(self) -> None:
        self.runner.play_next_match()
        write_scoreboard_projection(
            self.directory,
            {
                "version": 1,
                "tournament_id": "resume-verification-cup",
                "status": "running",
                "phase": "qualifying",
                "teams": [],
                "fixtures": [],
                "standings": [],
                "champion": None,
            },
        )

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        rebuilt = load_scoreboard_projection(self.directory)
        self.assertEqual(rebuilt["status"], "paused")
        self.assertEqual(
            rebuilt["fixtures"][0]["matches"][0]["match_id"],
            "qualifying-0001-match-1",
        )

    def test_open_verifies_the_sealed_manifest_under_the_run_lock(self) -> None:
        verified_tournament_ids: list[str] = []

        def verify_sealed_manifest(manifest: dict[str, object]) -> None:
            verified_tournament_ids.append(str(manifest["tournament_id"]))
            with self.assertRaises(TournamentRunLockHeldError):
                with TournamentRunLock(self.directory):
                    pass

        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
            sealed_manifest_verifier=verify_sealed_manifest,
        )

        self.assertEqual(verified_tournament_ids, ["resume-verification-cup"])

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
