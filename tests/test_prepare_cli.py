from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rps_runner import prepare_cli
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.language_environment import load_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


def digest(character: str) -> str:
    return "sha256:" + character * 64


class PrepareCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.store = self.directory / "artifact-store"
        self.report = self.directory / "readiness.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def arguments(self) -> list[str]:
        return [
            "--catalog",
            str(CATALOG),
            "--environment",
            "python",
            "--platform",
            "linux/arm64",
            "--profile",
            "docker-execution-v1",
            "--artifact-store",
            str(self.store),
            "--report",
            str(self.report),
            "--parallelism",
            "4",
        ]

    def prepared(self) -> dict[str, object]:
        return {
            "organizer_images": [digest("1")],
            "practice_artifacts": {
                "copycat": digest("2"),
                "fixed-move": digest("3"),
                "protocol-test": digest("4"),
                "random": digest("5"),
            },
            "artifact_digest": digest("6"),
            "artifact_image_id": digest("1"),
            "validation_identity": "validation-report-v1@" + digest("7"),
            "offline_checks": {
                "networkless_rebuild": "passed",
                "readiness_handshake": "passed",
                "isolation_profile": "passed",
                "artifact_archive": "passed",
                "artifact_restore": "passed",
            },
            "artifact_store_identity": "artifact-set-index-v1@" + digest("8"),
        }

    def doctor(self) -> dict[str, object]:
        return {
            "ready": True,
            "status": "ready",
            "machine": {"identity": "container-host-machine-v1@" + digest("a")},
            "docker": {
                "context": "orbstack",
                "server_version": "27.3.1",
                "engine_identity": "docker-engine-v1@" + digest("b"),
            },
            "catalog": {"identity": load_catalog(CATALOG).identity},
            "profile": {
                "identity": INITIAL_EXECUTION_PROFILE.identity,
                "resources": dict(INITIAL_EXECUTION_PROFILE.as_mapping()),
            },
            "capacity": {"requested_match_parallelism": 4},
            "artifact_store": {
                "index_identity": "artifact-set-index-v1@" + digest("8")
            },
        }

    def test_fast_preparation_writes_a_comparable_report_and_doctor_inputs(self) -> None:
        with (
            mock.patch(
                "rps_runner.prepare_cli.prepare_offline_inputs",
                return_value=self.prepared(),
            ) as prepare,
            mock.patch(
                "rps_runner.prepare_cli._verify_engine_selection",
                return_value={"context": "orbstack", "platform": "linux/arm64"},
            ),
            mock.patch(
                "rps_runner.prepare_cli.diagnose_host_readiness",
                return_value=self.doctor(),
            ) as doctor,
            mock.patch(
                "rps_runner.prepare_cli.verify_presentation_assets",
                return_value={
                    "identity": "sha256:" + "9" * 64,
                    "assets": {
                        "index.html": "<!doctype html>",
                        "styles.css": "body{}",
                        "app.js": '"use strict";',
                    },
                },
            ),
            mock.patch("rps_runner.prepare_cli.time.monotonic", side_effect=(10.0, 22.5)),
        ):
            result = prepare_cli.run(self.arguments())

        self.assertEqual(result["preparation_report_format_version"], "rps-preparation-report-v1")
        self.assertEqual(result["mode"], "fast")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["elapsed_seconds"], 12.5)
        self.assertEqual(result["catalog_identity"], load_catalog(CATALOG).identity)
        self.assertEqual(result["profile_identity"], INITIAL_EXECUTION_PROFILE.identity)
        self.assertEqual(result["platform"], "linux/arm64")
        self.assertEqual(result["parallelism"], 4)
        self.assertEqual(result["docker_context"], "orbstack")
        self.assertEqual(result["docker_version"], "27.3.1")
        self.assertEqual(result["cached_identities"]["practice_artifacts"]["fixed-move"], digest("3"))
        self.assertEqual(result["offline_checks"]["artifact_restore"], "passed")
        self.assertEqual(result["offline_checks"]["presentation_assets"], "passed")
        self.assertEqual(
            result["presentation_assets"]["identity"],
            "sha256:" + "9" * 64,
        )
        self.assertEqual(result["artifact_store"]["path"], str(self.store.resolve()))
        self.assertEqual(json.loads(self.report.read_text()), result)
        request = doctor.call_args.args[0]
        self.assertEqual(request.catalog, CATALOG.resolve())
        self.assertEqual(request.platform, "linux/arm64")
        self.assertEqual(request.organizer_images, (digest("1"),))
        self.assertEqual(request.practice_artifacts[0][0], "copycat")
        self.assertEqual(request.artifact_store, self.store.resolve())
        prepare.assert_called_once()

    def test_all_mutable_selections_are_explicit_and_latest_is_rejected(self) -> None:
        parser = prepare_cli.build_parser()
        for missing in ("--catalog", "--environment", "--platform", "--profile", "--artifact-store", "--report"):
            arguments = self.arguments()
            index = arguments.index(missing)
            del arguments[index : index + 2]
            with self.assertRaises(prepare_cli.PreparationFailure):
                parser.parse_args(arguments)

        arguments = self.arguments()
        arguments[arguments.index("docker-execution-v1")] = "latest"
        with self.assertRaisesRegex(ValueError, "mutable latest"):
            prepare_cli.run(arguments)

    def test_existing_destinations_are_never_replaced(self) -> None:
        self.store.mkdir()
        with self.assertRaisesRegex(ValueError, "artifact store.*already exists"):
            prepare_cli.run(self.arguments())

    def test_wrong_engine_context_or_platform_stops_before_any_build(self) -> None:
        with mock.patch(
            "rps_runner.prepare_cli._docker",
            side_effect=(
                mock.Mock(returncode=0, stdout=b"desktop-linux\n", stderr=b""),
            ),
        ):
            with self.assertRaisesRegex(
                prepare_cli.PreparationFailure, "does not match explicit context"
            ):
                prepare_cli._verify_engine_selection("linux/arm64", "orbstack")

        with mock.patch(
            "rps_runner.prepare_cli._docker",
            side_effect=(
                mock.Mock(returncode=0, stdout=b"orbstack\n", stderr=b""),
                mock.Mock(
                    returncode=0,
                    stdout=json.dumps(
                        {"OSType": "linux", "Architecture": "x86_64"}
                    ).encode(),
                    stderr=b"",
                ),
            ),
        ):
            with self.assertRaisesRegex(
                prepare_cli.PreparationFailure, "requested 'linux/arm64'"
            ):
                prepare_cli._verify_engine_selection("linux/arm64", "orbstack")

    def test_runtime_pull_requires_permission_and_uses_the_pinned_reference(self) -> None:
        reference = "python@" + digest("9")
        missing = mock.Mock(
            returncode=1, stdout=b"", stderr=b"Error: No such image"
        )
        with (
            mock.patch(
                "rps_runner.prepare_cli.runtime_references",
                return_value=[reference],
            ),
            mock.patch("rps_runner.prepare_cli._docker", return_value=missing) as docker,
        ):
            with self.assertRaisesRegex(
                prepare_cli.PreparationFailure, "--allow-pull"
            ):
                prepare_cli._ensure_pinned_runtimes(
                    mock.Mock(), "linux/arm64", False
                )
        docker.assert_called_once_with(["image", "inspect", reference], timeout=10)

        present = mock.Mock(returncode=0, stdout=b"[]", stderr=b"")
        with (
            mock.patch(
                "rps_runner.prepare_cli.runtime_references",
                return_value=[reference],
            ),
            mock.patch(
                "rps_runner.prepare_cli._docker",
                side_effect=(missing, present, present),
            ) as docker,
        ):
            prepare_cli._ensure_pinned_runtimes(mock.Mock(), "linux/arm64", True)
        self.assertEqual(
            [call.args[0] for call in docker.call_args_list],
            [
                ["image", "inspect", reference],
                ["pull", "--platform", "linux/arm64", reference],
                ["image", "inspect", reference],
            ],
        )

    def test_failure_output_assigns_no_team_fault(self) -> None:
        error = prepare_cli.PreparationFailure(
            "catalog_correction", "frozen catalog asset digest does not match"
        )
        stderr = io.StringIO()
        with (
            mock.patch("rps_runner.prepare_cli.run", side_effect=error),
            mock.patch("sys.stderr", stderr),
        ):
            code = prepare_cli.main(self.arguments())

        self.assertEqual(code, 2)
        diagnostic = json.loads(stderr.getvalue().split(": ", 1)[1])
        self.assertEqual(diagnostic["disposition"], "catalog_correction")
        self.assertEqual(diagnostic["team_fault"], False)
        self.assertTrue(diagnostic["can_retry_after_correction"])

    def test_late_doctor_failure_rolls_back_the_generated_store(self) -> None:
        def prepare(**_: object) -> dict[str, object]:
            self.store.mkdir()
            return self.prepared()

        with (
            mock.patch(
                "rps_runner.prepare_cli.prepare_offline_inputs", side_effect=prepare
            ),
            mock.patch(
                "rps_runner.prepare_cli._verify_engine_selection",
                return_value={"context": "orbstack", "platform": "linux/arm64"},
            ),
            mock.patch(
                "rps_runner.prepare_cli.diagnose_host_readiness",
                return_value={"ready": False},
            ),
        ):
            with self.assertRaisesRegex(
                prepare_cli.PreparationFailure, "doctor did not accept"
            ):
                prepare_cli.run(self.arguments())

        self.assertFalse(self.store.exists())
        self.assertFalse(self.report.exists())

    def test_missing_required_input_has_the_failure_disposition(self) -> None:
        stderr = io.StringIO()
        arguments = self.arguments()
        index = arguments.index("--profile")
        del arguments[index : index + 2]
        with mock.patch("sys.stderr", stderr):
            code = prepare_cli.main(arguments)

        self.assertEqual(code, 2)
        diagnostic = json.loads(stderr.getvalue().split(": ", 1)[1])
        self.assertEqual(diagnostic["disposition"], "organizer_intervention")
        self.assertFalse(diagnostic["team_fault"])


if __name__ == "__main__":
    unittest.main()
