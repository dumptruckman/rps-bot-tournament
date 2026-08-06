from __future__ import annotations

import unittest

from rps_runner.tournament.immutable import thaw_json
from rps_runner.tournament.state import (
    TournamentStateError,
    build_playoff_bracket_record,
    build_tournament_ended_without_champion_record,
    build_security_violation_ruling_record,
    build_security_violation_suspected_record,
    fold_tournament_state,
)
from rps_runner.tournament.competition import Standing
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
    def test_builds_every_canonical_reduced_playoff_shape(self) -> None:
        standings = tuple(
            Standing(team_id, 0, 0, 0, 0, 0, 0, 0, tie_break_key)
            for tie_break_key, team_id in enumerate(
                ("alpha", "beta", "gamma", "delta"), start=1
            )
        )

        expected_fixtures = {
            4: [
                ("playoff-semifinal-1", "semifinal", ["alpha", "delta"]),
                ("playoff-semifinal-2", "semifinal", ["beta", "gamma"]),
                ("playoff-final", "final", [None, None]),
            ],
            3: [
                ("playoff-semifinal-1", "semifinal", ["beta", "gamma"]),
                ("playoff-final", "final", ["alpha", None]),
            ],
            2: [("playoff-final", "final", ["alpha", "beta"])],
            1: [],
            0: [],
        }

        for count, expected in expected_fixtures.items():
            with self.subTest(eligible_team_count=count):
                record = build_playoff_bracket_record(
                    manifest(), standings[:count]
                )
                self.assertEqual(
                    [
                        (
                            fixture["fixture_id"],
                            fixture["stage"],
                            fixture["team_ids"],
                        )
                        for fixture in record["fixtures"]
                    ],
                    expected,
                )
                self.assertEqual(len(record["seeds"]), count)

    def test_bracket_preserves_authoritative_head_to_head_standing_order(self) -> None:
        standings = (
            Standing("beta", 3, 1, 2, 0, 10, 0, 0, 20),
            Standing("alpha", 3, 1, 3, 0, 20, 0, 0, 10),
        )

        record = build_playoff_bracket_record(manifest(), standings)

        self.assertEqual(
            record["seeds"],
            [
                {"seed": 1, "team_id": "beta"},
                {"seed": 2, "team_id": "alpha"},
            ],
        )
        self.assertEqual(
            record["fixtures"][0]["team_ids"], ["beta", "alpha"]
        )

    def test_zero_eligible_terminal_record_is_rules_driven_and_canonical(self) -> None:
        empty_manifest = manifest() | {
            "roster": [],
            "tie_break_keys": {},
            "qualifying_schedule": [],
        }
        bracket = StoredCompetitionRecord(
            1,
            build_playoff_bracket_record(empty_manifest, ()),
            "hash-1",
        )
        terminal = StoredCompetitionRecord(
            2,
            build_tournament_ended_without_champion_record(),
            "hash-2",
        )

        state = fold_tournament_state(empty_manifest, (bracket, terminal))

        self.assertTrue(state.ended_without_champion)
        self.assertIsNone(state.champion_team_id)
        self.assertFalse(state.bracket_locked)
        self.assertIsNone(state.next_playoff_match)

        malformed = thaw_json(terminal.record)
        malformed["reason_code"] = "operator_abort"
        with self.assertRaisesRegex(TournamentStateError, "non-canonical"):
            fold_tournament_state(
                empty_manifest,
                (bracket, StoredCompetitionRecord(2, malformed, "bad-hash")),
            )

    def test_fold_reconstructs_pending_and_confirmed_qualifying_disqualification(
        self,
    ) -> None:
        incident = StoredCompetitionRecord(
            sequence=1,
            content_hash="hash-1",
            record=build_security_violation_suspected_record(
                fixture_id="qualifying-0001",
                match_id="qualifying-0001-match-1",
                match_ordinal=1,
                team_ids=("alpha", "beta"),
                suspected_team_id="alpha",
                evidence_link="evidence:cup/incident-1",
            ),
        )
        pending = fold_tournament_state(manifest(), (incident,))
        self.assertEqual(pending.pending_security_ruling.suspected_team_id, "alpha")
        self.assertIsNone(pending.next_qualifying_match)

        ruling = StoredCompetitionRecord(
            sequence=2,
            content_hash="hash-2",
            record=build_security_violation_ruling_record(
                pending.pending_security_ruling,
                decision="confirmed",
                organizer_id="organizer-1",
                reason_code="confirmed_prohibited_behavior",
                note=None,
            ),
        )
        administrative = StoredCompetitionRecord(
            sequence=3,
            content_hash="hash-3",
            record={
                "type": "administrative_series_win",
                "phase": "qualifying",
                "fixture_id": "qualifying-0001",
                "team_ids": ["alpha", "beta"],
                "winner_team_id": "beta",
                "disqualified_team_id": "alpha",
                "reason_code": "opponent_disqualified",
                "ruling_match_id": "qualifying-0001-match-1",
            },
        )
        ruled_prefix = fold_tournament_state(manifest(), (incident, ruling))
        with self.assertRaises(TypeError):
            ruled_prefix.pending_administrative_records[0][
                "winner_team_id"
            ] = "gamma"

        state = fold_tournament_state(manifest(), (incident, ruling, administrative))

        self.assertEqual(state.disqualified_team_ids, ("alpha",))
        self.assertEqual(state.qualifying_series[0].administrative_winner_id, "beta")
        self.assertEqual(state.next_qualifying_match.fixture_id, "qualifying-0002")
        standings = {standing.team_id: standing for standing in state.standings}
        self.assertNotIn("alpha", standings)
        self.assertEqual(standings["beta"].standing_points, 3)
        self.assertEqual(standings["beta"].match_wins, 0)

    def test_fold_rejects_impossible_incident_and_ruling_histories(self) -> None:
        valid_incident_record = build_security_violation_suspected_record(
            fixture_id="qualifying-0001",
            match_id="qualifying-0001-match-1",
            match_ordinal=1,
            team_ids=("alpha", "beta"),
            suspected_team_id="alpha",
            evidence_link="evidence:cup/incident-1",
        )
        valid_incident = StoredCompetitionRecord(1, valid_incident_record, "hash-1")
        pending = fold_tournament_state(manifest(), (valid_incident,))
        valid_ruling_record = build_security_violation_ruling_record(
            pending.pending_security_ruling,
            decision="rejected",
            organizer_id="organizer-1",
            reason_code="attribution_not_confirmed",
        )
        invalid_cases = []
        wrong_team = thaw_json(valid_incident_record)
        wrong_team["suspected_team_id"] = "gamma"
        invalid_cases.append(
            (
                "next canonical Match",
                (StoredCompetitionRecord(1, wrong_team, "h"),),
            )
        )
        ruling_first = StoredCompetitionRecord(1, valid_ruling_record, "h")
        invalid_cases.append(("no pending suspicion", (ruling_first,)))
        duplicate_incident = StoredCompetitionRecord(2, valid_incident_record, "h2")
        invalid_cases.append(("already awaiting", (valid_incident, duplicate_incident)))
        wrong_match = thaw_json(valid_ruling_record)
        wrong_match["match_id"] = "qualifying-0001-match-2"
        invalid_cases.append(
            (
                "does not resolve",
                (valid_incident, StoredCompetitionRecord(2, wrong_match, "h2")),
            )
        )
        valid_ruling = StoredCompetitionRecord(2, valid_ruling_record, "h2")
        duplicate_ruling = StoredCompetitionRecord(3, valid_ruling_record, "h3")
        invalid_cases.append(
            (
                "no pending suspicion",
                (valid_incident, valid_ruling, duplicate_ruling),
            )
        )
        confirmed_ruling_record = build_security_violation_ruling_record(
            pending.pending_security_ruling,
            decision="confirmed",
            organizer_id="organizer-1",
            reason_code="confirmed_prohibited_behavior",
        )
        administrative_record = {
            "type": "administrative_series_win",
            "phase": "qualifying",
            "fixture_id": "qualifying-0001",
            "team_ids": ["alpha", "beta"],
            "winner_team_id": "beta",
            "disqualified_team_id": "alpha",
            "reason_code": "opponent_disqualified",
            "ruling_match_id": "qualifying-0001-match-1",
        }
        invalid_cases.append(
            (
                "next canonical Match",
                (
                    valid_incident,
                    StoredCompetitionRecord(2, confirmed_ruling_record, "h2"),
                    StoredCompetitionRecord(3, administrative_record, "h3"),
                    StoredCompetitionRecord(4, valid_incident_record, "h4"),
                ),
            )
        )

        for expected, records in invalid_cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(TournamentStateError, expected):
                    fold_tournament_state(manifest(), records)

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
