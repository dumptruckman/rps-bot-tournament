from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import shlex
import sys
import unittest

from rps_runner.engine import InfrastructureError, MatchConfig
from rps_runner.tournament.match_executor import (
    LocalMatchExecutor,
    MatchExecutionRequest,
    MatchExecutionResult,
    ResolvedArtifactReference,
)
from rps_runner.tournament.storage import canonical_json_bytes


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKS_PROTOCOL = PROJECT_ROOT / "tests" / "fixtures" / "bots" / "checks_protocol.py"


def checking_bot(moves: str, expected_seed: int) -> str:
    return shlex.join(
        [
            sys.executable,
            str(CHECKS_PROTOCOL),
            moves,
            "1",
            "300",
            str(expected_seed),
        ]
    )


def request(**overrides: object) -> MatchExecutionRequest:
    values = {
        "tournament_id": "summer-cup",
        "fixture_id": "qualifying-001",
        "series_id": "qualifying-001-series",
        "match_id": "qualifying-001-match-1",
        "attempt_number": 1,
        "team_a_id": "red-team",
        "team_b_id": "blue-team",
        "artifact_digest_a": "sha256:red",
        "artifact_digest_b": "sha256:blue",
        "match_seed": 333,
        "bot_visible_seed_a": 111,
        "bot_visible_seed_b": 222,
        "protocol_version": 1,
        "scheduled_turns": 300,
        "first_move_timeout_ms": 901,
        "move_timeout_ms": 902,
        "total_timeout_ms": 903,
        "stderr_limit_bytes": 904,
        "stdout_limit_bytes": 905,
        "cpu_limit_ms": 3_000,
        "cpu_quota_millis_per_second": 909,
        "memory_limit_bytes": 907,
        "process_limit": 2,
        "filesystem_write_limit_bytes": 908,
        "network_access_allowed": False,
    }
    values.update(overrides)
    return MatchExecutionRequest(**values)


def engine_result(
    *,
    status: str,
    winner: object,
    faults: dict[str, object],
    rounds: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "scheduled_rounds": 300,
        "seed": 333,
        "status": status,
        "winner": winner,
        "score": {"a": 1, "b": 0, "draws": 0},
        "completed_rounds": len(rounds),
        "moves": {
            "a": "".join(str(round_result["a"]) for round_result in rounds),
            "b": "".join(str(round_result["b"]) for round_result in rounds),
        },
        "rounds": rounds,
        "faults": faults,
        "timing": {
            "clock": "monotonic",
            "total_response_ns": {"a": 10, "b": 20},
        },
        "bots": {
            "a": {"command": "red", "stderr": "", "stderr_truncated": False},
            "b": {"command": "blue", "stderr": "", "stderr_truncated": False},
        },
    }


