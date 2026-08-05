from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Optional

from rps_runner.tournament.runner import (
    BotArtifactManifest,
    MatchExecutionRequest,
    Team,
    TournamentRunner,
)
from rps_runner.tournament.match_executor import MatchExecutionResult
from rps_runner.tournament.storage import (
    load_competition_records,
    load_manifest,
    load_scoreboard_projection,
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
            "faults": {
                request.team_a_id: None,
                request.team_b_id: None,
            },
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
        self.assertEqual(manifest["scheduled_turns_per_match"], 300)
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

        def execute(request: MatchExecutionRequest) -> MatchExecutionResult:
            requests.append(request)
            return executor_result(
                request, winner_team_id="beta", score=(7, 3)
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
                "round_wins": {"beta": 7, "delta": 3},
                "protocol_forfeit_team_id": None,
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
            self.directory, match_executor=second_executor
        )
        resumed.play_next_match()

        third_requests: list[str] = []

        def third_executor(request: MatchExecutionRequest) -> MatchExecutionResult:
            third_requests.append(request.match_id)
            return executor_result(request, winner_team_id=None)

        resumed_again = TournamentRunner.open(
            self.directory, match_executor=third_executor
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
