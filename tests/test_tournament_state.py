from __future__ import annotations

import unittest

from rps_runner.tournament.immutable import thaw_json
from rps_runner.tournament.state import (
    TournamentStateError,
    build_playoff_bracket_record,
    fold_tournament_state,
)
from rps_runner.tournament.storage import StoredCompetitionRecord


_ARTIFACT_MARKERS = {
    "alpha": "a",
    "beta": "b",
    "gamma": "c",
    "delta": "d",
}


def manifest() -> dict[str, object]:
    return {
        "tournament_seed": "123",
        "scheduled_turns_per_match": 300,
        "roster": [
            {
                "team_id": team_id,
                "bot_artifact": {"artifact_digest": marker * 64},
            }
            for team_id, marker in (
                ("alpha", "a"),
                ("beta", "b"),
                ("gamma", "c"),
                ("delta", "d"),
            )
        ],
        "tie_break_keys": {
            "alpha": "10",
            "beta": "20",
            "gamma": "30",
            "delta": "40",
        },
        "qualifying_schedule": [
            {
                "ordinal": 1,
                "bye_team_id": None,
                "fixtures": [
                    {
                        "fixture_id": "qualifying-0001",
                        "ordinal": 1,
                        "batch_ordinal": 1,
                        "team_ids": ["alpha", "beta"],
                        "fixture_seed": "101",
                    },
                    {
                        "fixture_id": "qualifying-0002",
                        "ordinal": 2,
                        "batch_ordinal": 1,
                        "team_ids": ["gamma", "delta"],
                        "fixture_seed": "102",
                    },
                ],
            }
        ],
    }


def terminal_record(
    sequence: int,
    fixture_id: str,
    match_ordinal: int,
    team_ids: tuple[str, str],
    *,
    winner: str | None,
) -> StoredCompetitionRecord:
    outcome = "draw" if winner is None else "win"
    fixture_seed = {
        ("alpha", "beta"): 101,
        ("gamma", "delta"): 102,
    }[team_ids]
    canonical_match_values = {
        (101, 1): (
            7709576413964902478,
            "alpha",
            "beta",
            4228793024919491213,
            18408050786848739827,
        ),
        (101, 2): (
            16191387338004992788,
            "beta",
            "alpha",
            12086671031693006535,
            1713949370700645773,
        ),
        (101, 3): (
            12100650173640807532,
            "alpha",
            "beta",
            4669030192551596549,
            18094709123171065991,
        ),
        (102, 1): (
            4109016285202502236,
            "gamma",
            "delta",
            8190589259286918708,
            2147131373327332200,
        ),
        (102, 2): (
            18324596081919369702,
            "delta",
            "gamma",
            12045062621523015878,
            1261141140565240060,
        ),
        (102, 3): (
            2067810078260220596,
            "gamma",
            "delta",
            13755993109981983230,
            2027672838468256583,
        ),
    }
    match_seed, team_a, team_b, seed_a, seed_b = canonical_match_values[
        (fixture_seed, match_ordinal)
    ]
    if winner is None:
        round_moves = {team_ids[0]: "R", team_ids[1]: "R"}
        round_wins = {team_ids[0]: 0, team_ids[1]: 0}
    elif winner == team_ids[0]:
        round_moves = {team_ids[0]: "R", team_ids[1]: "S"}
        round_wins = {team_ids[0]: 300, team_ids[1]: 0}
    else:
        round_moves = {team_ids[0]: "S", team_ids[1]: "R"}
        round_wins = {team_ids[0]: 0, team_ids[1]: 300}
    moves = {
        team_id: move * 300 for team_id, move in round_moves.items()
    }
    return StoredCompetitionRecord(
        sequence=sequence,
        content_hash=f"hash-{sequence}",
        record={
            "type": "match_terminal",
            "phase": "qualifying",
            "fixture_id": fixture_id,
            "match_id": f"{fixture_id}-match-{match_ordinal}",
            "match_ordinal": match_ordinal,
            "team_ids": list(team_ids),
            "outcome": outcome,
            "winner_team_id": winner,
            "round_wins": round_wins,
            "protocol_forfeit_team_id": None,
            "moves": moves,
            "rounds": [
                {
                    "turn": turn,
                    "moves": round_moves,
                    "winner_team_id": winner,
                }
                for turn in range(300)
            ],
            "faults": {team_ids[0]: None, team_ids[1]: None},
            "match_seed": str(match_seed),
            "bot_positions": {"a": team_a, "b": team_b},
            "bot_visible_seeds": {
                team_a: str(seed_a),
                team_b: str(seed_b),
            },
            "artifact_digests": {
                team_id: _ARTIFACT_MARKERS[team_id] * 64
                for team_id in team_ids
            },
        },
    )


