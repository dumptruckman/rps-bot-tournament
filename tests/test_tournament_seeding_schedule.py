from __future__ import annotations

from itertools import combinations
import unittest

from rps_runner.tournament.schedule import (
    BotPositions,
    Fixture,
    FixtureBatch,
    build_qualifying_schedule,
    bot_positions,
    shuffle_team_ids,
)
from rps_runner.tournament.seeding import (
    derive_bot_seed,
    derive_fixture_seed,
    derive_match_seed,
    derive_position_value,
    derive_schedule_value,
    derive_tiebreak_key,
    derive_u64,
)


class SeedDerivationTests(unittest.TestCase):
    def test_version_one_matches_independent_golden_vectors(self) -> None:
        vectors = (
            (0, "fixture-seed", "qualifying-0001", 3006357440780989151),
            (
                18446744073709551615,
                "fixture-seed",
                "qualifying-0496",
                14317227228373711062,
            ),
            (
                0x0102030405060708,
                "bot-visible-seed",
                "東京/ß",
                7012202496826276551,
            ),
        )

        for parent_seed, child_type, identifier, expected in vectors:
            with self.subTest(
                parent_seed=parent_seed,
                child_type=child_type,
                identifier=identifier,
            ):
                self.assertEqual(
                    derive_u64(parent_seed, child_type, identifier), expected
                )

    def test_seed_hierarchy_and_domains_match_golden_values(self) -> None:
        fixture_seed = derive_fixture_seed(123456789, "qualifying-0001")
        match_seed = derive_match_seed(fixture_seed, 1)

        self.assertEqual(fixture_seed, 12353042038433105865)
        self.assertEqual(match_seed, 4868274571950258215)
        self.assertEqual(
            derive_bot_seed(match_seed, "alpha"), 2374326309173501126
        )
        self.assertEqual(
            derive_schedule_value(123456789, "alpha"), 7971735128055229538
        )
        self.assertEqual(
            derive_position_value(fixture_seed, 1), 14689783219451139572
        )
        self.assertEqual(
            derive_tiebreak_key(123456789, "alpha"), 10397659462510387600
        )

    def test_typed_derivations_enforce_best_of_three_ordinals(self) -> None:
        for match_ordinal in (0, 4):
            with self.subTest(match_ordinal=match_ordinal):
                with self.assertRaisesRegex(ValueError, "between 1 and 3"):
                    derive_match_seed(0, match_ordinal)
        with self.assertRaisesRegex(ValueError, "1 or 3"):
            derive_position_value(0, 2)