class TournamentMatchExecutorTests(unittest.TestCase):
    def test_suspected_security_violation_is_distinct_from_other_outcomes(self) -> None:
        result = MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=None,
            operational_telemetry={"raw_evidence": {"network": "blocked"}},
            suspected_security_violation_team_id="red-team",
            evidence_link="evidence:summer-cup/qualifying-001-match-1/attempt-1",
        )

        self.assertFalse(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertEqual(result.suspected_security_violation_team_id, "red-team")
        self.assertEqual(
            result.evidence_link,
            "evidence:summer-cup/qualifying-001-match-1/attempt-1",
        )

    def test_security_incident_can_implicate_both_competing_teams(self) -> None:
        result = MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=None,
            operational_telemetry={"raw_evidence": "two-team-incident"},
            suspected_security_violation_team_ids=("red-team", "blue-team"),
            evidence_link="evidence:summer-cup/double-incident",
        )

        self.assertEqual(
            result.suspected_security_violation_team_ids,
            ("red-team", "blue-team"),
        )
        with self.assertRaisesRegex(ValueError, "either the singular or plural"):
            MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={},
                suspected_security_violation_team_id="red-team",
                suspected_security_violation_team_ids=("blue-team",),
                evidence_link="evidence:summer-cup/ambiguous-incident",
            )

    def test_execution_result_rejects_ambiguous_security_outcomes(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence link"):
            MatchExecutionResult(
                infrastructure_failure=False,
                competitive_outcome=None,
                operational_telemetry={},
                suspected_security_violation_team_id="red-team",
            )

    def test_request_requires_the_sealed_300_turn_match_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "300"):
            request(scheduled_turns=299)

    def test_request_requires_protocol_version_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "protocol version 1"):
            request(protocol_version=2)

    def test_request_rejects_invalid_resource_and_security_limits(self) -> None:
        cases = (
            ("stdout_limit_bytes", 0),
            ("cpu_limit_ms", 0),
            ("cpu_limit_ms", 1_001),
            ("cpu_quota_millis_per_second", 0),
            ("memory_limit_bytes", 0),
            ("process_limit", 0),
            ("filesystem_write_limit_bytes", 0),
            ("network_access_allowed", "no"),
        )

        for field_name, value in cases:
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValueError, field_name):
                    request(**{field_name: value})

    def test_request_is_translated_and_normalized_by_team_identity(self) -> None:
        captured_configs: list[MatchConfig] = []

        def fake_run_match(config: MatchConfig) -> dict[str, object]:
            captured_configs.append(config)
            return {
                "protocol_version": 1,
                "scheduled_rounds": 300,
                "seed": 333,
                "status": "completed",
                "winner": "a",
                "score": {"a": 1, "b": 0, "draws": 0},
                "completed_rounds": 1,
                "moves": {"a": "R", "b": "S"},
                "rounds": [
                    {
                        "turn": 0,
                        "a": "R",
                        "b": "S",
                        "winner": "a",
                        "response_time_ns": {"a": 10, "b": 20},
                    }
                ],
                "faults": {"a": None, "b": None},
                "timing": {
                    "clock": "monotonic",
                    "total_response_ns": {"a": 10, "b": 20},
                },
                "bots": {
                    "a": {
                        "command": "/bots/red",
                        "stderr": "red diagnostic",
                        "stderr_truncated": False,
                    },
                    "b": {
                        "command": "/bots/blue",
                        "stderr": "blue diagnostic",
                        "stderr_truncated": False,
                    },
                },
            }

        executor = LocalMatchExecutor(
            artifact_command_resolver=lambda team_id, digest: f"/{team_id}/{digest}",
            match_runner=fake_run_match,
        )

        result = executor.execute(request())

        self.assertEqual(
            captured_configs,
            [
                MatchConfig(
                    bot_a="/red-team/sha256:red",
                    bot_b="/blue-team/sha256:blue",
                    rounds=300,
                    seed=333,
                    first_move_timeout_ms=901,
                    move_timeout_ms=902,
                    total_timeout_ms=903,
                    stderr_limit_bytes=904,
                    stdout_limit_bytes=905,
                    bot_a_seed=111,
                    bot_b_seed=222,
                )
            ],
        )
        self.assertFalse(result.infrastructure_failure)
        self.assertEqual(
            result.competitive_outcome,
            {
                "tournament_id": "summer-cup",
                "fixture_id": "qualifying-001",
                "series_id": "qualifying-001-series",
                "match_id": "qualifying-001-match-1",
                "protocol_version": 1,
                "scheduled_turns": 300,
                "match_seed": 333,
                "positions": {
                    "a": {
                        "team_id": "red-team",
                        "artifact_digest": "sha256:red",
                        "bot_visible_seed": 111,
                    },
                    "b": {
                        "team_id": "blue-team",
                        "artifact_digest": "sha256:blue",
                        "bot_visible_seed": 222,
                    },
                },
                "status": "completed",
                "outcome": "win",
                "winner_team_id": "red-team",
                "score": {"red-team": 1, "blue-team": 0, "draws": 0},
                "moves": {"red-team": "R", "blue-team": "S"},
                "rounds": [
                    {
                        "turn": 0,
                        "moves": {"red-team": "R", "blue-team": "S"},
                        "winner_team_id": "red-team",
                    }
                ],
                "faults": {"red-team": None, "blue-team": None},
            },
        )
        self.assertEqual(result.operational_telemetry["attempt_number"], 1)
        self.assertEqual(
            result.operational_telemetry["round_response_times_ns"],
            [{"red-team": 10, "blue-team": 20}],
        )
        self.assertEqual(
            result.operational_telemetry["timing"],
            {
                "clock": "monotonic",
                "total_response_ns": {"red-team": 10, "blue-team": 20},
            },
        )
        self.assertEqual(
            result.operational_telemetry["bots"]["red-team"]["stderr"],
            "red diagnostic",
        )
        self.assertEqual(
            result.operational_telemetry["resource_limits"],
            {
                "first_move_timeout_ms": 901,
                "move_timeout_ms": 902,
                "total_timeout_ms": 903,
                "stderr_limit_bytes": 904,
                "stdout_limit_bytes": 905,
                "cpu_limit_ms": 3000,
                "cpu_quota_millis_per_second": 909,
                "memory_limit_bytes": 907,
                "process_limit": 2,
                "open_file_limit": 64,
                "filesystem_write_limit_bytes": 908,
                "network_access_allowed": False,
                "execution_profile_version": "docker-execution-v1",
            },
        )

    def test_wrong_engine_protocol_becomes_an_infrastructure_failure(self) -> None:
        raw_result = engine_result(
            status="completed",
            winner="draw",
            faults={"a": None, "b": None},
            rounds=[],
        )
        raw_result["protocol_version"] = 2
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: raw_result,
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertEqual(
            result.operational_telemetry["infrastructure_failure"]["kind"],
            "InvalidMatchResultError",
        )
        self.assertIn(
            "protocol_version",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )
        self.assertEqual(
            result.operational_telemetry["resource_limits"]["cpu_limit_ms"],
            3000,
        )

    def test_wrong_engine_turn_count_becomes_an_infrastructure_failure(self) -> None:
        raw_result = engine_result(
            status="completed",
            winner="draw",
            faults={"a": None, "b": None},
            rounds=[],
        )
        raw_result["scheduled_rounds"] = 299
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: raw_result,
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertIn(
            "scheduled_rounds",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )

    def test_wrong_engine_match_seed_becomes_an_infrastructure_failure(self) -> None:
        raw_result = engine_result(
            status="completed",
            winner="draw",
            faults={"a": None, "b": None},
            rounds=[],
        )
        raw_result["seed"] = 444
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: raw_result,
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertIn(
            "seed",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )

    def test_invalid_engine_status_and_winner_shapes_are_failures(self) -> None:
        cases = (
            ("unknown", "a"),
            ("completed", None),
            ("forfeit", "draw"),
            ("double_forfeit", "a"),
        )

        for status, winner in cases:
            with self.subTest(status=status, winner=winner):
                raw_result = engine_result(
                    status=status,
                    winner=winner,
                    faults={"a": None, "b": None},
                    rounds=[],
                )
                executor = LocalMatchExecutor(
                    lambda team_id, digest: team_id,
                    lambda config, value=raw_result: value,
                )

                result = executor.execute(request())

                self.assertTrue(result.infrastructure_failure)
                self.assertIsNone(result.competitive_outcome)
                self.assertIn(
                    "status/winner",
                    result.operational_telemetry["infrastructure_failure"]["message"],
                )

    def test_engine_forfeit_requires_exactly_the_losing_bot_fault(self) -> None:
        raw_result = engine_result(
            status="forfeit",
            winner="b",
            faults={"a": None, "b": None},
            rounds=[],
        )
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: raw_result,
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertIn(
            "fault",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )

    def test_malformed_engine_payload_shapes_are_infrastructure_failures(self) -> None:
        cases = (
            ("score", []),
            ("moves", []),
            ("rounds", {}),
            ("timing", []),
            ("bots", []),
        )

        for field, malformed_value in cases:
            with self.subTest(field=field):
                raw_result = engine_result(
                    status="completed",
                    winner="draw",
                    faults={"a": None, "b": None},
                    rounds=[],
                )
                raw_result[field] = malformed_value
                executor = LocalMatchExecutor(
                    lambda team_id, digest: team_id,
                    lambda config, value=raw_result: value,
                )

                result = executor.execute(request())

                self.assertTrue(result.infrastructure_failure)
                self.assertIsNone(result.competitive_outcome)
                self.assertIn(
                    field,
                    result.operational_telemetry["infrastructure_failure"]["message"],
                )

    def test_malformed_completed_round_becomes_an_infrastructure_failure(self) -> None:
        raw_result = engine_result(
            status="completed",
            winner="a",
            faults={"a": None, "b": None},
            rounds=[
                {
                    "turn": 0,
                    "a": "R",
                    "b": "S",
                    "winner": "a",
                    "response_time_ns": {"a": 10, "b": 20},
                }
            ],
        )
        raw_result["rounds"][0]["a"] = []
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: raw_result,
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertIn(
            "rounds.a",
            result.operational_telemetry["infrastructure_failure"]["message"],
        )

    def test_infrastructure_error_is_a_failed_attempt_without_an_outcome(self) -> None:
        def unavailable_runner(config: MatchConfig) -> dict[str, object]:
            raise InfrastructureError("container unavailable")

        executor = LocalMatchExecutor(
            artifact_command_resolver=lambda team_id, digest: f"/{team_id}/{digest}",
            match_runner=unavailable_runner,
        )

        result = executor.execute(request(attempt_number=2))

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertEqual(
            result.operational_telemetry,
            {
                "tournament_id": "summer-cup",
                "fixture_id": "qualifying-001",
                "match_id": "qualifying-001-match-1",
                "attempt_number": 2,
                "resource_limits": {
                    "first_move_timeout_ms": 901,
                    "move_timeout_ms": 902,
                    "total_timeout_ms": 903,
                    "stderr_limit_bytes": 904,
                    "stdout_limit_bytes": 905,
                    "cpu_limit_ms": 3000,
                    "cpu_quota_millis_per_second": 909,
                    "memory_limit_bytes": 907,
                    "process_limit": 2,
                    "open_file_limit": 64,
                    "filesystem_write_limit_bytes": 908,
                    "network_access_allowed": False,
                    "execution_profile_version": "docker-execution-v1",
                },
                "commands": {
                    "red-team": "/red-team/sha256:red",
                    "blue-team": "/blue-team/sha256:blue",
                },
                "infrastructure_failure": {
                    "kind": "InfrastructureError",
                    "message": "container unavailable",
                },
            },
        )

    def test_artifact_resolution_failure_is_a_failed_match_attempt(self) -> None:
        def unavailable_artifact(team_id: str, digest: str) -> str:
            raise InfrastructureError("artifact unavailable")

        executor = LocalMatchExecutor(
            artifact_command_resolver=unavailable_artifact,
            match_runner=lambda config: self.fail("Match Runner must not be called"),
        )

        result = executor.execute(request())

        self.assertTrue(result.infrastructure_failure)
        self.assertIsNone(result.competitive_outcome)
        self.assertEqual(
            result.operational_telemetry["infrastructure_failure"],
            {"kind": "InfrastructureError", "message": "artifact unavailable"},
        )

    def test_artifact_resolution_diagnostics_are_operational_telemetry(self) -> None:
        executor = LocalMatchExecutor(
            artifact_command_resolver=lambda team_id, digest: (
                ResolvedArtifactReference(
                    f"/{team_id}/{digest}",
                    {
                        "status": "verified",
                        "archive_restored": team_id == "red-team",
                    },
                )
            ),
            match_runner=lambda config: engine_result(
                status="completed",
                winner="draw",
                faults={"a": None, "b": None},
                rounds=[],
            ),
        )

        result = executor.execute(request())

        self.assertEqual(
            result.operational_telemetry["artifact_resolutions"],
            {
                "red-team": {
                    "status": "verified",
                    "archive_restored": True,
                },
                "blue-team": {
                    "status": "verified",
                    "archive_restored": False,
                },
            },
        )

    def test_engine_outcomes_are_normalized_to_team_relative_facts(self) -> None:
        completed_round = {
            "turn": 0,
            "a": "R",
            "b": "S",
            "winner": "a",
            "response_time_ns": {"a": 10, "b": 20},
        }
        cases = (
            (
                "draw",
                engine_result(
                    status="completed",
                    winner="draw",
                    faults={"a": None, "b": None},
                    rounds=[completed_round],
                ),
                None,
                {"red-team": None, "blue-team": None},
            ),
            (
                "win",
                engine_result(
                    status="forfeit",
                    winner="b",
                    faults={
                        "a": {"kind": "timeout", "turn": 1, "detail": "51ms"},
                        "b": None,
                    },
                    rounds=[completed_round],
                ),
                "blue-team",
                {
                    "red-team": {"kind": "timeout", "turn": 1},
                    "blue-team": None,
                },
            ),
            (
                "double_forfeit",
                engine_result(
                    status="double_forfeit",
                    winner=None,
                    faults={
                        "a": {"kind": "invalid_move", "turn": 0, "detail": "X"},
                        "b": {"kind": "unexpected_exit", "turn": 0, "detail": ""},
                    },
                    rounds=[],
                ),
                None,
                {
                    "red-team": {"kind": "invalid_move", "turn": 0},
                    "blue-team": {"kind": "unexpected_exit", "turn": 0},
                },
            ),
        )

        for expected_outcome, raw_result, expected_winner, expected_faults in cases:
            with self.subTest(expected_outcome=expected_outcome):
                executor = LocalMatchExecutor(
                    artifact_command_resolver=lambda team_id, digest: team_id,
                    match_runner=lambda config, result=raw_result: result,
                )

                result = executor.execute(request())
                competitive = result.competitive_outcome

                self.assertIsNotNone(competitive)
                assert competitive is not None
                self.assertEqual(competitive["outcome"], expected_outcome)
                self.assertEqual(competitive["winner_team_id"], expected_winner)
                self.assertEqual(competitive["faults"], expected_faults)
                self.assertEqual(len(competitive["rounds"]), len(raw_result["rounds"]))
                for normalized_round in competitive["rounds"]:
                    self.assertNotIn("response_time_ns", normalized_round)

    def test_competitive_payload_is_invariant_when_telemetry_changes(self) -> None:
        first_round = {
            "turn": 0,
            "a": "R",
            "b": "S",
            "winner": "a",
            "response_time_ns": {"a": 10, "b": 20},
        }
        second_round = dict(first_round)
        second_round["response_time_ns"] = {"a": 900, "b": 800}
        first_raw = engine_result(
            status="forfeit",
            winner="b",
            faults={
                "a": {"kind": "timeout", "turn": 1, "detail": "51ms"},
                "b": None,
            },
            rounds=[first_round],
        )
        second_raw = engine_result(
            status="forfeit",
            winner="b",
            faults={
                "a": {"kind": "timeout", "turn": 1, "detail": "99ms"},
                "b": None,
            },
            rounds=[second_round],
        )
        first_raw["timing"] = {
            "clock": "monotonic",
            "host": "worker-1",
            "total_response_ns": {"a": 10, "b": 20},
        }
        second_raw["timing"] = {
            "clock": "monotonic",
            "host": "worker-2",
            "total_response_ns": {"a": 900, "b": 800},
        }
        first_raw["bots"] = {"a": {"stderr": "first"}, "b": {"stderr": ""}}
        second_raw["bots"] = {"a": {"stderr": "second"}, "b": {"stderr": ""}}

        first = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: first_raw,
        ).execute(request())
        second = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: second_raw,
        ).execute(request())

        self.assertEqual(first.competitive_outcome, second.competitive_outcome)
        self.assertNotEqual(first.operational_telemetry, second.operational_telemetry)

    def test_request_and_result_values_are_immutable(self) -> None:
        execution_request = request()
        executor = LocalMatchExecutor(
            lambda team_id, digest: team_id,
            lambda config: engine_result(
                status="completed",
                winner="draw",
                faults={"a": None, "b": None},
                rounds=[],
            ),
        )

        result = executor.execute(execution_request)

        with self.assertRaises(FrozenInstanceError):
            execution_request.match_seed = 999
        with self.assertRaises(FrozenInstanceError):
            result.infrastructure_failure = True
        assert result.competitive_outcome is not None
        with self.assertRaises(TypeError):
            result.competitive_outcome["winner_team_id"] = "blue-team"
        with self.assertRaises(TypeError):
            result.operational_telemetry["attempt_number"] = 99
        with self.assertRaises(TypeError):
            result.competitive_outcome["positions"]["a"]["team_id"] = "changed"
        with self.assertRaises(TypeError):
            result.operational_telemetry["round_response_times_ns"].append({})
        self.assertIn(
            b'"winner_team_id":null',
            canonical_json_bytes(result.competitive_outcome),
        )

    def test_real_match_runner_contract_uses_team_specific_seeds(self) -> None:
        commands = {
            "sha256:red": checking_bot("R" * 300, 111),
            "sha256:blue": checking_bot("S" * 300, 222),
        }
        executor = LocalMatchExecutor(
            artifact_command_resolver=lambda team_id, digest: commands[digest]
        )

        result = executor.execute(request())

        self.assertFalse(result.infrastructure_failure)
        competitive = result.competitive_outcome
        self.assertIsNotNone(competitive)
        assert competitive is not None
        self.assertEqual(competitive["outcome"], "win")
        self.assertEqual(competitive["winner_team_id"], "red-team")
        self.assertEqual(len(competitive["rounds"]), 300)
        self.assertEqual(competitive["faults"], {"red-team": None, "blue-team": None})


if __name__ == "__main__":
    unittest.main()