class TournamentStateFoldTests(unittest.TestCase):
    def test_empty_fold_exposes_first_canonical_match_and_empty_standings(self) -> None:
        state = fold_tournament_state(manifest(), ())

        self.assertFalse(state.qualifying_phase_complete)
        self.assertEqual(state.next_qualifying_match.fixture_id, "qualifying-0001")
        self.assertEqual(state.next_qualifying_match.match_ordinal, 1)
        self.assertEqual(state.next_qualifying_match.team_ids, ("alpha", "beta"))
        self.assertEqual(state.next_qualifying_match.fixture_seed, 101)
        self.assertEqual([item.team_id for item in state.standings], [
            "alpha", "beta", "gamma", "delta"
        ])
        self.assertTrue(all(item.standing_points == 0 for item in state.standings))

    def test_fold_reconstructs_series_standings_and_next_match(self) -> None:
        records = (
            terminal_record(1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"),
            terminal_record(2, "qualifying-0001", 2, ("alpha", "beta"), winner="alpha"),
        )

        state = fold_tournament_state(manifest(), records)

        first_series = state.qualifying_series[0]
        self.assertTrue(first_series.is_complete)
        self.assertEqual(first_series.winner, "alpha")
        self.assertEqual(state.next_qualifying_match.fixture_id, "qualifying-0002")
        self.assertEqual(state.next_qualifying_match.match_ordinal, 1)
        standings = {item.team_id: item for item in state.standings}
        self.assertEqual(standings["alpha"].standing_points, 3)
        self.assertEqual(standings["alpha"].match_differential, 2)
        self.assertEqual(standings["beta"].match_differential, -2)

    def test_fold_reports_qualifying_phase_complete_after_every_series(self) -> None:
        records = (
            terminal_record(1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"),
            terminal_record(2, "qualifying-0001", 2, ("alpha", "beta"), winner="alpha"),
            terminal_record(3, "qualifying-0002", 1, ("gamma", "delta"), winner="gamma"),
            terminal_record(4, "qualifying-0002", 2, ("gamma", "delta"), winner="gamma"),
        )

        state = fold_tournament_state(manifest(), records)

        self.assertTrue(state.qualifying_phase_complete)
        self.assertIsNone(state.next_qualifying_match)

    def test_fold_reconstructs_and_validates_canonical_playoff_bracket(self) -> None:
        qualifying_records = (
            terminal_record(
                1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
            ),
            terminal_record(
                2, "qualifying-0001", 2, ("alpha", "beta"), winner="alpha"
            ),
            terminal_record(
                3, "qualifying-0002", 1, ("gamma", "delta"), winner="gamma"
            ),
            terminal_record(
                4, "qualifying-0002", 2, ("gamma", "delta"), winner="gamma"
            ),
        )
        qualified = fold_tournament_state(manifest(), qualifying_records)
        bracket = build_playoff_bracket_record(manifest(), qualified.standings)
        bracket_record = StoredCompetitionRecord(
            sequence=5,
            content_hash="hash-5",
            record=bracket,
        )

        state = fold_tournament_state(
            manifest(), qualifying_records + (bracket_record,)
        )

        self.assertEqual(state.phase.value, "playoff")
        self.assertEqual(
            [(seed.seed, seed.team_id) for seed in state.playoff_seeds],
            [(1, "alpha"), (2, "gamma"), (3, "beta"), (4, "delta")],
        )
        self.assertEqual(
            [fixture.fixture_id for fixture in state.playoff_fixtures],
            ["playoff-semifinal-1", "playoff-semifinal-2", "playoff-final"],
        )

        invalid = dict(bracket)
        invalid["fixtures"] = [dict(item) for item in bracket["fixtures"]]
        invalid["fixtures"][0]["fixture_seed"] = "999"
        invalid_record = StoredCompetitionRecord(
            sequence=5,
            content_hash="invalid-hash",
            record=invalid,
        )
        with self.assertRaisesRegex(TournamentStateError, "does not match"):
            fold_tournament_state(
                manifest(), qualifying_records + (invalid_record,)
            )

    def test_rejects_unknown_fixture(self) -> None:
        record = terminal_record(1, "qualifying-9999", 1, ("alpha", "beta"), winner="alpha")

        with self.assertRaisesRegex(TournamentStateError, "unknown Fixture"):
            fold_tournament_state(manifest(), (record,))

    def test_rejects_terminal_outcome_contradictions(self) -> None:
        invalid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )
        record = thaw_json(invalid.record)
        record["protocol_forfeit_team_id"] = "alpha"
        record["moves"] = {"alpha": "R", "beta": "S"}
        record["rounds"] = record["rounds"][:1]
        record["round_wins"] = {"alpha": 1, "beta": 0}
        record["faults"] = dict(record["faults"])
        record["faults"]["alpha"] = {"kind": "timeout", "turn": 1}
        invalid = StoredCompetitionRecord(
            sequence=1, content_hash="invalid-hash", record=record
        )

        with self.assertRaisesRegex(TournamentStateError, "outcome fields"):
            fold_tournament_state(manifest(), (invalid,))

    def test_rejects_noncanonical_match_identity_values(self) -> None:
        valid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )
        mutations = {
            "Match Seed": lambda record: record.update(match_seed="999"),
            "Bot Positions": lambda record: record.update(
                bot_positions={"a": "beta", "b": "alpha"}
            ),
            "bot-visible Seeds": lambda record: record.update(
                bot_visible_seeds={"alpha": "999", "beta": "998"}
            ),
            "Bot Artifact digests": lambda record: record.update(
                artifact_digests={"alpha": "f" * 64, "beta": "b" * 64}
            ),
        }

        for description, mutate in mutations.items():
            with self.subTest(description=description):
                record = thaw_json(valid.record)
                mutate(record)
                invalid = StoredCompetitionRecord(
                    sequence=1, content_hash="invalid-hash", record=record
                )
                with self.assertRaisesRegex(TournamentStateError, description):
                    fold_tournament_state(manifest(), (invalid,))

    def test_rejects_contradictory_completed_match_details(self) -> None:
        valid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )

        invalid_values = []
        invalid_moves = thaw_json(valid.record)
        invalid_moves["moves"]["alpha"] = "X"
        invalid_values.append(("completed moves", invalid_moves))

        invalid_round = thaw_json(valid.record)
        invalid_round["rounds"][0]["winner_team_id"] = "beta"
        invalid_values.append(("completed Rounds", invalid_round))

        invalid_round_wins = thaw_json(valid.record)
        invalid_round_wins["round_wins"] = {"alpha": 9, "beta": 0}
        invalid_values.append(("Round wins", invalid_round_wins))

        extra_move = thaw_json(valid.record)
        extra_move["moves"]["alpha"] += "R"
        invalid_values.append(("completed moves", extra_move))

        invalid_fault = thaw_json(valid.record)
        invalid_fault["faults"]["alpha"] = {"kind": "timeout", "turn": 1}
        invalid_values.append(("normalized faults", invalid_fault))

        for description, record in invalid_values:
            with self.subTest(description=description):
                invalid = StoredCompetitionRecord(
                    sequence=1, content_hash="invalid-hash", record=record
                )
                with self.assertRaisesRegex(TournamentStateError, description):
                    fold_tournament_state(manifest(), (invalid,))

    def test_rejects_truncated_unfaulted_match(self) -> None:
        valid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )
        record = thaw_json(valid.record)
        record["moves"] = {"alpha": "R", "beta": "S"}
        record["rounds"] = record["rounds"][:1]
        record["round_wins"] = {"alpha": 1, "beta": 0}

        with self.assertRaisesRegex(TournamentStateError, "number of completed"):
            fold_tournament_state(
                manifest(),
                (
                    StoredCompetitionRecord(
                        sequence=1,
                        content_hash="invalid-hash",
                        record=record,
                    ),
                ),
            )

    def test_rejects_fault_after_all_scheduled_turns(self) -> None:
        valid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )
        record = thaw_json(valid.record)
        record["winner_team_id"] = "beta"
        record["protocol_forfeit_team_id"] = "alpha"
        record["faults"]["alpha"] = {"kind": "timeout", "turn": 300}

        with self.assertRaisesRegex(TournamentStateError, "number of completed"):
            fold_tournament_state(
                manifest(),
                (
                    StoredCompetitionRecord(
                        sequence=1,
                        content_hash="invalid-hash",
                        record=record,
                    ),
                ),
            )

    def test_rejects_noncanonical_record_and_nested_fields(self) -> None:
        valid = terminal_record(
            1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"
        )
        invalid_values = []
        telemetry = thaw_json(valid.record)
        telemetry["stderr"] = "operational detail"
        invalid_values.append(("Competition Record fields", telemetry))

        round_detail = thaw_json(valid.record)
        round_detail["rounds"][0]["duration_ms"] = 5
        invalid_values.append(("completed Rounds", round_detail))

        fault_detail = thaw_json(valid.record)
        fault_detail["protocol_forfeit_team_id"] = "alpha"
        fault_detail["winner_team_id"] = "beta"
        fault_detail["faults"]["alpha"] = {
            "kind": "timeout",
            "turn": 300,
            "raw_error": "secret",
        }
        invalid_values.append(("normalized faults", fault_detail))

        for description, record in invalid_values:
            with self.subTest(description=description):
                with self.assertRaisesRegex(TournamentStateError, description):
                    fold_tournament_state(
                        manifest(),
                        (
                            StoredCompetitionRecord(
                                sequence=1,
                                content_hash="invalid-hash",
                                record=record,
                            ),
                        ),
                    )

    def test_rejects_duplicate_gapped_and_out_of_order_match_ordinals(self) -> None:
        first = terminal_record(1, "qualifying-0001", 1, ("alpha", "beta"), winner=None)
        invalid_cases = (
            terminal_record(2, "qualifying-0001", 1, ("alpha", "beta"), winner=None),
            terminal_record(2, "qualifying-0001", 3, ("alpha", "beta"), winner=None),
            terminal_record(1, "qualifying-0001", 2, ("alpha", "beta"), winner=None),
        )

        for invalid in invalid_cases:
            with self.subTest(match_ordinal=invalid.record["match_ordinal"]):
                prefix = () if invalid.sequence == 1 else (first,)
                with self.assertRaisesRegex(TournamentStateError, "Match ordinal"):
                    fold_tournament_state(manifest(), prefix + (invalid,))

    def test_rejects_a_later_fixture_before_the_current_series_completes(self) -> None:
        record = terminal_record(1, "qualifying-0002", 1, ("gamma", "delta"), winner="gamma")

        with self.assertRaisesRegex(TournamentStateError, "canonical Fixture order"):
            fold_tournament_state(manifest(), (record,))

    def test_rejects_record_after_series_completion(self) -> None:
        records = (
            terminal_record(1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"),
            terminal_record(2, "qualifying-0001", 2, ("alpha", "beta"), winner="alpha"),
            terminal_record(3, "qualifying-0001", 3, ("alpha", "beta"), winner="beta"),
        )

        with self.assertRaisesRegex(TournamentStateError, "complete Series"):
            fold_tournament_state(manifest(), records)


if __name__ == "__main__":
    unittest.main()
