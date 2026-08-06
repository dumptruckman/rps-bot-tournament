from __future__ import annotations

import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Optional

from rps_runner.tournament.competition import Phase
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
    build_operator_abort_record,
    build_security_violation_ruling_record,
    fold_tournament_state,
)
from rps_runner.tournament.seeding import derive_fixture_seed, derive_match_seed
from rps_runner.tournament.match_executor import MatchExecutionResult
from rps_runner.tournament.immutable import thaw_json
from rps_runner.tournament.locking import (
    TournamentRunLock,
    TournamentRunLockHeldError,
)
from rps_runner.tournament.storage import (
    IntegrityError,
    StoredCompetitionRecord,
    append_competition_record,
    append_operational_telemetry,
    load_competition_records,
    load_control_state,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
    update_control_state,
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
        self.assertEqual(manifest["record_schema_version"], 4)
        self.assertEqual(manifest["scoreboard_version"], 1)
        self.assertEqual(manifest["scheduled_turns_per_match"], 300)
        self.assertEqual(manifest["execution_mode"], "step")
        self.assertEqual(manifest["continuous_parallelism"], 1)
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
        config = TournamentConfig(
            execution_mode="step",
            match_limits=limits,
            continuous_parallelism=3,
        )
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
            self.assertEqual(manifest["continuous_parallelism"], 3)
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
            self.assertEqual(manifest["record_schema_version"], 4)
            self.assertEqual(manifest["seed_derivation_version"], 1)
            self.assertEqual(manifest["scoreboard_version"], 1)
            self.assertEqual(
                (self.directory / "manifest.json").read_bytes(),
                (other_directory / "manifest.json").read_bytes(),
            )

            first.play_next_match()

        self.assertEqual(len(requests), 1)
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
        with self.assertRaises(FrozenInstanceError):
            config.continuous_parallelism = 4  # type: ignore[misc]

    def test_creation_rejects_invalid_continuous_parallelism_before_sealing(
        self,
    ) -> None:
        for parallelism in (0, -1, True, 1.5):
            with self.subTest(parallelism=parallelism):
                with self.assertRaises((TypeError, ValueError)):
                    TournamentRunner.create(
                        self.directory,
                        tournament_id="invalid-parallelism",
                        tournament_seed=1,
                        roster=four_team_roster(),
                        config=TournamentConfig(
                            continuous_parallelism=parallelism,  # type: ignore[arg-type]
                        ),
                        match_executor=lambda request: request,
                    )
                self.assertFalse((self.directory / "manifest.json").exists())


class TournamentContinuousModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_continuous_mode_completes_the_canonical_tournament(self) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="continuous-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=execute,
        )

        committed = runner.run_continuously()

        self.assertEqual(len(committed), 18)
        self.assertEqual(len(requests), 18)
        self.assertTrue(
            all(not request.match_id.endswith("-match-3") for request in requests)
        )
        self.assertEqual(
            [record.record["match_id"] for record in committed],
            [request.match_id for request in requests],
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "complete")
        self.assertEqual(projection["phase"], "playoff")
        self.assertIsNotNone(projection["champion"])
        self.assertTrue(
            all(
                fixture["status"] == "complete"
                for fixture in projection["fixtures"]
            )
        )
        self.assertTrue(
            all(
                fixture["status"] == "complete"
                for fixture in projection["bracket"]["fixtures"]
            )
        )

    def test_configured_parallel_matches_overlap_and_commit_canonically(self) -> None:
        active_team_ids: set[str] = set()
        active_count = 0
        maximum_active = 0
        match_ids: list[str] = []
        overlap = threading.Event()
        projection_checked = threading.Event()
        lock = threading.Lock()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            nonlocal active_count, maximum_active
            request_team_ids = {request.team_a_id, request.team_b_id}
            check_projection = False
            with lock:
                self.assertTrue(active_team_ids.isdisjoint(request_team_ids))
                match_ids.append(request.match_id)
                active_team_ids.update(request_team_ids)
                active_count += 1
                maximum_active = max(maximum_active, active_count)
                if active_count == 2:
                    overlap.set()
                    check_projection = True
            self.assertTrue(overlap.wait(5), "eligible Matches did not overlap")
            if check_projection:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    projection = load_scoreboard_projection(self.directory)
                    active_fixtures = [
                        fixture
                        for fixture in projection["fixtures"]
                        if fixture["status"] == "active"
                    ]
                    if len(active_fixtures) == 2:
                        self.assertTrue(
                            all("active_match_id" in fixture for fixture in active_fixtures)
                        )
                        self.assertNotIn("evidence", projection)
                        projection_checked.set()
                        break
                    time.sleep(0.01)
            self.assertTrue(projection_checked.wait(5))
            result = executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )
            with lock:
                active_team_ids.difference_update(request_team_ids)
                active_count -= 1
            return result

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-overlap-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )

        committed = runner.run_continuously()

        self.assertEqual(maximum_active, 2)
        self.assertTrue(projection_checked.is_set())
        self.assertEqual(len(committed), 18)
        self.assertTrue(
            all(not match_id.endswith("-match-3") for match_id in match_ids)
        )
        self.assertEqual(runner.status, "complete")

    def test_reversed_completion_matches_limit_one_records_and_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as sequential_name:
            sequential_directory = Path(sequential_name)
            sequential = TournamentRunner.create(
                sequential_directory,
                tournament_id="timing-invariant-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                config=TournamentConfig(execution_mode="continuous"),
                match_executor=lambda request: executor_result(
                    request,
                    winner_team_id=min(request.team_a_id, request.team_b_id),
                ),
            )
            sequential.run_continuously()
            expected_records = load_competition_records(sequential_directory)
            expected_projection = load_scoreboard_projection(sequential_directory)
            expected_state = fold_tournament_state(
                load_manifest(sequential_directory).manifest, expected_records
            )

        later_match_finished = threading.Event()

        def reversed_completion(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            if request.match_id == "qualifying-0001-match-1":
                self.assertTrue(later_match_finished.wait(5))
            elif request.match_id == "qualifying-0002-match-1":
                later_match_finished.set()
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        parallel = TournamentRunner.create(
            self.directory,
            tournament_id="timing-invariant-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=reversed_completion,
        )
        parallel.run_continuously()
        actual_records = load_competition_records(self.directory)

        self.assertEqual(
            [thaw_json(record.record) for record in actual_records],
            [thaw_json(record.record) for record in expected_records],
        )
        self.assertEqual(
            [record.content_hash for record in actual_records],
            [record.content_hash for record in expected_records],
        )
        self.assertEqual(
            load_scoreboard_projection(self.directory), expected_projection
        )
        self.assertEqual(
            fold_tournament_state(
                load_manifest(self.directory).manifest, actual_records
            ),
            expected_state,
        )

    def test_parallel_pause_commits_only_prefix_and_resume_skips_it(self) -> None:
        both_started = threading.Event()
        release = threading.Event()
        started_ids: list[str] = []
        lock = threading.Lock()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            with lock:
                started_ids.append(request.match_id)
                if len(started_ids) == 2:
                    both_started.set()
            self.assertTrue(release.wait(5))
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-pause-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )
        result: list[tuple[StoredCompetitionRecord, ...]] = []
        worker = threading.Thread(target=lambda: result.append(runner.start()))
        worker.start()
        self.assertTrue(both_started.wait(5))
        runner.request_pause()
        release.set()
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(result[0]), 1)
        committed_id = result[0][0].record["match_id"]
        records = load_competition_records(self.directory)
        self.assertEqual(
            [record.record["match_id"] for record in records], [committed_id]
        )

        resumed_ids: list[str] = []
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: (
                resumed_ids.append(request.match_id)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened.resume()

        self.assertNotIn(committed_id, resumed_ids)
        self.assertIn("qualifying-0002-match-1", resumed_ids)
        self.assertEqual(reopened.status, "complete")

    def test_parallel_security_violation_never_commits_later_completion(
        self,
    ) -> None:
        release_first = threading.Event()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.match_id == "qualifying-0001-match-1":
                self.assertTrue(release_first.wait(5))
                return MatchExecutionResult(
                    infrastructure_failure=False,
                    competitive_outcome=None,
                    operational_telemetry={},
                    suspected_security_violation_team_id=request.team_a_id,
                    evidence_link="evidence:parallel-security",
                )
            if request.match_id == "qualifying-0002-match-1":
                release_first.set()
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-security-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )

        self.assertEqual(runner.run_continuously(), ())

        records = load_competition_records(self.directory)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record["type"], "security_violation_suspected")
        self.assertEqual(records[0].record["match_id"], "qualifying-0001-match-1")
        self.assertEqual(runner.status, "awaiting_security_ruling")

    def test_parallel_infrastructure_failure_preserves_only_committed_prefix(
        self,
    ) -> None:
        failure_seen = threading.Event()
        first_run_ids: list[str] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            first_run_ids.append(request.match_id)
            if request.match_id == "qualifying-0002-match-1":
                failure_seen.set()
                return MatchExecutionResult(
                    infrastructure_failure=True,
                    competitive_outcome=None,
                    operational_telemetry={"diagnostic": "worker unavailable"},
                )
            if request.match_id == "qualifying-0001-match-1":
                self.assertTrue(failure_seen.wait(5))
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-infrastructure-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )

        with self.assertRaises(InfrastructureInterventionRequiredError) as caught:
            runner.run_continuously()

        self.assertEqual(caught.exception.match_id, "qualifying-0002-match-1")
        self.assertEqual(caught.exception.attempt_count, 3)
        records = load_competition_records(self.directory)
        self.assertEqual(
            [record.record["match_id"] for record in records],
            ["qualifying-0001-match-1"],
        )
        self.assertEqual(runner.control_status, "infrastructure_intervention")

        resumed_ids: list[str] = []
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: (
                resumed_ids.append(request.match_id)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened.resume()

        self.assertNotIn("qualifying-0001-match-1", resumed_ids)
        self.assertIn("qualifying-0002-match-1", resumed_ids)
        self.assertEqual(reopened.status, "complete")

    def test_standard_semifinals_overlap_but_final_waits_for_both(self) -> None:
        semifinal_one_active = threading.Event()
        semifinal_two_active = threading.Event()
        semifinal_overlap = threading.Event()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.match_id == "playoff-semifinal-1-match-1":
                semifinal_one_active.set()
                self.assertTrue(semifinal_two_active.wait(5))
                semifinal_overlap.set()
            elif request.match_id == "playoff-semifinal-2-match-1":
                semifinal_two_active.set()
                self.assertTrue(semifinal_one_active.wait(5))
            elif request.match_id.startswith("playoff-final-"):
                semifinal_records = [
                    record.record
                    for record in load_competition_records(self.directory)
                    if record.record.get("fixture_id")
                    in ("playoff-semifinal-1", "playoff-semifinal-2")
                    and record.record.get("type") == "match_terminal"
                ]
                self.assertEqual(len(semifinal_records), 4)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-playoff-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )

        runner.run_continuously()

        self.assertTrue(semifinal_overlap.is_set())
        self.assertEqual(runner.status, "complete")

    def test_parallel_interruption_reopens_without_out_of_order_commit(self) -> None:
        later_finished = threading.Event()

        def interrupt(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.match_id == "qualifying-0001-match-1":
                self.assertTrue(later_finished.wait(5))
                raise KeyboardInterrupt("simulated runner interruption")
            if request.match_id == "qualifying-0002-match-1":
                later_finished.set()
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="parallel-interruption-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=interrupt,
        )

        with self.assertRaises(KeyboardInterrupt):
            runner.run_continuously()

        self.assertEqual(load_competition_records(self.directory), [])
        resumed_ids: list[str] = []
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: (
                resumed_ids.append(request.match_id)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened.resume()

        self.assertIn("qualifying-0001-match-1", resumed_ids)
        self.assertIn("qualifying-0002-match-1", resumed_ids)
        self.assertEqual(reopened.status, "complete")
    def test_explicit_start_honors_pause_requested_during_active_match(self) -> None:
        entered_executor = threading.Event()
        release_executor = threading.Event()
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            self.assertTrue(load_control_state(self.directory)["match_active"])
            entered_executor.set()
            self.assertTrue(release_executor.wait(5))
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="durable-pause-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=execute,
        )
        result: list[tuple[StoredCompetitionRecord, ...]] = []
        worker = threading.Thread(target=lambda: result.append(runner.start()))
        worker.start()
        self.assertTrue(entered_executor.wait(5))

        runner.request_pause()
        self.assertTrue(load_control_state(self.directory)["pause_requested"])
        release_executor.set()
        worker.join(5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(runner.status, "paused")
        self.assertEqual(load_control_state(self.directory)["lifecycle"], "paused")
        self.assertFalse(load_control_state(self.directory)["pause_requested"])

    def test_paused_tournament_reopens_resumes_and_skips_committed_match(self) -> None:
        first_requests: list[MatchExecutionRequest] = []
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="reopen-control-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=lambda request: (
                first_requests.append(request)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
        )
        runner.request_pause()
        # A boundary pause is idempotent; start executes until a new request.
        original_executor = runner.match_executor
        runner.match_executor = lambda request: (
            runner.request_pause() or original_executor(request)
        )
        runner.start()
        committed_id = first_requests[0].match_id

        resumed_requests: list[MatchExecutionRequest] = []
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: (
                resumed_requests.append(request)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        reopened.resume()

        self.assertNotIn(
            committed_id, [request.match_id for request in resumed_requests]
        )
        self.assertEqual(reopened.status, "complete")

    def test_open_recovers_interrupted_running_control_to_safe_boundary(self) -> None:
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="interrupted-control-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=lambda request: self.fail(
                "Opening control recovery must not execute a Match"
            ),
        )
        update_control_state(
            self.directory,
            lambda control: {
                **control,
                "lifecycle": "running",
                "pause_requested": True,
            },
        )

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=runner.match_executor,
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        self.assertEqual(reopened.control_status, "paused")
        self.assertTrue(load_control_state(self.directory)["pause_requested"])
        self.assertEqual(load_competition_records(self.directory), [])

    def test_mode_switches_apply_only_at_match_boundaries(self) -> None:
        requests: list[MatchExecutionRequest] = []
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="mode-switch-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=lambda request: (
                requests.append(request)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
        )
        runner.switch_mode("step")
        runner.play_next_match()
        self.assertEqual(len(requests), 1)
        self.assertEqual(runner.status, "paused")
        self.assertEqual(
            load_manifest(self.directory).manifest["execution_mode"],
            "continuous",
        )

        runner.switch_mode("continuous")
        runner.start()
        self.assertEqual(runner.current_mode, "continuous")
        self.assertEqual(runner.status, "complete")
        with self.assertRaisesRegex(ValueError, "complete Tournament"):
            runner.switch_mode("step")
        self.assertEqual(runner.start(), ())
        self.assertEqual(runner.resume(), ())
        runner.request_pause()

    def test_mode_switch_is_rejected_while_match_is_active(self) -> None:
        both_entered = threading.Event()
        release_executor = threading.Event()
        requests: list[str] = []
        request_lock = threading.Lock()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            with request_lock:
                requests.append(request.match_id)
                if len(requests) == 2:
                    both_entered.set()
            self.assertTrue(release_executor.wait(5))
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="active-switch-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(
                execution_mode="continuous", continuous_parallelism=2
            ),
            match_executor=execute,
        )
        worker = threading.Thread(target=runner.start)
        worker.start()
        self.assertTrue(both_entered.wait(5))
        with self.assertRaisesRegex(ValueError, "Match boundary"):
            runner.switch_mode("step")
        runner.request_pause()
        release_executor.set()
        worker.join(5)
        self.assertFalse(worker.is_alive())
        committed_ids = [
            record.record["match_id"]
            for record in load_competition_records(self.directory)
            if record.record["type"] == "match_terminal"
        ]
        self.assertEqual(len(committed_ids), 1)

        runner.switch_mode("step")
        runner.play_next_match()
        after_switch_ids = [
            record.record["match_id"]
            for record in load_competition_records(self.directory)
            if record.record["type"] == "match_terminal"
        ]
        self.assertEqual(after_switch_ids.count(committed_ids[0]), 1)
        self.assertEqual(len(after_switch_ids), 2)

    def test_mode_timing_does_not_change_competition_records_or_tournament_state(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            return executor_result(request, winner_team_id=request.team_a_id)

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="canonical-controls-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=execute,
        )
        runner.start()
        continuous_records = load_competition_records(self.directory)

        with tempfile.TemporaryDirectory() as switched_name:
            switched_directory = Path(switched_name)
            switched = TournamentRunner.create(
                switched_directory,
                tournament_id="canonical-controls-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                config=TournamentConfig(execution_mode="continuous"),
                match_executor=execute,
            )
            switched.switch_mode("step")
            switched.play_next_match()
            switched.switch_mode("continuous")
            switched.start()
            switched_records = load_competition_records(switched_directory)

            self.assertEqual(
                [stored.record for stored in switched_records],
                [stored.record for stored in continuous_records],
            )
            self.assertEqual(
                fold_tournament_state(
                    load_manifest(switched_directory).manifest, switched_records
                ),
                fold_tournament_state(
                    load_manifest(self.directory).manifest, continuous_records
                ),
            )

    def test_start_requires_resume_after_infrastructure_intervention(self) -> None:
        def fail(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=True,
                competitive_outcome=None,
                operational_telemetry={"error": "host unavailable"},
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="intervention-control-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=fail,
        )
        with self.assertRaises(InfrastructureInterventionRequiredError):
            runner.start()
        self.assertEqual(runner.control_status, "infrastructure_intervention")
        with self.assertRaisesRegex(ValueError, "Resume is required"):
            runner.start()
        with self.assertRaisesRegex(ValueError, "Match boundary"):
            runner.switch_mode("step")
        runner.request_pause()
        self.assertEqual(runner.control_status, "infrastructure_intervention")

        runner.match_executor = lambda request: (
            runner.request_pause()
            or executor_result(request, winner_team_id=request.team_a_id)
        )
        resumed = runner.resume()
        self.assertEqual(len(resumed), 1)
        self.assertEqual(resumed[0].record["match_id"], "qualifying-0001-match-1")
        self.assertEqual(runner.control_status, "paused")

    def test_execution_operations_reject_the_other_sealed_mode(self) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(request, winner_team_id=request.team_a_id)

        continuous = TournamentRunner.create(
            self.directory,
            tournament_id="continuous-operation-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=execute,
        )
        with self.assertRaisesRegex(ValueError, "sealed in Step Mode"):
            continuous.play_next_match()

        with tempfile.TemporaryDirectory() as step_name:
            step = TournamentRunner.create(
                Path(step_name),
                tournament_id="step-operation-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                match_executor=execute,
            )
            with self.assertRaisesRegex(ValueError, "sealed in Continuous Mode"):
                step.run_continuously()

        self.assertEqual(requests, [])

    def test_continuous_mode_stops_while_awaiting_security_ruling(self) -> None:
        requests: list[MatchExecutionRequest] = []

        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=f"evidence:continuous/{request.match_id}",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="continuous-security-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=suspect,
        )

        committed = runner.run_continuously()

        self.assertEqual(len(requests), 1)
        self.assertEqual(committed, ())
        self.assertEqual(runner.status, "awaiting_security_ruling")
        self.assertEqual(len(load_competition_records(self.directory)), 1)
        with self.assertRaisesRegex(ValueError, "Security Violation"):
            runner.switch_mode("step")
        with self.assertRaises(SecurityRulingRequiredError):
            runner.start()
        with self.assertRaises(SecurityRulingRequiredError):
            runner.resume()
        runner.request_pause()

    def test_continuous_mode_does_not_rerun_a_match_committed_before_interruption(
        self,
    ) -> None:
        initial_requests: list[MatchExecutionRequest] = []

        def interrupt_next_match(
            request: MatchExecutionRequest,
        ) -> MatchExecutionResult:
            initial_requests.append(request)
            if len(initial_requests) == 2:
                raise KeyboardInterrupt("operator stopped between Matches")
            return executor_result(request, winner_team_id=request.team_a_id)

        created = TournamentRunner.create(
            self.directory,
            tournament_id="continuous-resume-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=interrupt_next_match,
        )
        with self.assertRaises(KeyboardInterrupt):
            created.run_continuously()
        committed_match_id = initial_requests[0].match_id

        resumed_requests: list[MatchExecutionRequest] = []

        def resume(request: MatchExecutionRequest) -> MatchExecutionResult:
            resumed_requests.append(request)
            return executor_result(request, winner_team_id=request.team_a_id)

        resumed = TournamentRunner.open(
            self.directory,
            match_executor=resume,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        resumed.run_continuously()

        self.assertNotIn(
            committed_match_id,
            [request.match_id for request in resumed_requests],
        )
        self.assertEqual(resumed.status, "complete")
        record_count = len(load_competition_records(self.directory))

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "A completed Tournament must not request another Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(reopened.run_continuously(), ())
        self.assertEqual(
            len(load_competition_records(self.directory)), record_count
        )

    def test_continuous_mode_stops_at_infrastructure_and_abort_boundaries(
        self,
    ) -> None:
        failed_requests: list[MatchExecutionRequest] = []

        def fail(request: MatchExecutionRequest) -> MatchExecutionResult:
            failed_requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=True,
                competitive_outcome=None,
                operational_telemetry={"error": "host unavailable"},
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="continuous-infrastructure-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            config=TournamentConfig(execution_mode="continuous"),
            match_executor=fail,
        )
        with self.assertRaises(InfrastructureInterventionRequiredError):
            runner.run_continuously()

        self.assertEqual(len(failed_requests), 3)
        self.assertEqual(
            {request.match_id for request in failed_requests},
            {"qualifying-0001-match-1"},
        )
        self.assertEqual(load_competition_records(self.directory), [])

        with tempfile.TemporaryDirectory() as aborted_name:
            aborted_requests: list[MatchExecutionRequest] = []
            aborted = TournamentRunner.create(
                Path(aborted_name),
                tournament_id="continuous-abort-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                config=TournamentConfig(execution_mode="continuous"),
                match_executor=lambda request: aborted_requests.append(request),
            )
            aborted.abort(organizer_id="organizer-continuous")

            self.assertEqual(aborted.run_continuously(), ())
            self.assertEqual(aborted_requests, [])
            self.assertEqual(aborted.status, "aborted")
            with self.assertRaisesRegex(ValueError, "complete Tournament"):
                aborted.switch_mode("step")
            self.assertEqual(aborted.start(), ())
            self.assertEqual(aborted.resume(), ())
            aborted.request_pause()


class TournamentStepModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_operator_can_abort_before_or_after_committed_matches(self) -> None:
        requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(request, winner_team_id=request.team_a_id)

        with tempfile.TemporaryDirectory() as fresh_name:
            fresh_directory = Path(fresh_name)
            fresh = TournamentRunner.create(
                fresh_directory,
                tournament_id="fresh-operator-abort-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                match_executor=execute,
            )
            first_record = fresh.abort(organizer_id="organizer-before-match")
            self.assertEqual(first_record.sequence, 1)
            self.assertEqual(requests, [])
            self.assertEqual(fresh.status, "aborted")

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="operator-abort-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=execute,
        )
        committed = runner.play_next_match()
        prior_bytes = (self.directory / "records" / "00000001.json").read_bytes()

        aborted = runner.abort(
            organizer_id="organizer-9",
            note="Venue evacuation",
        )

        self.assertEqual(aborted.sequence, 2)
        self.assertEqual(aborted.record["type"], "tournament_aborted")
        self.assertEqual(aborted.record["phase"], "qualifying")
        self.assertEqual(aborted.record["organizer_id"], "organizer-9")
        self.assertEqual(aborted.record["reason_code"], "operator_requested")
        self.assertEqual(aborted.record["note"], "Venue evacuation")
        self.assertEqual(
            (self.directory / "records" / "00000001.json").read_bytes(),
            prior_bytes,
        )
        self.assertEqual(load_competition_records(self.directory)[0], committed)
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "aborted")
        self.assertEqual(projection["completion_reason"], "operator_requested")
        self.assertIsNone(projection["champion"])
        self.assertEqual(
            projection["operator_abort"],
            {
                "organizer_id": "organizer-9",
                "reason_code": "operator_requested",
                "note": "Venue evacuation",
            },
        )
        self.assertIsNone(runner.play_next_match())
        self.assertEqual(len(requests), 1)
        with self.assertRaisesRegex(ValueError, "already complete"):
            runner.abort(organizer_id="organizer-9")

    def test_abort_rejects_pending_security_ruling_and_completed_tournament(self) -> None:
        runner = TournamentRunner.create(
            self.directory,
            tournament_id="abort-transition-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:abort-transition/incident-1",
            ),
        )
        runner.play_next_match()

        with self.assertRaisesRegex(ValueError, "Security Violation"):
            runner.abort(organizer_id="organizer-1")
        self.assertEqual(len(load_competition_records(self.directory)), 1)

        with tempfile.TemporaryDirectory() as completed_name:
            completed_directory = Path(completed_name)
            completed = TournamentRunner.create(
                completed_directory,
                tournament_id="completed-abort-cup",
                tournament_seed=123456789,
                roster=four_team_roster(),
                match_executor=lambda request: executor_result(
                    request,
                    winner_team_id=min(request.team_a_id, request.team_b_id),
                ),
            )
            while completed.play_next_match() is not None:
                pass
            champion = load_scoreboard_projection(completed_directory)["champion"]
            record_count = len(load_competition_records(completed_directory))

            with self.assertRaisesRegex(ValueError, "already complete"):
                completed.abort(organizer_id="organizer-2")

            self.assertEqual(
                load_scoreboard_projection(completed_directory)["champion"], champion
            )
            self.assertEqual(
                len(load_competition_records(completed_directory)), record_count
            )

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

    def test_operator_abort_in_playoffs_preserves_qualifying_results(self) -> None:
        runner = self._runner_at_playoffs(
            lambda request: self.fail(
                "Aborting at a playoff boundary must not execute a Match"
            )
        )
        records_before_abort = load_competition_records(self.directory)

        aborted = runner.abort(organizer_id="organizer-playoffs")

        records_after_abort = load_competition_records(self.directory)
        self.assertEqual(aborted.record["phase"], "playoff")
        self.assertEqual(records_after_abort[:-1], records_before_abort)
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["phase"], "playoff")
        self.assertEqual(projection["status"], "aborted")
        self.assertIsNone(projection["champion"])
        self.assertIsNone(runner.play_next_match())

    def _complete_with_eligible_team_count(
        self, eligible_team_count: int
    ) -> tuple[
        TournamentRunner,
        list[MatchExecutionRequest],
        dict[str, object],
    ]:
        requests: list[MatchExecutionRequest] = []

        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=(
                    f"evidence:reduced-{eligible_team_count}/{request.match_id}"
                ),
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id=f"reduced-{eligible_team_count}-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )
        single_disqualifications = (
            2 if eligible_team_count == 0 else 4 - eligible_team_count
        )
        for ordinal in range(single_disqualifications):
            incident = runner.play_next_match()
            self.assertEqual(incident.record["type"], "security_violation_suspected")
            runner.confirm_security_violation(
                organizer_id=f"organizer-{ordinal + 1}"
            )
        if eligible_team_count == 0:
            def suspect_both(
                request: MatchExecutionRequest,
            ) -> MatchExecutionResult:
                requests.append(request)
                return MatchExecutionResult(
                    infrastructure_failure=False,
                    competitive_outcome=None,
                    operational_telemetry={
                        "raw_security_evidence": "variable-double-incident"
                    },
                    evidence_link=f"evidence:reduced-0/{request.match_id}",
                    suspected_security_violation_team_ids=(
                        request.team_a_id,
                        request.team_b_id,
                    ),
                )

            runner.match_executor = suspect_both
            incident = runner.play_next_match()
            self.assertEqual(
                incident.record["suspected_team_ids"],
                incident.record["team_ids"],
            )
            for team_id in incident.record["suspected_team_ids"]:
                runner.confirm_security_violation(
                    organizer_id="organizer-3", team_id=team_id
                )

        def finish(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner.match_executor = finish
        while runner.play_next_match() is not None:
            pass
        projection = load_scoreboard_projection(self.directory)
        assert projection is not None
        return runner, requests, projection

    def _runner_at_reduced_playoffs(
        self,
        eligible_team_count: int,
        playoff_executor,
    ) -> TournamentRunner:
        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=f"evidence:recovery-{eligible_team_count}/{request.match_id}",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id=f"recovery-{eligible_team_count}-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )
        for ordinal in range(4 - eligible_team_count):
            runner.play_next_match()
            runner.confirm_security_violation(
                organizer_id=f"organizer-{ordinal + 1}"
            )

        runner.match_executor = lambda request: executor_result(
            request,
            winner_team_id=min(request.team_a_id, request.team_b_id),
        )
        while load_scoreboard_projection(self.directory)["phase"] == "qualifying":
            runner.play_next_match()
        runner.match_executor = playoff_executor
        return runner

    def test_reduced_playoffs_execute_only_canonical_matches_and_reopen(
        self,
    ) -> None:
        for eligible_team_count in (3, 2, 1, 0):
            with self.subTest(eligible_team_count=eligible_team_count):
                with tempfile.TemporaryDirectory() as directory_name:
                    self.directory = Path(directory_name)
                    runner, requests, projection = (
                        self._complete_with_eligible_team_count(
                            eligible_team_count
                        )
                    )
                    playoff_requests = [
                        request
                        for request in requests
                        if request.fixture_id.startswith("playoff-")
                    ]
                    fixtures = projection["bracket"]["fixtures"]
                    seeds = projection["bracket"]["seeds"]
                    for fixture in fixtures:
                        self.assertEqual(
                            fixture["fixture_seed"],
                            str(
                                derive_fixture_seed(
                                    123456789, fixture["fixture_id"]
                                )
                            ),
                        )
                    for request in playoff_requests:
                        fixture_seed = derive_fixture_seed(
                            123456789, request.fixture_id
                        )
                        match_ordinal = int(request.match_id.rsplit("-", 1)[1])
                        self.assertEqual(
                            request.match_seed,
                            derive_match_seed(fixture_seed, match_ordinal),
                        )

                    if eligible_team_count == 3:
                        self.assertEqual(
                            [fixture["stage"] for fixture in fixtures],
                            ["semifinal", "final"],
                        )
                        self.assertEqual(
                            fixtures[0]["team_ids"],
                            [seeds[1]["team_id"], seeds[2]["team_id"]],
                        )
                        self.assertEqual(
                            fixtures[1]["team_ids"][0], seeds[0]["team_id"]
                        )
                        self.assertEqual(len(playoff_requests), 4)
                    elif eligible_team_count == 2:
                        self.assertEqual(
                            [
                                (fixture["stage"], fixture["team_ids"])
                                for fixture in fixtures
                            ],
                            [("final", [seeds[0]["team_id"], seeds[1]["team_id"]])],
                        )
                        self.assertEqual(len(playoff_requests), 2)
                    elif eligible_team_count == 1:
                        self.assertEqual(fixtures, [])
                        self.assertEqual(playoff_requests, [])
                        self.assertFalse(projection["bracket"]["locked"])

                    else:
                        self.assertEqual(seeds, [])
                        self.assertEqual(fixtures, [])
                        self.assertEqual(playoff_requests, [])
                        self.assertFalse(projection["bracket"]["locked"])
                        self.assertIsNone(projection["champion"])
                        self.assertEqual(
                            projection["completion_reason"],
                            "no_eligible_teams",
                        )
                        self.assertTrue(
                            all(
                                fixture["status"] in {"complete", "skipped"}
                                for fixture in projection["fixtures"]
                            )
                        )

                    self.assertEqual(projection["status"], "complete")
                    if eligible_team_count:
                        self.assertIsNotNone(projection["champion"])
                    records_before_reopen = load_competition_records(self.directory)
                    projection_before_reopen = projection
                    if eligible_team_count == 3:
                        malformed_records = list(records_before_reopen)
                        bracket_index = next(
                            index
                            for index, stored in enumerate(malformed_records)
                            if stored.record["type"] == "playoff_bracket_created"
                        )
                        malformed_bracket = thaw_json(
                            malformed_records[bracket_index].record
                        )
                        malformed_bracket["fixtures"][0]["team_ids"] = [
                            seeds[0]["team_id"],
                            seeds[2]["team_id"],
                        ]
                        malformed_records[bracket_index] = StoredCompetitionRecord(
                            bracket_index + 1,
                            malformed_bracket,
                            "malformed-reduced-bracket",
                        )
                        with self.assertRaisesRegex(
                            TournamentStateError, "does not match"
                        ):
                            fold_tournament_state(
                                load_manifest(self.directory).manifest,
                                malformed_records,
                            )
                    reopened = TournamentRunner.open(
                        self.directory,
                        match_executor=lambda request: self.fail(
                            "A completed reduced Playoff Phase must execute no Match"
                        ),
                        artifact_digest_verifier=lambda team_id, digest: True,
                    )
                    self.assertIsNone(reopened.play_next_match())
                    self.assertEqual(
                        load_competition_records(self.directory), records_before_reopen
                    )
                    self.assertEqual(
                        load_scoreboard_projection(self.directory),
                        projection_before_reopen,
                    )

    def test_open_recovers_sole_champion_after_bracket_commit(self) -> None:
        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=f"evidence:sole-recovery/{request.match_id}",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="sole-recovery-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect,
        )
        for ordinal in range(2):
            runner.play_next_match()
            runner.confirm_security_violation(
                organizer_id=f"organizer-{ordinal + 1}"
            )
        runner.play_next_match()

        def interrupt_after_bracket(
            directory: Path, record: dict[str, object]
        ) -> object:
            if (
                record.get("type") == "tournament_champion_declared"
                and record.get("reason_code") == "sole_eligible_team"
            ):
                raise RuntimeError("interrupted after reduced bracket commit")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=interrupt_after_bracket,
        ):
            with self.assertRaisesRegex(RuntimeError, "after reduced bracket"):
                runner.confirm_security_violation(organizer_id="organizer-3")

        interrupted = load_competition_records(self.directory)
        self.assertEqual(interrupted[-1].record["type"], "playoff_bracket_created")
        self.assertEqual(interrupted[-1].record["fixtures"], [])
        self.assertFalse(
            any(
                record.record["type"] == "playoff_bracket_locked"
                for record in interrupted
            )
        )

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Sole-champion recovery must not execute a playoff Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        recovered = load_competition_records(self.directory)
        self.assertEqual(
            recovered[-1].record["reason_code"], "sole_eligible_team"
        )
        self.assertEqual(reopened.status, "complete")
        self.assertFalse(
            load_scoreboard_projection(self.directory)["bracket"]["locked"]
        )

    def test_open_recovers_three_team_final_after_semifinal_commit(self) -> None:
        playoff_requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            playoff_requests.append(request)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = self._runner_at_reduced_playoffs(3, execute)
        runner.play_next_match()
        real_write_projection = write_scoreboard_projection

        def interrupt_after_semifinal(
            directory: Path, projection: dict[str, object]
        ) -> None:
            bracket = projection.get("bracket", {})
            fixtures = bracket.get("fixtures", []) if isinstance(bracket, dict) else []
            if fixtures and fixtures[0].get("status") == "complete":
                raise RuntimeError("interrupted after reduced semifinal commit")
            real_write_projection(directory, projection)

        with patch(
            "rps_runner.tournament.runner.write_scoreboard_projection",
            side_effect=interrupt_after_semifinal,
        ):
            with self.assertRaisesRegex(RuntimeError, "semifinal commit"):
                runner.play_next_match()

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=execute,
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        state = fold_tournament_state(
            load_manifest(self.directory).manifest,
            load_competition_records(self.directory),
        )
        self.assertEqual(state.next_playoff_match.fixture_id, "playoff-final")
        self.assertEqual(len(playoff_requests), 2)
        reopened.play_next_match()
        self.assertEqual(playoff_requests[-1].fixture_id, "playoff-final")

    def test_open_recovers_direct_final_champion_after_terminal_commit(self) -> None:
        playoff_requests: list[MatchExecutionRequest] = []

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            playoff_requests.append(request)
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = self._runner_at_reduced_playoffs(2, execute)
        runner.play_next_match()

        def interrupt_before_champion(
            directory: Path, record: dict[str, object]
        ) -> object:
            if record.get("type") == "tournament_champion_declared":
                raise RuntimeError("interrupted before direct-final champion")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=interrupt_before_champion,
        ):
            with self.assertRaisesRegex(RuntimeError, "direct-final champion"):
                runner.play_next_match()

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not rerun the committed direct final"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(len(playoff_requests), 2)
        self.assertEqual(reopened.status, "complete")
        self.assertEqual(
            load_competition_records(self.directory)[-1].record["type"],
            "tournament_champion_declared",
        )

    def test_open_recovers_zero_eligible_terminal_after_bracket_commit(self) -> None:
        def suspect_one(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=f"evidence:zero-recovery/{request.match_id}",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="zero-recovery-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect_one,
        )
        for ordinal in range(2):
            runner.play_next_match()
            runner.confirm_security_violation(
                organizer_id=f"organizer-{ordinal + 1}"
            )

        def suspect_both(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "double"},
                evidence_link=f"evidence:zero-recovery/{request.match_id}",
                suspected_security_violation_team_ids=(
                    request.team_a_id,
                    request.team_b_id,
                ),
            )

        runner.match_executor = suspect_both
        incident = runner.play_next_match()
        first_team_id, second_team_id = incident.record["suspected_team_ids"]
        runner.confirm_security_violation(
            organizer_id="organizer-3", team_id=first_team_id
        )

        def interrupt_after_bracket(
            directory: Path, record: dict[str, object]
        ) -> object:
            if record.get("type") == "tournament_ended_without_champion":
                raise RuntimeError("interrupted before zero-eligible terminal")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=interrupt_after_bracket,
        ):
            with self.assertRaisesRegex(RuntimeError, "zero-eligible terminal"):
                runner.confirm_security_violation(
                    organizer_id="organizer-3", team_id=second_team_id
                )

        interrupted = load_competition_records(self.directory)
        self.assertEqual(interrupted[-1].record["type"], "playoff_bracket_created")
        self.assertFalse(
            any(
                record.record["type"] == "playoff_bracket_locked"
                for record in interrupted
            )
        )

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Zero-eligible recovery must not execute a playoff Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        recovered = load_competition_records(self.directory)
        self.assertEqual(
            recovered[-1].record["type"],
            "tournament_ended_without_champion",
        )
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(reopened.status, "complete")
        self.assertEqual(projection["completion_reason"], "no_eligible_teams")
        self.assertIsNone(projection["champion"])

    def test_multi_team_incident_is_ruled_per_bot_artifact(self) -> None:
        def suspect_one(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "single"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link=f"evidence:mixed-ruling/{request.match_id}",
            )

        runner = TournamentRunner.create(
            self.directory,
            tournament_id="mixed-ruling-cup",
            tournament_seed=123456789,
            roster=four_team_roster(),
            match_executor=suspect_one,
        )
        for ordinal in range(2):
            runner.play_next_match()
            runner.confirm_security_violation(
                organizer_id=f"organizer-{ordinal + 1}"
            )

        runner.match_executor = lambda request: MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=None,
            operational_telemetry={"raw_security_evidence": "double"},
            evidence_link=f"evidence:mixed-ruling/{request.match_id}",
            suspected_security_violation_team_ids=(
                request.team_b_id,
                request.team_a_id,
            ),
        )
        incident = runner.play_next_match()
        confirmed_team_id, cleared_team_id = incident.record[
            "suspected_team_ids"
        ]

        runner.confirm_security_violation(
            organizer_id="organizer-3", team_id=confirmed_team_id
        )
        runner.reject_security_violation(
            organizer_id="organizer-4", team_id=cleared_team_id
        )

        state = fold_tournament_state(
            load_manifest(self.directory).manifest,
            load_competition_records(self.directory),
        )
        self.assertIn(confirmed_team_id, state.disqualified_team_ids)
        self.assertNotIn(cleared_team_id, state.disqualified_team_ids)
        self.assertEqual(state.champion_team_id, cleared_team_id)
        self.assertEqual(
            incident.record["suspected_team_ids"], incident.record["team_ids"]
        )

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
        with self.assertRaisesRegex(
            TournamentStateError, "rules-driven Tournament completion"
        ):
            fold_tournament_state(
                load_manifest(self.directory).manifest,
                interrupted_records
                + [
                    StoredCompetitionRecord(
                        len(interrupted_records) + 1,
                        build_operator_abort_record(
                            phase=Phase.PLAYOFF,
                            organizer_id="organizer-too-late",
                        ),
                        "invalid-abort",
                    )
                ],
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

    def test_playoff_suspicion_pauses_and_survives_projection_rebuild(self) -> None:
        runner = self._runner_at_playoffs(
            lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:playoff/incident-1",
            )
        )

        incident = runner.play_next_match()

        records = load_competition_records(self.directory)
        self.assertEqual(incident.record["phase"], "playoff")
        self.assertEqual(
            incident.record["fixture_id"], "playoff-semifinal-1"
        )
        self.assertEqual(records[-1], incident)
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(
            state.pending_security_ruling.match_id, incident.record["match_id"]
        )
        self.assertIsNone(state.next_playoff_match)
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "awaiting_security_ruling")
        self.assertNotIn("evidence", str(projection))

        write_scoreboard_projection(self.directory, {"status": "stale"})
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not execute a Match while a ruling is pending"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(reopened.status, "awaiting_security_ruling")
        with self.assertRaises(SecurityRulingRequiredError):
            reopened.play_next_match()

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

    def test_rejected_playoff_attribution_retries_semifinal_and_final(self) -> None:
        requests: list[MatchExecutionRequest] = []
        suspected_fixtures: set[str] = set()

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            if request.fixture_id not in suspected_fixtures:
                suspected_fixtures.add(request.fixture_id)
                return MatchExecutionResult(
                    infrastructure_failure=False,
                    competitive_outcome=None,
                    operational_telemetry={"raw_security_evidence": "variable"},
                    suspected_security_violation_team_id=request.team_a_id,
                    evidence_link=f"evidence:playoff-retry/{request.match_id}",
                )
            return executor_result(
                request,
                winner_team_id=min(request.team_a_id, request.team_b_id),
            )

        runner = self._runner_at_playoffs(execute)
        for fixture_id in ("playoff-semifinal-1", "playoff-semifinal-2"):
            incident = runner.play_next_match()
            runner.reject_security_violation(organizer_id="organizer-retry")
            terminal = runner.play_next_match()
            self.assertEqual(incident.record["fixture_id"], fixture_id)
            self.assertEqual(terminal.record["match_id"], incident.record["match_id"])
            while True:
                state = fold_tournament_state(
                    load_manifest(self.directory).manifest,
                    load_competition_records(self.directory),
                )
                if state.next_playoff_match.fixture_id != fixture_id:
                    break
                runner.play_next_match()

        incident = runner.play_next_match()
        runner.reject_security_violation(organizer_id="organizer-retry")
        terminal = runner.play_next_match()
        self.assertEqual(terminal.record["match_id"], incident.record["match_id"])

        retried = [
            request
            for request in requests
            if request.match_id in {
                "playoff-semifinal-1-match-1",
                "playoff-semifinal-2-match-1",
                "playoff-final-match-1",
            }
        ]
        self.assertEqual(
            [(request.match_id, request.attempt_number) for request in retried],
            [
                ("playoff-semifinal-1-match-1", 1),
                ("playoff-semifinal-1-match-1", 2),
                ("playoff-semifinal-2-match-1", 1),
                ("playoff-semifinal-2-match-1", 2),
                ("playoff-final-match-1", 1),
                ("playoff-final-match-1", 2),
            ],
        )

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

    def test_confirmed_playoff_semifinal_violation_awards_and_advances_opponent(
        self,
    ) -> None:
        attempts: list[MatchExecutionRequest] = []

        def suspect(request: MatchExecutionRequest) -> MatchExecutionResult:
            attempts.append(request)
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:playoff-confirmed/semifinal",
            )

        runner = self._runner_at_playoffs(suspect)
        incident = runner.play_next_match()
        disqualified = incident.record["suspected_team_id"]
        opponent = next(
            team_id for team_id in incident.record["team_ids"]
            if team_id != disqualified
        )
        runner.confirm_security_violation(organizer_id="organizer-playoff")

        records = load_competition_records(self.directory)
        self.assertEqual(records[-1].record, {
            "type": "administrative_series_win",
            "phase": "playoff",
            "fixture_id": "playoff-semifinal-1",
            "team_ids": incident.record["team_ids"],
            "winner_team_id": opponent,
            "disqualified_team_id": disqualified,
            "reason_code": "opponent_disqualified",
            "ruling_match_id": incident.record["match_id"],
        })
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(state.playoff_series[0].winner, opponent)
        self.assertEqual(state.next_playoff_match.fixture_id, "playoff-semifinal-2")
        self.assertEqual(len(attempts), 1)
        projection = load_scoreboard_projection(self.directory)
        first = projection["bracket"]["fixtures"][0]
        self.assertEqual(first["status"], "complete")
        self.assertEqual(
            first["administrative_series_win"]["winner_team_id"], opponent
        )

    def test_confirmed_playoff_final_violation_declares_remaining_finalist(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.fixture_id.startswith("playoff-semifinal"):
                return executor_result(
                    request,
                    winner_team_id=min(request.team_a_id, request.team_b_id),
                )
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:playoff-confirmed/final",
            )

        runner = self._runner_at_playoffs(execute)
        while True:
            state = fold_tournament_state(
                load_manifest(self.directory).manifest,
                load_competition_records(self.directory),
            )
            if state.next_playoff_match.fixture_id == "playoff-final":
                break
            runner.play_next_match()
        incident = runner.play_next_match()
        disqualified = incident.record["suspected_team_id"]
        champion = next(
            team_id for team_id in incident.record["team_ids"]
            if team_id != disqualified
        )
        runner.confirm_security_violation(organizer_id="organizer-final")

        records = load_competition_records(self.directory)
        self.assertEqual(
            [record.record["type"] for record in records[-2:]],
            ["administrative_series_win", "tournament_champion_declared"],
        )
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(state.champion_team_id, champion)
        self.assertEqual(state.playoff_series[-1].winner, champion)
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "complete")
        self.assertEqual(projection["champion"], champion)
        self.assertEqual(
            projection["bracket"]["fixtures"][-1]["administrative_series_win"],
            {"winner_team_id": champion, "reason_code": "opponent_disqualified"},
        )

    def test_confirming_both_finalists_never_declares_disqualified_champion(
        self,
    ) -> None:
        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            if request.fixture_id.startswith("playoff-semifinal"):
                return executor_result(
                    request,
                    winner_team_id=min(request.team_a_id, request.team_b_id),
                )
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={},
                suspected_security_violation_team_ids=(
                    request.team_a_id,
                    request.team_b_id,
                ),
                evidence_link="evidence:playoff-confirmed/both-finalists",
            )

        runner = self._runner_at_playoffs(execute)
        while True:
            state = fold_tournament_state(
                load_manifest(self.directory).manifest,
                load_competition_records(self.directory),
            )
            if state.next_playoff_match.fixture_id == "playoff-final":
                break
            runner.play_next_match()
        incident = runner.play_next_match()
        first, second = incident.record["suspected_team_ids"]
        runner.confirm_security_violation(
            organizer_id="organizer-finalists", team_id=first
        )
        runner.confirm_security_violation(
            organizer_id="organizer-finalists", team_id=second
        )

        records = load_competition_records(self.directory)
        self.assertEqual(
            records[-1].record,
            {
                "type": "tournament_ended_without_champion",
                "phase": "playoff",
                "reason_code": "all_finalists_disqualified",
            },
        )
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertTrue(state.ended_without_champion)
        self.assertIsNone(state.champion_team_id)
        self.assertEqual(set(state.disqualified_team_ids), {first, second})
        projection = load_scoreboard_projection(self.directory)
        self.assertEqual(projection["status"], "complete")
        self.assertIsNone(projection["champion"])
        self.assertEqual(
            projection["completion_reason"], "all_finalists_disqualified"
        )

    def test_two_team_playoff_incident_resolves_sequentially_without_reseeding(
        self,
    ) -> None:
        def suspect_both(request: MatchExecutionRequest) -> MatchExecutionResult:
            return MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_ids=(
                    request.team_a_id,
                    request.team_b_id,
                ),
                evidence_link="evidence:playoff-confirmed/both",
            )

        runner = self._runner_at_playoffs(suspect_both)
        incident = runner.play_next_match()
        first, second = incident.record["suspected_team_ids"]
        runner.confirm_security_violation(
            organizer_id="organizer-both", team_id=first
        )
        interim = fold_tournament_state(
            load_manifest(self.directory).manifest,
            load_competition_records(self.directory),
        )
        self.assertEqual(interim.pending_security_ruling.suspected_team_ids, (second,))
        runner.confirm_security_violation(
            organizer_id="organizer-both", team_id=second
        )

        records = load_competition_records(self.directory)
        replacement = records[-1].record
        self.assertEqual(replacement["type"], "playoff_bracket_position_replaced")
        self.assertEqual(replacement["disqualified_team_id"], second)
        self.assertIsNone(replacement["reinstated_team_id"])
        state = fold_tournament_state(load_manifest(self.directory).manifest, records)
        self.assertEqual(set(state.disqualified_team_ids), {first, second})
        self.assertEqual(state.next_playoff_match.fixture_id, "playoff-semifinal-2")

        runner.match_executor = lambda request: executor_result(
            request,
            winner_team_id=min(request.team_a_id, request.team_b_id),
        )
        runner.play_next_match()
        runner.play_next_match()
        completed = fold_tournament_state(
            load_manifest(self.directory).manifest,
            load_competition_records(self.directory),
        )
        self.assertIsNotNone(completed.champion_team_id)
        self.assertNotIn(completed.champion_team_id, {first, second})
        projection = load_scoreboard_projection(self.directory)
        final = projection["bracket"]["fixtures"][-1]
        self.assertEqual(final["team_ids"].count(None), 1)
        self.assertEqual(final["status"], "complete")
        self.assertEqual(
            final["bracket_position_replacement"]["reinstated_team_id"], None
        )
        (self.directory / "scoreboard.json").unlink()
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Projection rebuild must not execute a Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(load_scoreboard_projection(self.directory), projection)

    def test_open_finishes_interrupted_playoff_disqualification_transitions(
        self,
    ) -> None:
        runner = self._runner_at_playoffs(
            lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={"raw_security_evidence": "variable"},
                suspected_security_violation_team_ids=(
                    request.team_a_id,
                    request.team_b_id,
                ),
                evidence_link="evidence:playoff-recovery/both",
            )
        )
        incident = runner.play_next_match()
        first, second = incident.record["suspected_team_ids"]

        def interrupt_admin(directory: Path, record: dict[str, object]) -> object:
            if record.get("type") == "administrative_series_win":
                raise RuntimeError(
                    "interrupted before playoff Administrative Series Win"
                )
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=interrupt_admin,
        ):
            with self.assertRaisesRegex(RuntimeError, "Administrative Series Win"):
                runner.confirm_security_violation(
                    organizer_id="organizer-recovery", team_id=first
                )
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not execute a Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        self.assertEqual(
            load_competition_records(self.directory)[-1].record["type"],
            "administrative_series_win",
        )

        def interrupt_replacement(directory: Path, record: dict[str, object]) -> object:
            if record.get("type") == "playoff_bracket_position_replaced":
                raise RuntimeError("interrupted before bracket replacement")
            return append_competition_record(directory, record)

        with patch(
            "rps_runner.tournament.runner.append_competition_record",
            side_effect=interrupt_replacement,
        ):
            with self.assertRaisesRegex(RuntimeError, "bracket replacement"):
                runner.confirm_security_violation(
                    organizer_id="organizer-recovery", team_id=second
                )
        TournamentRunner.open(
            self.directory,
            match_executor=lambda request: self.fail(
                "Recovery must not execute a Match"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )
        recovered = load_competition_records(self.directory)
        self.assertEqual(
            recovered[-1].record["type"],
            "playoff_bracket_position_replaced",
        )
        self.assertEqual(
            fold_tournament_state(load_manifest(self.directory).manifest, recovered)
            .next_playoff_match.fixture_id,
            "playoff-semifinal-2",
        )

    def test_fold_rejects_noncanonical_playoff_security_histories(self) -> None:
        runner = self._runner_at_playoffs(
            lambda request: MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={},
                suspected_security_violation_team_id=request.team_a_id,
                evidence_link="evidence:playoff-invalid/incident",
            )
        )
        runner.play_next_match()
        manifest_value = load_manifest(self.directory).manifest
        records = load_competition_records(self.directory)
        prefix, incident = records[:-1], records[-1]
        mutations = {
            "phase": lambda record: record.update(phase="qualifying"),
            "Fixture": lambda record: record.update(fixture_id="playoff-semifinal-2"),
            "Match": lambda record: record.update(
                match_id="playoff-semifinal-1-match-2"
            ),
            "Team": lambda record: record.update(suspected_team_id="not-a-competitor"),
        }
        for expected, mutate in mutations.items():
            with self.subTest(expected=expected):
                value = thaw_json(incident.record)
                mutate(value)
                invalid = StoredCompetitionRecord(incident.sequence, value, "invalid")
                with self.assertRaisesRegex(TournamentStateError, "canonical Match"):
                    fold_tournament_state(manifest_value, prefix + [invalid])

        duplicate = StoredCompetitionRecord(
            incident.sequence + 1, thaw_json(incident.record), "duplicate"
        )
        with self.assertRaisesRegex(TournamentStateError, "already awaiting"):
            fold_tournament_state(manifest_value, records + [duplicate])

        runner.confirm_security_violation(organizer_id="organizer-invalid")
        confirmed = load_competition_records(self.directory)
        administrative = confirmed[-1]
        malformed = thaw_json(administrative.record)
        malformed["winner_team_id"] = malformed["disqualified_team_id"]
        with self.assertRaisesRegex(TournamentStateError, "canonical transition"):
            fold_tournament_state(
                manifest_value,
                confirmed[:-1]
                + [
                    StoredCompetitionRecord(
                        administrative.sequence, malformed, "invalid"
                    )
                ],
            )

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

    def test_open_rebuilds_aborted_projection_without_executing_match(self) -> None:
        self.runner.abort(organizer_id="organizer-recovery", note=None)
        expected = load_scoreboard_projection(self.directory)
        scoreboard_path = self.directory / "scoreboard.json"

        for content in (None, b"not-json"):
            if content is None:
                scoreboard_path.unlink()
            else:
                scoreboard_path.write_bytes(content)
            resumed = TournamentRunner.open(
                self.directory,
                match_executor=lambda request: self.fail(
                    "Aborted Tournament must not execute a Match"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

            self.assertEqual(load_scoreboard_projection(self.directory), expected)
            self.assertEqual(resumed.status, "aborted")
            self.assertIsNone(resumed.play_next_match())

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

    def test_open_rejects_invalid_sealed_continuous_parallelism(self) -> None:
        manifest = load_manifest(self.directory).manifest
        manifest_path = self.directory / "manifest.json"
        manifest_path.unlink()
        seal_manifest(self.directory, manifest | {"continuous_parallelism": 0})

        with self.assertRaises(TournamentCompatibilityError) as caught:
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

        self.assertEqual(caught.exception.field, "continuous_parallelism")
        self.assertEqual(caught.exception.actual, 0)

    def test_open_treats_legacy_missing_parallelism_as_limit_one(self) -> None:
        manifest = thaw_json(load_manifest(self.directory).manifest)
        del manifest["continuous_parallelism"]
        manifest_path = self.directory / "manifest.json"
        manifest_path.unlink()
        seal_manifest(self.directory, manifest)

        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: executor_result(
                request, winner_team_id="beta"
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        reopened.play_next_match()
        self.assertEqual(len(load_competition_records(self.directory)), 1)

    def test_open_rejects_pre_abort_record_schema(self) -> None:
        manifest = load_manifest(self.directory).manifest
        manifest_path = self.directory / "manifest.json"
        manifest_path.unlink()
        seal_manifest(self.directory, manifest | {"record_schema_version": 3})

        with self.assertRaises(TournamentCompatibilityError) as caught:
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: executor_result(
                    request, winner_team_id="beta"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

        self.assertEqual(caught.exception.field, "record_schema_version")
        self.assertEqual(caught.exception.expected, 4)
        self.assertEqual(caught.exception.actual, 3)

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

    def test_restore_reopens_and_resumes_without_rerunning_committed_match(
        self,
    ) -> None:
        committed = self.runner.play_next_match()
        self.assertIsNotNone(committed)
        committed_match_id = str(committed.record["match_id"])
        expected_projection = load_scoreboard_projection(self.directory)
        record_path = self.directory / "records" / "00000001.json"
        backup_path = self.directory / "externally-supplied-record.json"
        backup_bytes = record_path.read_bytes()
        backup_path.write_bytes(backup_bytes)
        record_path.chmod(0o644)
        record_path.write_bytes(
            backup_bytes.replace(b'"winner_team_id"', b'"winner-team-id"')
        )
        requests: list[MatchExecutionRequest] = []

        with self.assertRaises(IntegrityError):
            TournamentRunner.open(
                self.directory,
                match_executor=lambda request: self.fail(
                    "A corrupt Competition Record must not execute a Match"
                ),
                artifact_digest_verifier=lambda team_id, digest: True,
            )

        restored = TournamentRunner.restore_competition_record_at(
            self.directory, backup_path
        )
        reopened = TournamentRunner.open(
            self.directory,
            match_executor=lambda request: (
                requests.append(request)
                or executor_result(request, winner_team_id=request.team_a_id)
            ),
            artifact_digest_verifier=lambda team_id, digest: True,
        )

        self.assertEqual(restored, committed)
        self.assertEqual(
            load_scoreboard_projection(self.directory), expected_projection
        )
        reopened.play_next_match()
        self.assertNotIn(
            committed_match_id, [request.match_id for request in requests]
        )
        self.assertEqual(backup_path.read_bytes(), backup_bytes)

    def test_restore_competes_for_the_exclusive_tournament_run_lock(self) -> None:
        committed = self.runner.play_next_match()
        record_path = self.directory / "records" / "00000001.json"
        backup_path = self.directory / "externally-supplied-record.json"
        backup_path.write_bytes(record_path.read_bytes())
        record_path.unlink()

        with TournamentRunLock(self.directory):
            with self.assertRaises(TournamentRunLockHeldError):
                TournamentRunner.restore_competition_record_at(
                    self.directory, backup_path
                )

        self.assertFalse(record_path.exists())
        self.assertIsNotNone(committed)
