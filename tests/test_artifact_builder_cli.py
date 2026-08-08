from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"
ARTIFACT_DIGEST = "sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "b" * 64


class ArtifactBuilderCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.fake_bin = self.directory / "bin"
        self.fake_bin.mkdir()
        self.bundle_count = 0
        self.docker_log = self.directory / "docker.jsonl"
        docker = self.fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "with open(os.environ['FAKE_DOCKER_LOG'], 'a') as stream:\n"
            "    stream.write(json.dumps(args) + '\\n')\n"
            "mode = os.environ.get('FAKE_DOCKER_MODE', 'success')\n"
            "runtime_digest = os.environ['FAKE_RUNTIME_DIGEST']\n"
            "if args[:2] == ['image', 'inspect']:\n"
            "    target = args[2]\n"
            "    if '@sha256:' in target:\n"
            "        print(json.dumps([{'Id': 'sha256:' + 'c' * 64, "
            "'RepoDigests': [target], 'Os': 'linux', 'Architecture': 'amd64'}]))\n"
            "    else:\n"
            "        architecture = 'arm64' if mode == 'wrong-platform' else 'amd64'\n"
            "        image_id = 'sha256:' + ('d' if mode == 'wrong-image' else 'b') * 64\n"
            "        print(json.dumps([{'Id': image_id, 'RepoDigests': [], "
            "'Os': 'linux', 'Architecture': architecture, "
            "'Config': {'Entrypoint': ['python3', '-I', '/opt/rps/wrapper.py']}}]))\n"
            "elif args and args[0] == 'build':\n"
            "    if mode == 'docker-failure':\n"
            "        print('Docker daemon rejected the build')\n"
            "        raise SystemExit(17)\n"
            "    if mode == 'overflow':\n"
            "        print('x' * 10000)\n"
            "        raise SystemExit(0)\n"
            "    if mode == 'timeout':\n"
            "        import time; time.sleep(2)\n"
            "    iid = pathlib.Path(args[args.index('--iidfile') + 1])\n"
            "    metadata = pathlib.Path(args[args.index('--metadata-file') + 1])\n"
            "    iid.write_text('sha256:' + 'b' * 64 + '\\n')\n"
            "    metadata.write_text(json.dumps({'containerimage.digest': 'sha256:' + 'a' * 64}))\n"
            "    print('build completed')\n"
            "else:\n"
            "    print('unexpected fake Docker invocation', file=sys.stderr)\n"
            "    raise SystemExit(64)\n"
        )
        docker.chmod(docker.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_bundle(self) -> Path:
        self.bundle_count += 1
        suffix = str(self.bundle_count)
        source = self.directory / ("team-source-" + suffix)
        source.mkdir()
        (source / "strategy.py").write_text(
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return 'R'\n"
        )
        bundle = self.directory / ("source-bundle-" + suffix)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.source_cli",
                "--catalog",
                str(CATALOG),
                "--environment",
                "python",
                "--source",
                str(source),
                "--bundle",
                str(bundle),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return bundle

    def run_builder(
        self,
        bundle: Path,
        candidate: Path,
        *,
        mode: str = "success",
        timeout: str = "5",
        maximum_output: str = "65536",
    ) -> subprocess.CompletedProcess[str]:
        runtime_data = json.loads(
            (CATALOG.parent / "python" / "runtimes.json").read_text()
        )
        runtime_digest = runtime_data["platforms"]["linux/amd64"]["image"].split(
            "@", 1
        )[1]
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.fake_bin) + os.pathsep + environment["PATH"],
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_DOCKER_MODE": mode,
                "FAKE_RUNTIME_DIGEST": runtime_digest,
            }
        )
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.artifact_cli",
                "--catalog",
                str(CATALOG),
                "--bundle",
                str(bundle),
                "--platform",
                "linux/amd64",
                "--candidate",
                str(candidate),
                "--timeout-seconds",
                timeout,
                "--max-diagnostics-bytes",
                maximum_output,
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def result(self, completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def docker_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.docker_log.read_text().splitlines()]

    def test_builds_one_networkless_platform_candidate_from_separate_inputs(self) -> None:
        bundle = self.make_bundle()
        candidate = self.directory / "candidate"

        result = self.result(self.run_builder(bundle, candidate))

        source_manifest = json.loads((bundle / "source-bundle.json").read_text())
        self.assertEqual(result["status"], "suite-candidate")
        self.assertEqual(result["source_digest"], source_manifest["source_digest"])
        self.assertEqual(result["artifact_digest"], ARTIFACT_DIGEST)
        self.assertRegex(result["build_identity"], r"^build-v1@sha256:[0-9a-f]{64}$")
        self.assertEqual(result["runtime_digest"], result["runtime"]["digest"])
        self.assertEqual(result["language"], "python")
        self.assertEqual(result["platform"], "linux/amd64")
        self.assertEqual(
            set(result["identities"]),
            {
                "catalog",
                "core_tool",
                "entrypoint",
                "language_environment",
                "platform",
                "recipe",
                "suite_candidate",
                "wrapper",
            },
        )
        for identity in result["identities"].values():
            self.assertRegex(identity, r"^[^@]+@sha256:[0-9a-f]{64}$")
        self.assertEqual(
            json.loads((candidate / "artifact-candidate.json").read_text()), result
        )
        self.assertEqual(
            (candidate / "source" / "strategy.py").read_bytes(),
            (bundle / "source" / "strategy.py").read_bytes(),
        )
        self.assertEqual((candidate / "build.log").read_text(), "build completed\n")
        self.assertFalse(candidate.stat().st_mode & stat.S_IWUSR)

        build = next(call for call in self.docker_calls() if call[0] == "build")
        self.assertIn("--network=none", build)
        self.assertIn("--pull=false", build)
        self.assertEqual(build[build.index("--platform") + 1], "linux/amd64")
        runtime_argument = build[build.index("--build-arg") + 1]
        self.assertRegex(runtime_argument, r"^RPS_BASE_RUNTIME=.+@sha256:[0-9a-f]{64}$")
        team_context = build[build.index("--build-context") + 1]
        self.assertTrue(team_context.startswith("team="))
        team_path = Path(team_context.split("=", 1)[1])
        self.assertEqual(team_path.name, "team-context")
        self.assertNotEqual(team_path, bundle / "source")
        organizer_context = Path(build[-1])
        self.assertNotEqual(team_path, organizer_context)
        self.assertNotEqual(organizer_context, bundle / "source")
        self.assertNotIn(str(bundle / "source"), build[-1])
        recipe = Path(build[build.index("--file") + 1])
        self.assertEqual(recipe.parent, organizer_context)
        self.assertEqual(recipe.name, "Dockerfile")

    def test_rejects_a_frozen_bundle_when_source_bytes_have_changed(self) -> None:
        bundle = self.make_bundle()
        strategy = bundle / "source" / "strategy.py"
        strategy.chmod(0o644)
        strategy.write_text("def choose_move(a, b, c, d):\n    return 'P'\n")

        completed = self.run_builder(bundle, self.directory / "candidate")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("source digest does not match", completed.stderr)
        self.assertIn("non-competitive build failure", completed.stderr)
        self.assertFalse((self.directory / "candidate").exists())

    def test_wrong_platform_and_unexpected_image_identity_are_actionable(self) -> None:
        for mode, expected in (
            ("wrong-platform", "wrong platform"),
            ("wrong-image", "image identity does not match"),
        ):
            with self.subTest(mode=mode):
                bundle = self.make_bundle()
                candidate = self.directory / ("candidate-" + mode)

                completed = self.run_builder(bundle, candidate, mode=mode)

                self.assertEqual(completed.returncode, 2)
                self.assertIn(expected, completed.stderr)
                self.assertFalse(candidate.exists())

    def test_timeout_output_overflow_and_docker_failure_are_bounded_failures(self) -> None:
        cases = (
            ("timeout", "0.05", "65536", "timed out"),
            ("overflow", "5", "100", "output exceeded"),
            ("docker-failure", "5", "65536", "Docker build failed with exit code 17"),
        )
        for mode, timeout, maximum_output, expected in cases:
            with self.subTest(mode=mode):
                bundle = self.make_bundle()
                candidate = self.directory / ("candidate-" + mode)

                completed = self.run_builder(
                    bundle,
                    candidate,
                    mode=mode,
                    timeout=timeout,
                    maximum_output=maximum_output,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn(expected, completed.stderr)
                self.assertLess(len(completed.stderr), 1000)
                self.assertFalse(candidate.exists())

    def test_rejects_unsupported_platform_before_building(self) -> None:
        bundle = self.make_bundle()
        candidate = self.directory / "candidate"
        runtime_data = json.loads(
            (CATALOG.parent / "python" / "runtimes.json").read_text()
        )
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(self.fake_bin) + os.pathsep + environment["PATH"],
                "FAKE_DOCKER_LOG": str(self.docker_log),
                "FAKE_DOCKER_MODE": "success",
                "FAKE_RUNTIME_DIGEST": runtime_data["platforms"]["linux/amd64"][
                    "image"
                ].split("@", 1)[1],
            }
        )

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.artifact_cli",
                "--catalog",
                str(CATALOG),
                "--bundle",
                str(bundle),
                "--platform",
                "linux/ppc64le",
                "--candidate",
                str(candidate),
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("target platform 'linux/ppc64le' is unsupported", completed.stderr)
        self.assertFalse(self.docker_log.exists())

    def test_existing_candidate_is_not_replaced(self) -> None:
        bundle = self.make_bundle()
        candidate = self.directory / "candidate"
        candidate.mkdir()
        marker = candidate / "keep.txt"
        marker.write_text("keep")

        completed = self.run_builder(bundle, candidate)

        self.assertEqual(completed.returncode, 2)
        self.assertIn("candidate destination already exists", completed.stderr)
        self.assertEqual(marker.read_text(), "keep")
        self.assertFalse(self.docker_log.exists())

    def test_public_operational_limits_remain_bounded(self) -> None:
        for timeout, maximum_output, expected in (
            ("inf", "65536", "build timeout must be finite"),
            ("5", "1048577", "diagnostics limit must be positive"),
        ):
            with self.subTest(timeout=timeout, maximum_output=maximum_output):
                bundle = self.make_bundle()
                completed = self.run_builder(
                    bundle,
                    self.directory / ("candidate-limits-" + str(self.bundle_count)),
                    timeout=timeout,
                    maximum_output=maximum_output,
                )

                self.assertEqual(completed.returncode, 2)
                self.assertIn(expected, completed.stderr)
                self.assertFalse(self.docker_log.exists())


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class ArtifactBuilderDockerIntegrationTests(unittest.TestCase):
    def test_public_cli_builds_and_retains_a_real_linux_amd64_image(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            directory = Path(temporary_name)
            source = directory / "source"
            source.mkdir()
            (source / "strategy.py").write_text(
                "def choose_move(turn, my_history, opponent_history, rng):\n"
                "    return 'R'\n"
            )
            bundle = directory / "bundle"
            validation = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rps_runner.source_cli",
                    "--catalog",
                    str(CATALOG),
                    "--environment",
                    "python",
                    "--source",
                    str(source),
                    "--bundle",
                    str(bundle),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(validation.returncode, 0, validation.stderr)
            candidate = directory / "candidate"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "rps_runner.artifact_cli",
                    "--catalog",
                    str(CATALOG),
                    "--bundle",
                    str(bundle),
                    "--platform",
                    "linux/amd64",
                    "--candidate",
                    str(candidate),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            try:
                inspection = subprocess.run(
                    [
                        "docker",
                        "image",
                        "inspect",
                        result["retention"]["local_image_id"],
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(inspection.returncode, 0, inspection.stderr)
                self.assertEqual(result["platform"], "linux/amd64")
                self.assertRegex(result["artifact_digest"], r"^sha256:[0-9a-f]{64}$")
            finally:
                subprocess.run(
                    [
                        "docker",
                        "image",
                        "rm",
                        result["retention"]["local_image_reference"],
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )


if __name__ == "__main__":
    unittest.main()
