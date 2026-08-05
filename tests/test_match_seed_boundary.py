from __future__ import annotations

import gc
import os
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch
import warnings

from rps_runner.engine import MatchConfig, run_match


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHECKS_PROTOCOL = PROJECT_ROOT / "tests" / "fixtures" / "bots" / "checks_protocol.py"


def checking_bot(move: str, rounds: int, expected_seed: int) -> str:
    return shlex.join(
        [
            sys.executable,
            str(CHECKS_PROTOCOL),
            move,
            "1",
            str(rounds),
            str(expected_seed),
        ]
    )


def isolated_environment_bot(move: str, expected_seed: int) -> str:
    script = (
        "import os,sys;"
        "[sys.stdin.readline() for _ in range(3)];"
        "keys={key for key in os.environ if key.startswith('RPS_')};"
        "expected={'RPS_PROTOCOL_VERSION','RPS_ROUNDS','RPS_SEED'};"
        "valid=os.environ.get('RPS_SEED')==sys.argv[1] and keys==expected;"
        "print(sys.argv[2] if valid else 'invalid',flush=True)"
    )
    return shlex.join([sys.executable, "-c", script, str(expected_seed), move])


class MatchSeedBoundaryTests(unittest.TestCase):
    def test_match_closes_bot_process_streams(self) -> None:
        match_seed = 12345
        config = MatchConfig(
            bot_a=checking_bot("R", 1, match_seed),
            bot_b=checking_bot("S", 1, match_seed),
            rounds=1,
            seed=match_seed,
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            result = run_match(config)
            gc.collect()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            [warning for warning in caught if warning.category is ResourceWarning],
            [],
        )

    def test_each_bot_receives_its_own_seed_while_result_keeps_match_seed(self) -> None:
        match_seed = 998877
        bot_a_seed = 0
        bot_b_seed = 2**64 - 1
        config = MatchConfig(
            bot_a=checking_bot("R", 1, bot_a_seed),
            bot_b=checking_bot("S", 1, bot_b_seed),
            rounds=1,
            seed=match_seed,
            bot_a_seed=bot_a_seed,
            bot_b_seed=bot_b_seed,
        )

        result = run_match(config)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["seed"], match_seed)

    def test_legacy_match_seed_remains_both_bots_visible_seed(self) -> None:
        match_seed = 12345
        config = MatchConfig(
            bot_a=checking_bot("R", 1, match_seed),
            bot_b=checking_bot("S", 1, match_seed),
            rounds=1,
            seed=match_seed,
        )

        result = run_match(config)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")
        self.assertEqual(result["seed"], match_seed)

    def test_match_and_bot_visible_seeds_must_be_unsigned_64_bit_values(self) -> None:
        cases = (
            ("seed", -1),
            ("bot_a_seed", -1),
            ("bot_b_seed", 2**64),
        )

        for field, invalid_seed in cases:
            with self.subTest(field=field, invalid_seed=invalid_seed):
                arguments = {
                    "bot_a": "bot-a",
                    "bot_b": "bot-b",
                    "rounds": 1,
                    "seed": 9,
                    field: invalid_seed,
                }
                with self.assertRaisesRegex(ValueError, field):
                    MatchConfig(**arguments)

    def test_runner_exposes_no_other_rps_identity_or_seed_variables(self) -> None:
        config = MatchConfig(
            bot_a=isolated_environment_bot("R", 101),
            bot_b=isolated_environment_bot("S", 202),
            rounds=1,
            seed=303,
            bot_a_seed=101,
            bot_b_seed=202,
        )

        with patch.dict(
            os.environ,
            {
                "RPS_OPPONENT_SEED": "must-not-leak",
                "RPS_OPPONENT_TEAM_ID": "must-not-leak",
            },
        ):
            result = run_match(config)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["winner"], "a")


if __name__ == "__main__":
    unittest.main()
