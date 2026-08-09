from __future__ import annotations

import json
from pathlib import Path
import subprocess
from unittest import mock
import unittest

from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.profile_probe import ProfileProbeFailure, measure_python_runtime


CATALOG = (
    Path(__file__).resolve().parents[1]
    / "language_environments"
    / "catalog-v1"
    / "catalog.json"
)


class ExecutionProfileTests(unittest.TestCase):
    def test_published_initial_profile_has_one_symmetric_outer_ceiling(self) -> None:
        profile = INITIAL_EXECUTION_PROFILE

        self.assertEqual(profile.version, "docker-execution-v1")
        self.assertEqual(profile.cpu_quota_millis_per_second, 1_000)
        self.assertEqual(profile.cpu_limit_ms, 2_000)
        self.assertEqual(profile.memory_limit_bytes, 268_435_456)
        self.assertEqual(profile.process_limit, 64)
        self.assertEqual(profile.open_file_limit, 64)
        self.assertEqual(profile.filesystem_write_limit_bytes, 16_777_216)
        self.assertEqual(profile.stdout_limit_bytes, 4_096)
        self.assertEqual(profile.stderr_limit_bytes, 65_536)
        self.assertEqual(profile.startup_timeout_seconds, 10.0)
        self.assertEqual(profile.shutdown_timeout_seconds, 3.0)
        self.assertEqual(profile.recommended_match_parallelism, 4)
        self.assertRegex(profile.identity, r"^docker-execution-v1@sha256:[0-9a-f]{64}$")

    @mock.patch("rps_runner.profile_probe.subprocess.run")
    def test_probe_measures_the_pinned_native_runtime_under_the_profile(
        self, run: mock.Mock
    ) -> None:
        runtime = json.loads((CATALOG.parent / "python" / "runtimes.json").read_text())
        reference = runtime["platforms"]["linux/arm64"]["image"]
        run.side_effect = [
            subprocess.CompletedProcess(
                ["docker", "info"], 0, stdout="linux/aarch64\n", stderr=""
            ),
            subprocess.CompletedProcess(
                ["docker", "image", "inspect"],
                0,
                stdout=json.dumps(
                    [
                        {
                            "Id": reference.split("@", 1)[1],
                            "Os": "linux",
                            "Architecture": "arm64",
                        }
                    ]
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                ["docker", "run"],
                0,
                stdout="",
                stderr="",
            ),
            subprocess.CompletedProcess(
                ["docker", "run"],
                0,
                stdout=json.dumps(
                    {
                        "python_version": "3.13.14",
                        "peak_rss_bytes": 12_000_000,
                        "cpu_probe_ms": 15.5,
                        "peak_threads": 9,
                        "peak_open_files": 36,
                        "temporary_filesystem_bytes": 1_048_576,
                    }
                )
                + "\n",
                stderr="",
            ),
        ]

        report = measure_python_runtime(CATALOG, "linux/arm64")

        self.assertTrue(report["native_execution"])
        self.assertEqual(report["platform"], "linux/arm64")
        self.assertEqual(report["runtime_reference"], reference)
        self.assertEqual(report["profile_identity"], INITIAL_EXECUTION_PROFILE.identity)
        self.assertGreaterEqual(report["measurements"]["startup_ms"], 0)
        command = run.call_args_list[3].args[0]
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertEqual(command[command.index("--platform") + 1], "linux/arm64")
        self.assertEqual(command[command.index("--cpus") + 1], "1")
        self.assertEqual(command[-3:-1], ["python3", "-c"])

    @mock.patch("rps_runner.profile_probe.subprocess.run")
    def test_probe_rejects_cross_architecture_emulation(self, run: mock.Mock) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["docker", "info"], 0, stdout="linux/amd64\n", stderr=""
        )

        with self.assertRaisesRegex(ProfileProbeFailure, "native linux/arm64"):
            measure_python_runtime(CATALOG, "linux/arm64")

        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
