from fractions import Fraction
import unittest

from rps_runner.tournament.competition import (
    MatchOutcome,
    MatchResult,
    Phase,
    PlayoffFixture,
    PlayoffStage,
    Series,
    Standing,
    calculate_qualifying_standings,
    create_playoff_bracket,
    rank_standings,
)


TEAM_A = "alpha"
TEAM_B = "beta"


class SeriesScoringTests(unittest.TestCase):
    def test_series_ends_after_two_match_wins(self) -> None:
        series = Series(TEAM_A, TEAM_B, Phase.QUALIFYING)

        after_one = series.record(MatchResult.win(TEAM_A, TEAM_B, TEAM_A))
        completed = after_one.record(
            MatchResult.win(TEAM_A, TEAM_B, TEAM_A)
        )

        self.assertFalse(after_one.is_complete)
        self.assertTrue(completed.is_complete)
        self.assertEqual(completed.match_count, 2)
        self.assertEqual(
            completed.series_points,
            {TEAM_A: Fraction(2), TEAM_B: Fraction(0)},
        )
        self.assertEqual(completed.winner, TEAM_A)
        with self.assertRaisesRegex(ValueError, "already complete"):
            completed.record(MatchResult.draw(TEAM_A, TEAM_B))

    def test_three_match_series_scores_wins_draws_and_rounds(self) -> None:
        series = Series(TEAM_A, TEAM_B, Phase.QUALIFYING)

        series = series.record(
            MatchResult.win(
                TEAM_A, TEAM_B, TEAM_A, round_wins=(7, 3)
            )
        )
        series = series.record(
            MatchResult.draw(TEAM_A, TEAM_B, round_wins=(4, 4))
        )
        completed = series.record(
            MatchResult.win(
                TEAM_A, TEAM_B, TEAM_B, round_wins=(2, 6)
            )
        )

        self.assertFalse(series.is_complete)
        self.assertEqual(
            completed.series_points,
            {TEAM_A: Fraction(3, 2), TEAM_B: Fraction(3, 2)},
        )
        self.assertIsNone(completed.winner)
        self.assertEqual(completed.standing_points, {TEAM_A: 1, TEAM_B: 1})

    def test_double_forfeit_consumes_match_without_series_points(self) -> None:
        series = Series(TEAM_A, TEAM_B, Phase.QUALIFYING)
        series = series.record(MatchResult.double_forfeit(TEAM_A, TEAM_B))
        series = series.record(MatchResult.win(TEAM_A, TEAM_B, TEAM_A))

        self.assertFalse(series.is_complete)
        self.assertEqual(series.match_count, 2)
        self.assertEqual(
            series.series_points,
            {TEAM_A: Fraction(1), TEAM_B: Fraction(0)},
        )
        self.assertEqual(
            series.matches[0].outcome, MatchOutcome.DOUBLE_FORFEIT
        )

    def test_protocol_forfeit_is_a_match_win_without_synthetic_rounds(self) -> None:
        result = MatchResult.protocol_forfeit(
            TEAM_A,
            TEAM_B,
            faulting_team_id=TEAM_A,
            completed_round_wins=(2, 1),
        )

        self.assertEqual(result.winner, TEAM_B)
        self.assertEqual(result.round_wins, {TEAM_A: 2, TEAM_B: 1})
        self.assertEqual(result.protocol_forfeit_team_id, TEAM_A)

    def test_tied_playoff_series_advances_higher_seed(self) -> None:
        series = Series(
            TEAM_A,
            TEAM_B,
            Phase.PLAYOFF,
            higher_seed_team_id=TEAM_B,
        )
        series = series.record(MatchResult.win(TEAM_A, TEAM_B, TEAM_A))
        series = series.record(MatchResult.win(TEAM_A, TEAM_B, TEAM_B))
        completed = series.record(MatchResult.double_forfeit(TEAM_A, TEAM_B))

        self.assertTrue(completed.is_complete)
        self.assertEqual(completed.winner, TEAM_B)


