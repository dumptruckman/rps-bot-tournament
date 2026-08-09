from __future__ import annotations

import math
import unittest

from rps_runner.tournament.execution_inputs import TournamentExecutionInputs


class TournamentExecutionInputsTests(unittest.TestCase):
    def test_copies_and_freezes_the_platform_mapping(self) -> None:
        platforms = {"sha256:" + "a" * 64: "linux/arm64"}

        inputs = TournamentExecutionInputs(platforms, 10.0, 3.0)
        platforms["sha256:" + "a" * 64] = "linux/amd64"

        self.assertEqual(
            inputs.platform_by_digest["sha256:" + "a" * 64],
            "linux/arm64",
        )
        with self.assertRaises(TypeError):
            inputs.platform_by_digest[
                "sha256:" + "b" * 64
            ] = "linux/arm64"  # type: ignore[index]

    def test_rejects_invalid_platform_mappings_and_timeouts(self) -> None:
        valid = {"sha256:" + "a" * 64: "linux/arm64"}
        invalid_cases = (
            ({}, 10.0, 3.0),
            ({"not-a-digest": "linux/arm64"}, 10.0, 3.0),
            ({"sha256:" + "a" * 64: "linux/amd64"}, 10.0, 3.0),
            (valid, 0, 3.0),
            (valid, 10.0, math.inf),
            (valid, True, 3.0),
        )

        for platforms, startup, shutdown in invalid_cases:
            with self.subTest(
                platforms=platforms, startup=startup, shutdown=shutdown
            ):
                with self.assertRaises(ValueError):
                    TournamentExecutionInputs(platforms, startup, shutdown)


if __name__ == "__main__":
    unittest.main()
