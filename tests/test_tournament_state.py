from __future__ import annotations

import unittest

from rps_runner.tournament.state import (
    TournamentStateError,
    build_playoff_bracket_record,
    fold_tournament_state,
)
from rps_runner.tournament.storage import StoredCompetitionRecord


def manifest() -> dict[str, object]:
    return {
        "tournament_seed": "123",
        "roster": [
            {"team_id": "alpha"},
            {"team_id": "beta"},
            {"team_id": "gamma"},
            {"team_id": "delta"},
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
            "round_wins": {team_ids[0]: 1, team_ids[1]: 0},
            "protocol_forfeit_team_id": None,
        },
    )


class TournamentStateFoldTests(unittest.TestCase):
    def test_empty_fold_exposes_first_canonical_match_and_empty_standings(self) -> None:
        state = fold_tournament_state(manifest(), ())

        self.assertFalse(state.qualification_complete)
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

    def test_fold_reports_qualification_complete_after_every_series(self) -> None:
        records = (
            terminal_record(1, "qualifying-0001", 1, ("alpha", "beta"), winner="alpha"),
            terminal_record(2, "qualifying-0001", 2, ("alpha", "beta"), winner="alpha"),
            terminal_record(3, "qualifying-0002", 1, ("gamma", "delta"), winner="gamma"),
            terminal_record(4, "qualifying-0002", 2, ("gamma", "delta"), winner="gamma"),
        )

        state = fold_tournament_state(manifest(), records)

        self.assertTrue(state.qualification_complete)
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