class QualifyingStandingTests(unittest.TestCase):
    def standing(
        self,
        team_id: str,
        *,
        points: int = 3,
        series_wins: int = 1,
        match_wins: int = 2,
        match_losses: int = 1,
        round_wins: int = 20,
        round_losses: int = 10,
        protocol_forfeits: int = 0,
        tie_break_key: int = 100,
    ) -> Standing:
        return Standing(
            team_id=team_id,
            standing_points=points,
            series_wins=series_wins,
            match_wins=match_wins,
            match_losses=match_losses,
            round_wins=round_wins,
            round_losses=round_losses,
            protocol_fault_forfeits=protocol_forfeits,
            tie_break_key=tie_break_key,
        )

    def assert_ranked(self, standings: list[Standing], expected: list[str]) -> None:
        self.assertEqual(
            [standing.team_id for standing in rank_standings(standings)],
            expected,
        )

    def test_ranking_applies_each_non_head_to_head_tie_breaker(self) -> None:
        self.assert_ranked(
            [self.standing("low", points=2), self.standing("high", points=3)],
            ["high", "low"],
        )
        self.assert_ranked(
            [
                self.standing("low", series_wins=1),
                self.standing("high", series_wins=2),
            ],
            ["high", "low"],
        )
        self.assert_ranked(
            [
                self.standing("low", match_wins=2, match_losses=2),
                self.standing("high", match_wins=3, match_losses=1),
            ],
            ["high", "low"],
        )
        self.assert_ranked(
            [
                self.standing("low", round_wins=11, round_losses=10),
                self.standing("high", round_wins=14, round_losses=10),
            ],
            ["high", "low"],
        )
        self.assert_ranked(
            [
                self.standing("low", protocol_forfeits=2),
                self.standing("high", protocol_forfeits=1),
            ],
            ["high", "low"],
        )
        self.assert_ranked(
            [
                self.standing("low", tie_break_key=9),
                self.standing("high", tie_break_key=3),
            ],
            ["high", "low"],
        )

    def test_head_to_head_decides_exactly_two_remaining_tied_teams(self) -> None:
        head_to_head = Series("alpha", "beta", Phase.QUALIFYING)
        head_to_head = head_to_head.record(
            MatchResult.win("alpha", "beta", "alpha")
        ).record(MatchResult.win("alpha", "beta", "alpha"))
        beta = self.standing("beta", tie_break_key=1)
        alpha = self.standing("alpha", tie_break_key=99)

        ranked = rank_standings([beta, alpha], [head_to_head])

        self.assertEqual([item.team_id for item in ranked], ["alpha", "beta"])

    def test_head_to_head_is_skipped_for_three_remaining_tied_teams(self) -> None:
        alpha_over_beta = Series("alpha", "beta", Phase.QUALIFYING)
        alpha_over_beta = alpha_over_beta.record(
            MatchResult.win("alpha", "beta", "alpha")
        ).record(MatchResult.win("alpha", "beta", "alpha"))
        standings = [
            self.standing("alpha", match_wins=2, match_losses=2),
            self.standing("beta", match_wins=4, match_losses=1),
            self.standing("gamma", match_wins=3, match_losses=2),
        ]

        ranked = rank_standings(standings, [alpha_over_beta])

        self.assertEqual(
            [item.team_id for item in ranked],
            ["beta", "gamma", "alpha"],
        )

    def test_calculation_awards_standing_points_and_match_statistics(self) -> None:
        series = Series("alpha", "beta", Phase.QUALIFYING)
        series = series.record(
            MatchResult.protocol_forfeit(
                "alpha",
                "beta",
                faulting_team_id="beta",
                completed_round_wins=(3, 4),
            )
        ).record(
            MatchResult.win(
                "alpha", "beta", "alpha", round_wins=(8, 2)
            )
        )

        standings = calculate_qualifying_standings(
            ["alpha", "beta"], [series], {"alpha": 8, "beta": 9}
        )

        self.assertEqual(
            standings,
            (
                Standing("alpha", 3, 1, 2, 0, 11, 6, 0, 8),
                Standing("beta", 0, 0, 0, 2, 6, 11, 1, 9),
            ),
        )

    def test_administrative_win_has_no_lower_level_statistics(self) -> None:
        result = Series.administrative_win(
            "alpha", "disqualified", Phase.QUALIFYING, winner="alpha"
        )

        standings = calculate_qualifying_standings(
            ["alpha", "disqualified"],
            [result],
            {"alpha": 1, "disqualified": 2},
        )

        self.assertEqual(
            standings[0], Standing("alpha", 3, 1, 0, 0, 0, 0, 0, 1)
        )

    def test_disqualification_preserves_played_result_but_excludes_its_stats(self) -> None:
        played = Series("alpha", "removed", Phase.QUALIFYING)
        played = played.record(
            MatchResult.protocol_forfeit(
                "alpha",
                "removed",
                faulting_team_id="alpha",
                completed_round_wins=(5, 6),
            )
        ).record(MatchResult.win("alpha", "removed", "alpha"))
        played = played.record(MatchResult.draw("alpha", "removed"))

        standings = calculate_qualifying_standings(
            ["alpha", "removed"],
            [played],
            {"alpha": 10, "removed": 20},
            disqualified_team_ids={"removed"},
        )

        self.assertEqual(len(played.matches), 3)
        self.assertEqual(
            standings,
            (Standing("alpha", 3, 1, 0, 0, 0, 0, 0, 10),),
        )