class QualifyingScheduleTests(unittest.TestCase):
    def test_team_ids_are_sorted_then_deterministically_shuffled(self) -> None:
        self.assertEqual(
            shuffle_team_ids(
                ("delta", "alpha", "gamma", "beta"), 123456789
            ),
            ("beta", "gamma", "alpha", "delta"),
        )

    def test_four_team_circle_schedule_has_stable_fixture_identity_and_order(
        self,
    ) -> None:
        schedule = build_qualifying_schedule(
            ("delta", "alpha", "gamma", "beta"), 123456789
        )

        self.assertEqual(
            schedule,
            (
                FixtureBatch(
                    ordinal=1,
                    fixtures=(
                        Fixture(
                            fixture_id="qualifying-0001",
                            ordinal=1,
                            batch_ordinal=1,
                            team_ids=("beta", "delta"),
                            fixture_seed=12353042038433105865,
                        ),
                        Fixture(
                            fixture_id="qualifying-0002",
                            ordinal=2,
                            batch_ordinal=1,
                            team_ids=("gamma", "alpha"),
                            fixture_seed=17725675378203971453,
                        ),
                    ),
                    bye_team_id=None,
                ),
                FixtureBatch(
                    ordinal=2,
                    fixtures=(
                        Fixture(
                            fixture_id="qualifying-0003",
                            ordinal=3,
                            batch_ordinal=2,
                            team_ids=("beta", "alpha"),
                            fixture_seed=7075214817761632351,
                        ),
                        Fixture(
                            fixture_id="qualifying-0004",
                            ordinal=4,
                            batch_ordinal=2,
                            team_ids=("delta", "gamma"),
                            fixture_seed=7683105400918925558,
                        ),
                    ),
                    bye_team_id=None,
                ),
                FixtureBatch(
                    ordinal=3,
                    fixtures=(
                        Fixture(
                            fixture_id="qualifying-0005",
                            ordinal=5,
                            batch_ordinal=3,
                            team_ids=("beta", "gamma"),
                            fixture_seed=11449081545130815592,
                        ),
                        Fixture(
                            fixture_id="qualifying-0006",
                            ordinal=6,
                            batch_ordinal=3,
                            team_ids=("alpha", "delta"),
                            fixture_seed=230110480220486133,
                        ),
                    ),
                    bye_team_id=None,
                ),
            ),
        )

    def test_supported_rosters_are_complete_batched_round_robins(self) -> None:
        for team_count in range(4, 33):
            team_ids = tuple(
                f"team-{ordinal:02d}" for ordinal in range(team_count)
            )

            schedule = build_qualifying_schedule(team_ids, 987654321)
            fixtures = tuple(
                fixture for batch in schedule for fixture in batch.fixtures
            )

            with self.subTest(team_count=team_count):
                self.assertEqual(
                    len(schedule),
                    team_count - 1 if team_count % 2 == 0 else team_count,
                )
                self.assertEqual(
                    len(fixtures), team_count * (team_count - 1) // 2
                )
                self.assertEqual(
                    {frozenset(fixture.team_ids) for fixture in fixtures},
                    {
                        frozenset(pair)
                        for pair in combinations(team_ids, 2)
                    },
                )
                self.assertEqual(
                    tuple(fixture.ordinal for fixture in fixtures),
                    tuple(range(1, len(fixtures) + 1)),
                )
                for batch in schedule:
                    active_team_ids = tuple(
                        team_id
                        for fixture in batch.fixtures
                        for team_id in fixture.team_ids
                    )
                    self.assertEqual(
                        len(active_team_ids), len(set(active_team_ids))
                    )
                    if team_count % 2:
                        self.assertIsNotNone(batch.bye_team_id)
                        self.assertNotIn(batch.bye_team_id, active_team_ids)
                    else:
                        self.assertIsNone(batch.bye_team_id)
                if team_count % 2:
                    self.assertEqual(
                        {batch.bye_team_id for batch in schedule},
                        set(team_ids),
                    )

    def test_schedule_rejects_rosters_outside_four_to_thirty_two_or_duplicates(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "between 4 and 32"):
            build_qualifying_schedule(("one", "two", "three"), 0)
        with self.assertRaisesRegex(ValueError, "between 4 and 32"):
            build_qualifying_schedule(
                tuple(f"team-{ordinal}" for ordinal in range(33)), 0
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            build_qualifying_schedule(("one", "two", "three", "three"), 0)

    def test_five_team_circle_schedule_assigns_each_team_one_bye(self) -> None:
        schedule = build_qualifying_schedule(
            ("epsilon", "delta", "alpha", "gamma", "beta"), 123456789
        )

        self.assertEqual(
            tuple(batch.bye_team_id for batch in schedule),
            ("beta", "delta", "gamma", "epsilon", "alpha"),
        )
        self.assertEqual(
            tuple(
                tuple(fixture.team_ids for fixture in batch.fixtures)
                for batch in schedule
            ),
            (
                (("gamma", "epsilon"), ("alpha", "delta")),
                (("beta", "epsilon"), ("gamma", "alpha")),
                (("beta", "delta"), ("epsilon", "alpha")),
                (("beta", "alpha"), ("delta", "gamma")),
                (("beta", "gamma"), ("delta", "epsilon")),
            ),
        )
        self.assertEqual(
            tuple(
                fixture.fixture_id
                for batch in schedule
                for fixture in batch.fixtures
            ),
            (
                "qualifying-0001",
                "qualifying-0002",
                "qualifying-0003",
                "qualifying-0004",
                "qualifying-0005",
                "qualifying-0006",
                "qualifying-0007",
                "qualifying-0008",
                "qualifying-0009",
                "qualifying-0010",
            ),
        )


class BotPositionTests(unittest.TestCase):
    def test_match_two_swaps_and_match_three_is_independently_derived(
        self,
    ) -> None:
        self.assertEqual(
            derive_position_value(0, 1), 11635458936656502452
        )
        self.assertEqual(
            derive_position_value(0, 3), 10551199532690348431
        )
        self.assertEqual(
            bot_positions(0, 1, "alpha", "beta"),
            BotPositions(team_a_id="alpha", team_b_id="beta"),
        )
        self.assertEqual(
            bot_positions(0, 2, "alpha", "beta"),
            BotPositions(team_a_id="beta", team_b_id="alpha"),
        )
        self.assertEqual(
            bot_positions(0, 3, "alpha", "beta"),
            BotPositions(team_a_id="beta", team_b_id="alpha"),
        )

    def test_position_assignment_rejects_invalid_match_ordinals(self) -> None:
        for match_ordinal in (0, 4):
            with self.subTest(match_ordinal=match_ordinal):
                with self.assertRaisesRegex(ValueError, "between 1 and 3"):
                    bot_positions(0, match_ordinal, "alpha", "beta")


if __name__ == "__main__":
    unittest.main()
