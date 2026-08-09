from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from typing import Optional

from rps_runner import doctor_cli
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import load_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"
GIB = 1024**3


def digest(character: str) -> str:
    return "sha256:" + character * 64


class DoctorCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.store = self.directory / "artifact-store"
        self.store.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def docker_result(
        self, command: list[str], *, missing_images: Optional[set[str]] = None
    ) -> mock.Mock:
        missing_images = missing_images or set()
        if command == ["docker", "context", "show"]:
            return mock.Mock(returncode=0, stdout="orbstack\n", stderr="")
        if command == ["docker", "version", "--format", "{{json .}}"]:
            return mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "Server": {
                            "Platform": {"Name": "OrbStack"},
                            "Version": "27.3.1",
                            "ApiVersion": "1.47",
                            "MinAPIVersion": "1.24",
                            "Os": "linux",
                            "Arch": "arm64",
                        }
                    }
                ),
                stderr="",
            )
        if command == ["docker", "info", "--format", "{{json .}}"]:
            return mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "ID": "engine-123",
                        "OperatingSystem": "OrbStack",
                        "OSType": "linux",
                        "Architecture": "aarch64",
                        "NCPU": 16,
                        "MemTotal": 128 * GIB,
                        "DockerRootDir": "/var/lib/docker",
                        "Driver": "overlayfs",
                        "SecurityOptions": [
                            "name=seccomp,profile=builtin",
                            "name=cgroupns",
                        ],
                        "MemoryLimit": True,
                        # OrbStack on cgroup v2 reports the legacy CFS flag as
                        # false while enforcing Docker's modern CPU controls.
                        "CPUCfs": False,
                        "PidsLimit": True,
                        "CgroupVersion": "2",
                    }
                ),
                stderr="",
            )
        if command[:3] == ["docker", "image", "inspect"]:
            reference = command[3]
            if reference in missing_images:
                return mock.Mock(
                    returncode=1, stdout="", stderr="Error: No such image"
                )
            image_id = reference if reference.startswith("sha256:") else digest("f")
            return mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "Id": image_id,
                            "Os": "linux",
                            "Architecture": "arm64",
                            "RepoDigests": [reference],
                            "Size": 125_000_000,
                        }
                    ]
                ),
                stderr="",
            )
        self.fail("unexpected Docker command: " + repr(command))

    def arguments(self) -> list[str]:
        return [
            "--catalog",
            str(CATALOG),
            "--platform",
            "linux/arm64",
            "--artifact-store",
            str(self.store),
            "--organizer-image",
            digest("1"),
            "--practice-artifact",
            "fixed-move=" + digest("2"),
            "--parallelism",
            "4",
            "--minimum-free-disk-bytes",
            str(10 * GIB),
        ]

    @contextmanager
    def ready_environment(self, docker=None):
        docker_side_effect = docker or (
            lambda command, **_: self.docker_result(command)
        )
        with (
            mock.patch(
                "rps_runner.host_readiness.subprocess.run",
                side_effect=docker_side_effect,
            ),
            mock.patch(
                "rps_runner.host_readiness.verify_artifact_store",
                return_value={
                    "integrity": {
                        "index_identity": "artifact-set-index-v1@" + digest("a")
                    },
                    "artifacts": [{"platform": "linux/arm64"}],
                },
            ),
            mock.patch(
                "rps_runner.host_readiness.shutil.disk_usage",
                return_value=mock.Mock(
                    total=100 * GIB, used=20 * GIB, free=80 * GIB
                ),
            ),
        ):
            yield

    def test_ready_orbstack_report_uses_only_read_only_docker_commands(self) -> None:
        calls: list[list[str]] = []

        def docker(command: list[str], **_: object) -> mock.Mock:
            calls.append(command)
            return self.docker_result(command)

        with (
            mock.patch("rps_runner.host_readiness.subprocess.run", side_effect=docker),
            mock.patch(
                "rps_runner.host_readiness.verify_artifact_store",
                return_value={
                    "integrity": {"index_identity": "artifact-set-index-v1@" + digest("a")},
                    "artifacts": [{"platform": "linux/arm64"}],
                },
            ),
            mock.patch(
                "rps_runner.host_readiness.shutil.disk_usage",
                return_value=mock.Mock(total=100 * GIB, used=20 * GIB, free=80 * GIB),
            ),
            mock.patch("rps_runner.host_readiness.platform.node", return_value="m4-host"),
            mock.patch("rps_runner.host_readiness.platform.system", return_value="Darwin"),
            mock.patch("rps_runner.host_readiness.platform.release", return_value="25.0"),
            mock.patch("rps_runner.host_readiness.platform.machine", return_value="arm64"),
            mock.patch("rps_runner.host_readiness.os.cpu_count", return_value=16),
        ):
            report = doctor_cli.run(self.arguments())

        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["ready"])
        self.assertEqual(report["docker"]["context"], "orbstack")
        self.assertEqual(report["docker"]["server_platform"], "linux/arm64")
        self.assertEqual(report["docker"]["server_name"], "OrbStack")
        self.assertEqual(report["catalog"]["identity"], load_catalog(CATALOG).identity)
        self.assertEqual(report["profile"]["identity"], INITIAL_EXECUTION_PROFILE.identity)
        self.assertEqual(report["capacity"]["visible_cpus"], 16)
        self.assertEqual(report["capacity"]["requested_match_parallelism"], 4)
        self.assertEqual(report["artifact_store"]["status"], "passed")
        self.assertEqual(report["rehearsal"]["status"], "not_provided")
        self.assertEqual(
            {check["code"] for check in report["checks"] if check["status"] == "passed"},
            {
                "docker_connected",
                "active_context",
                "native_platform",
                "engine_features",
                "catalog_integrity",
                "base_images_present",
                "organizer_images_present",
                "practice_artifacts_present",
                "artifact_store_readable",
                "disk_available",
                "cpu_capacity",
                "profile_prerequisites",
            },
        )
        for command in calls:
            self.assertIn(
                command[:3],
                (
                    ["docker", "context", "show"],
                    ["docker", "version", "--format"],
                    ["docker", "info", "--format"],
                    ["docker", "image", "inspect"],
                ),
            )

    def test_reports_distinct_context_platform_image_disk_control_and_store_failures(
        self,
    ) -> None:
        missing = {digest("1"), digest("2")}

        def docker(command: list[str], **_: object) -> mock.Mock:
            result = self.docker_result(command, missing_images=missing)
            if command == ["docker", "context", "show"]:
                result.stdout = "desktop-linux\n"
            elif command == ["docker", "info", "--format", "{{json .}}"]:
                details = json.loads(result.stdout)
                details.update(
                    {
                        "Architecture": "x86_64",
                        "NCPU": 2,
                        "SecurityOptions": [],
                        "MemoryLimit": False,
                        "CPUCfs": False,
                        "PidsLimit": False,
                        "CgroupVersion": "1",
                    }
                )
                result.stdout = json.dumps(details)
            return result

        arguments = self.arguments() + ["--expected-context", "orbstack"]
        with (
            mock.patch("rps_runner.host_readiness.subprocess.run", side_effect=docker),
            mock.patch(
                "rps_runner.host_readiness.verify_artifact_store",
                side_effect=ValueError("artifact store index integrity mismatch"),
            ),
            mock.patch(
                "rps_runner.host_readiness.shutil.disk_usage",
                return_value=mock.Mock(total=20 * GIB, used=19 * GIB, free=GIB),
            ),
        ):
            report = doctor_cli.run(arguments)

        self.assertEqual(report["status"], "not_ready")
        failures = {
            check["code"]: check["detail"]
            for check in report["checks"]
            if check["status"] == "failed"
        }
        self.assertIn("wrong_context", failures)
        self.assertIn("wrong_platform", failures)
        self.assertIn("missing_organizer_images", failures)
        self.assertIn("missing_practice_artifacts", failures)
        self.assertIn("insufficient_disk", failures)
        self.assertIn("unsupported_controls", failures)
        self.assertIn("parallelism_impossible", failures)
        self.assertIn("corrupt_artifact_store", failures)
        self.assertFalse(report["docker"]["features"]["cpu_limit"])

    def test_unavailable_docker_still_reports_catalog_and_store_diagnostics(self) -> None:
        def unavailable(command: list[str], **_: object) -> mock.Mock:
            if command == ["docker", "context", "show"]:
                raise FileNotFoundError("docker")
            self.fail("Docker probing continued after connectivity failure")

        with (
            mock.patch(
                "rps_runner.host_readiness.subprocess.run", side_effect=unavailable
            ),
            mock.patch(
                "rps_runner.host_readiness.verify_artifact_store",
                side_effect=ValueError("image archive digest mismatch"),
            ),
            mock.patch(
                "rps_runner.host_readiness.shutil.disk_usage",
                return_value=mock.Mock(total=100 * GIB, used=20 * GIB, free=80 * GIB),
            ),
        ):
            report = doctor_cli.run(self.arguments())

        failures = {check["code"] for check in report["checks"] if check["status"] == "failed"}
        self.assertIn("docker_unavailable", failures)
        self.assertIn("corrupt_artifact_store", failures)
        self.assertEqual(report["catalog"]["status"], "passed")

    def test_matching_and_stale_rehearsal_evidence_are_machine_readable(self) -> None:
        # First obtain the exact current identity values that evidence must bind.
        with self.ready_environment():
            current = doctor_cli.run(self.arguments())

        evidence = {
            "rehearsal_report_format_version": "rps-rehearsal-report-v1",
            "status": "passed",
            "machine_identity": current["machine"]["identity"],
            "engine_identity": current["docker"]["engine_identity"],
            "docker_context": "orbstack",
            "catalog_identity": current["catalog"]["identity"],
            "profile_identity": current["profile"]["identity"],
            "platform": "linux/arm64",
            "parallelism": 4,
        }
        evidence_path = self.directory / "rehearsal.json"
        evidence_path.write_text(json.dumps(evidence))
        arguments = self.arguments() + ["--rehearsal-evidence", str(evidence_path)]

        with self.ready_environment():
            matching = doctor_cli.run(arguments)
        self.assertEqual(matching["rehearsal"]["status"], "matched")

        evidence["parallelism"] = 8
        evidence_path.write_text(json.dumps(evidence))
        with self.ready_environment():
            stale = doctor_cli.run(arguments)
        self.assertEqual(stale["rehearsal"]["status"], "mismatched")
        self.assertEqual(stale["rehearsal"]["mismatches"], ["parallelism"])

    def test_cached_image_requirements_must_be_immutable(self) -> None:
        arguments = self.arguments()
        arguments[arguments.index(digest("1"))] = "organizer:latest"

        with self.assertRaisesRegex(ValueError, "immutable sha256"):
            doctor_cli.run(arguments)

    def test_image_platform_and_digest_failures_have_stable_reason_codes(self) -> None:
        organizer = digest("1")
        practice = digest("2")

        def docker(command: list[str], **_: object) -> mock.Mock:
            result = self.docker_result(command)
            if command == ["docker", "image", "inspect", organizer]:
                image = json.loads(result.stdout)
                image[0]["Architecture"] = "amd64"
                result.stdout = json.dumps(image)
            elif command == ["docker", "image", "inspect", practice]:
                image = json.loads(result.stdout)
                image[0]["Id"] = digest("9")
                image[0]["RepoDigests"] = []
                result.stdout = json.dumps(image)
            return result

        with (
            mock.patch("rps_runner.host_readiness.subprocess.run", side_effect=docker),
            mock.patch(
                "rps_runner.host_readiness.verify_artifact_store",
                return_value={
                    "integrity": {
                        "index_identity": "artifact-set-index-v1@" + digest("a")
                    },
                    "artifacts": [{"platform": "linux/arm64"}],
                },
            ),
            mock.patch(
                "rps_runner.host_readiness.shutil.disk_usage",
                return_value=mock.Mock(
                    total=100 * GIB, used=20 * GIB, free=80 * GIB
                ),
            ),
        ):
            report = doctor_cli.run(self.arguments())

        failures = {
            check["code"] for check in report["checks"] if check["status"] == "failed"
        }
        self.assertIn("wrong_platform_images", failures)
        self.assertIn("image_digest_mismatch", failures)
        self.assertEqual(
            report["images"]["organizer"]["problems"][0]["reason"],
            "wrong_platform",
        )
        self.assertEqual(
            report["images"]["practice"]["problems"][0]["reason"],
            "digest_mismatch",
        )

    def test_late_docker_failure_remains_a_machine_readable_diagnostic(self) -> None:
        organizer = digest("1")

        def docker(command: list[str], **_: object) -> mock.Mock:
            if command == ["docker", "image", "inspect", organizer]:
                raise TimeoutError("Docker disappeared during inspection")
            return self.docker_result(command)

        with self.ready_environment(docker):
            report = doctor_cli.run(self.arguments())

        failures = {
            check["code"] for check in report["checks"] if check["status"] == "failed"
        }
        self.assertIn("image_inspection_failed", failures)
        self.assertEqual(
            report["images"]["organizer"]["problems"][0]["reason"],
            "inspection_failed",
        )


if __name__ == "__main__":
    unittest.main()