def ranked_standings(count: int) -> list[Standing]:
    return [
        Standing(
            f"team-{ordinal}",
            standing_points=100 - ordinal,
            series_wins=10,
            match_wins=20,
            match_losses=1,
            round_wins=200,
            round_losses=10,
            protocol_fault_forfeits=0,
            tie_break_key=ordinal,
        )
        for ordinal in range(1, count + 1)
    ]


class PlayoffTests(unittest.TestCase):
    def test_standard_bracket_seeds_one_four_and_two_three(self) -> None:
        bracket = create_playoff_bracket(ranked_standings(6))

        self.assertEqual(
            [(seed.seed, seed.team_id) for seed in bracket.seeds],
            [(1, "team-1"), (2, "team-2"), (3, "team-3"), (4, "team-4")],
        )
        self.assertEqual(
            bracket.semifinals,
            (
                PlayoffFixture(
                    PlayoffStage.SEMIFINAL, "team-1", "team-4"
                ),
                PlayoffFixture(
                    PlayoffStage.SEMIFINAL, "team-2", "team-3"
                ),
            ),
        )
        self.assertEqual(
            bracket.final,
            PlayoffFixture(PlayoffStage.FINAL, None, None),
        )

    def test_reduced_brackets_cover_every_eligible_team_count(self) -> None:
        three = create_playoff_bracket(ranked_standings(3))
        two = create_playoff_bracket(ranked_standings(2))
        one = create_playoff_bracket(ranked_standings(1))
        none = create_playoff_bracket([])

        self.assertEqual(
            three.semifinals,
            (
                PlayoffFixture(
                    PlayoffStage.SEMIFINAL, "team-2", "team-3"
                ),
            ),
        )
        self.assertEqual(
            three.final,
            PlayoffFixture(PlayoffStage.FINAL, "team-1", None),
        )
        self.assertEqual(two.semifinals, ())
        self.assertEqual(
            two.final,
            PlayoffFixture(PlayoffStage.FINAL, "team-1", "team-2"),
        )
        self.assertEqual(one.champion, "team-1")
        self.assertFalse(one.aborted)
        self.assertIsNone(none.champion)
        self.assertTrue(none.aborted)

    def test_pre_lock_disqualification_reselects_the_playoff_field(self) -> None:
        original = create_playoff_bracket(ranked_standings(5))

        recomputed = original.disqualify("team-2")

        self.assertFalse(recomputed.locked)
        self.assertEqual(
            [seed.team_id for seed in recomputed.seeds],
            ["team-1", "team-3", "team-4", "team-5"],
        )
        self.assertEqual(
            [seed.team_id for seed in original.seeds],
            ["team-1", "team-2", "team-3", "team-4"],
        )

    def test_post_lock_disqualification_awards_current_series_and_advances(self) -> None:
        bracket = create_playoff_bracket(ranked_standings(4))
        locked = bracket.start_semifinal(0)

        advanced = locked.disqualify("team-4")

        self.assertTrue(advanced.locked)
        self.assertEqual(advanced.semifinals[0].winner_id, "team-1")
        self.assertTrue(advanced.semifinals[0].administrative)
        self.assertEqual(advanced.final.team_a_id, "team-1")

    def test_disqualified_advancing_team_is_replaced_by_team_it_eliminated(self) -> None:
        bracket = create_playoff_bracket(ranked_standings(4))
        bracket = bracket.start_semifinal(0).complete_semifinal(0, "team-4")

        reinstated = bracket.disqualify("team-4")

        self.assertEqual(bracket.final.team_a_id, "team-4")
        self.assertEqual(reinstated.final.team_a_id, "team-1")
        self.assertEqual(reinstated.semifinals[0].winner_id, "team-4")

    def test_finalist_disqualification_after_final_starts_declares_champion(self) -> None:
        bracket = create_playoff_bracket(ranked_standings(2)).start_final()

        completed = bracket.disqualify("team-2")

        self.assertEqual(completed.champion, "team-1")
        self.assertEqual(completed.final.winner_id, "team-1")
        self.assertTrue(completed.final.administrative)
