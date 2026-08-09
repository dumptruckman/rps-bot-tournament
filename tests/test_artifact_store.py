from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rps_runner.artifact_store import (
    ArtifactSelection,
    ArtifactStoreIntegrityError,
    load_retained_artifact_manifest,
    preserve_artifact_set,
    resolve_artifact,
    verify_artifact_store,
)


def digest(character: str) -> str:
    return "sha256:" + character * 64


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def selection(self, name: str, character: str) -> ArtifactSelection:
        candidate = self.directory / (name + "-candidate")
        source = candidate / "source"
        source.mkdir(parents=True)
        (source / "strategy.py").write_text("def choose_move(*args): return 'R'\n")
        source_digest = digest(character)
        artifact_digest = digest(chr(ord(character) + 1))
        image_id = digest(chr(ord(character) + 2))
        (candidate / "source-bundle.json").write_text(
            json.dumps(
                {
                    "bundle_format_version": "source-bundle-v1",
                    "source_digest": source_digest,
                    "files": ["strategy.py"],
                }
            )
        )
        (candidate / "artifact-candidate.json").write_text(
            json.dumps(
                {
                    "artifact_candidate_format_version": "artifact-candidate-v1",
                    "artifact_digest": artifact_digest,
                    "source_digest": source_digest,
                    "platform": "linux/arm64",
                    "image": {
                        "manifest_digest": artifact_digest,
                        "local_image_id": image_id,
                    },
                    "retention": {
                        "authority": artifact_digest,
                        "local_image_id": image_id,
                        "local_image_reference": name + ":mutable",
                    },
                }
            )
        )
        certification = self.directory / (name + "-certification")
        certification.mkdir()
        validation_identity = "validation-report-v1@" + digest(character)
        (certification / "bot-artifact-manifest.json").write_text(
            json.dumps(
                {
                    "bot_artifact_manifest_format_version": "bot-artifact-manifest-v1",
                    "status": "validated",
                    "artifact_digest": artifact_digest,
                    "source_digest": source_digest,
                    "platform": "linux/arm64",
                    "validation_identity": validation_identity,
                    "image": {
                        "manifest_digest": artifact_digest,
                        "local_image_id": image_id,
                    },
                    "retention": {
                        "authority": artifact_digest,
                        "local_image_id": image_id,
                        "local_image_reference": name + ":mutable",
                    },
                }
            )
        )
        (certification / "validation-report.json").write_text(
            json.dumps(
                {
                    "validation_report_format_version": "validation-report-v1",
                    "status": "passed",
                    "platform": "linux/arm64",
                    "validation_identity": validation_identity,
                }
            )
        )
        return ArtifactSelection(candidate, certification)

    def inspect(self, image_id: str) -> mock.Mock:
        return mock.Mock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "Id": image_id,
                        "Os": "linux",
                        "Architecture": "arm64",
                    }
                ]
            ).encode(),
            stderr=b"",
        )

    def preserve(self, name: str = "alpha") -> tuple[Path, dict[str, object]]:
        selection = self.selection(name, "1")
        store = self.directory / (name + "-store")

        def docker(command: list[str], **_: object) -> mock.Mock:
            if command[:3] == ["docker", "image", "inspect"]:
                return self.inspect(command[3])
            if command[:3] == ["docker", "image", "save"]:
                Path(command[command.index("--output") + 1]).write_bytes(
                    b"verified docker archive"
                )
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")
            self.fail("unexpected Docker command: " + repr(command))

        with mock.patch("rps_runner.artifact_store.subprocess.run", side_effect=docker):
            index = preserve_artifact_set(store, [selection])
        return store, dict(index["artifacts"][0])

    def test_preserves_two_artifacts_in_one_integrity_checked_archive(self) -> None:
        selections = [self.selection("alpha", "1"), self.selection("beta", "4")]
        store = self.directory / "store"

        def docker(command: list[str], **_: object) -> mock.Mock:
            if command[:2] == ["docker", "image"] and command[2] == "inspect":
                return self.inspect(command[3])
            if command[:3] == ["docker", "image", "save"]:
                output = Path(command[command.index("--output") + 1])
                output.write_bytes(b"one docker archive with shared layers")
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")
            self.fail("unexpected Docker command: " + repr(command))

        with mock.patch(
            "rps_runner.artifact_store.subprocess.run", side_effect=docker
        ) as run:
            index = preserve_artifact_set(store, selections)

        save = next(
            call.args[0]
            for call in run.call_args_list
            if call.args[0][:3] == ["docker", "image", "save"]
        )
        self.assertEqual(save.count("--output"), 1)
        self.assertEqual(set(save[-2:]), {digest("3"), digest("6")})
        self.assertEqual(len(index["artifacts"]), 2)
        self.assertTrue((store / "images.tar").is_file())
        self.assertTrue((store / "artifact-set-index.json").is_file())
        self.assertTrue(
            (
                store
                / "artifacts"
                / digest("2").split(":", 1)[1]
                / "source"
                / "strategy.py"
            ).is_file()
        )
        persisted = json.loads((store / "artifact-set-index.json").read_text())
        self.assertRegex(
            persisted["integrity"]["index_identity"],
            r"^artifact-set-index-v1@sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            persisted["archive"]["digest"],
            "sha256:" + hashlib.sha256((store / "images.tar").read_bytes()).hexdigest(),
        )
        serialized = json.dumps(persisted, sort_keys=True)
        self.assertNotIn(str(store), serialized)
        self.assertNotIn("alpha:mutable", serialized)

    def test_missing_validation_report_fails_before_docker_is_called(self) -> None:
        selection = self.selection("alpha", "1")
        (selection.certification / "validation-report.json").unlink()

        with (
            mock.patch("rps_runner.artifact_store.subprocess.run") as run,
            self.assertRaisesRegex(
                ArtifactStoreIntegrityError, "validation report is missing"
            ),
        ):
            preserve_artifact_set(self.directory / "store", [selection])

        run.assert_not_called()
        self.assertFalse((self.directory / "store").exists())

    def test_restores_an_absent_image_and_reverifies_identity(self) -> None:
        store, artifact = self.preserve()
        calls: list[list[str]] = []
        inspect_count = 0

        def docker(command: list[str], **_: object) -> mock.Mock:
            nonlocal inspect_count
            calls.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                inspect_count += 1
                if inspect_count == 1:
                    return mock.Mock(
                        returncode=1, stdout=b"", stderr=b"No such image"
                    )
                return self.inspect(str(artifact["image_id"]))
            if command[:3] == ["docker", "image", "load"]:
                return mock.Mock(returncode=0, stdout=b"Loaded image", stderr=b"")
            self.fail("unexpected Docker command: " + repr(command))

        with mock.patch("rps_runner.artifact_store.subprocess.run", side_effect=docker):
            resolved = resolve_artifact(
                store,
                str(artifact["artifact_digest"]),
                str(artifact["platform"]),
            )

        self.assertEqual(resolved, artifact["image_id"])
        self.assertEqual(
            [command[:3] for command in calls],
            [
                ["docker", "image", "inspect"],
                ["docker", "image", "load"],
                ["docker", "image", "inspect"],
            ],
        )
        self.assertEqual(calls[1][-1], str(store / "images.tar"))
        self.assertFalse(
            any("build" in command or "tag" in command for command in calls)
        )

    def test_loads_the_integrity_verified_retained_manifest(self) -> None:
        store, artifact = self.preserve()

        manifest = load_retained_artifact_manifest(
            store,
            str(artifact["artifact_digest"]),
            str(artifact["platform"]),
        )

        self.assertEqual(manifest["artifact_digest"], artifact["artifact_digest"])
        self.assertEqual(manifest["validation_identity"], artifact["validation_identity"])

    def test_corrupt_index_archive_and_retained_report_fail_closed(self) -> None:
        cases = ("index", "archive", "report")
        for index, kind in enumerate(cases):
            with self.subTest(kind=kind):
                store, artifact = self.preserve("artifact" + str(index))
                if kind == "index":
                    path = store / "artifact-set-index.json"
                    path.chmod(0o644)
                    value = json.loads(path.read_text())
                    value["artifacts"][0]["platform"] = "linux/amd64"
                    path.write_text(json.dumps(value))
                elif kind == "archive":
                    path = store / "images.tar"
                    path.chmod(0o644)
                    path.write_bytes(b"corrupt")
                else:
                    path = (
                        store
                        / str(artifact["path"])
                        / "validation-report.json"
                    )
                    path.chmod(0o644)
                    path.write_text("{}")

                with self.assertRaisesRegex(
                    ArtifactStoreIntegrityError, "integrity|digest|validation report"
                ):
                    verify_artifact_store(store)

    def test_wrong_platform_after_restore_is_actionable(self) -> None:
        store, artifact = self.preserve()
        inspect_count = 0

        def docker(command: list[str], **_: object) -> mock.Mock:
            nonlocal inspect_count
            if command[:3] == ["docker", "image", "inspect"]:
                inspect_count += 1
                if inspect_count == 1:
                    return mock.Mock(
                        returncode=1, stdout=b"", stderr=b"No such image"
                    )
                result = self.inspect(str(artifact["image_id"]))
                value = json.loads(result.stdout)
                value[0]["Architecture"] = "amd64"
                result.stdout = json.dumps(value).encode()
                return result
            if command[:3] == ["docker", "image", "load"]:
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")
            self.fail("unexpected Docker command: " + repr(command))

        with (
            mock.patch("rps_runner.artifact_store.subprocess.run", side_effect=docker),
            self.assertRaisesRegex(
                ArtifactStoreIntegrityError, "wrong platform.*amd64"
            ),
        ):
            resolve_artifact(
                store,
                str(artifact["artifact_digest"]),
                str(artifact["platform"]),
            )

    def test_manifest_digest_mismatch_fails_before_export(self) -> None:
        selection = self.selection("alpha", "1")
        manifest_path = selection.certification / "bot-artifact-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["image"]["manifest_digest"] = digest("f")
        manifest_path.write_text(json.dumps(manifest))

        with (
            mock.patch("rps_runner.artifact_store.subprocess.run") as run,
            self.assertRaisesRegex(
                ArtifactStoreIntegrityError, "image manifest digest mismatch"
            ),
        ):
            preserve_artifact_set(self.directory / "store", [selection])

        run.assert_not_called()

    def test_archive_missing_requested_image_fails_without_substitution(self) -> None:
        store, artifact = self.preserve()
        calls: list[list[str]] = []

        def docker(command: list[str], **_: object) -> mock.Mock:
            calls.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                return mock.Mock(
                    returncode=1, stdout=b"", stderr=b"No such image"
                )
            if command[:3] == ["docker", "image", "load"]:
                return mock.Mock(
                    returncode=0, stdout=b"loaded another image", stderr=b""
                )
            self.fail("unexpected Docker command: " + repr(command))

        with (
            mock.patch("rps_runner.artifact_store.subprocess.run", side_effect=docker),
            self.assertRaisesRegex(
                ArtifactStoreIntegrityError,
                "missing after loading.*expected local image ID",
            ),
        ):
            resolve_artifact(
                store,
                str(artifact["artifact_digest"]),
                str(artifact["platform"]),
            )

        self.assertFalse(
            any("build" in command or "tag" in command for command in calls)
        )

    def test_daemon_failure_is_not_treated_as_an_absent_image(self) -> None:
        store, artifact = self.preserve()

        with (
            mock.patch(
                "rps_runner.artifact_store.subprocess.run",
                return_value=mock.Mock(
                    returncode=1,
                    stdout=b"",
                    stderr=b"Cannot connect to the Docker daemon",
                ),
            ) as run,
            self.assertRaisesRegex(
                ArtifactStoreIntegrityError, "Cannot connect to the Docker daemon"
            ),
        ):
            resolve_artifact(
                store,
                str(artifact["artifact_digest"]),
                str(artifact["platform"]),
            )

        self.assertEqual(len(run.call_args_list), 1)
        self.assertEqual(run.call_args.args[0][:3], ["docker", "image", "inspect"])

    def test_post_load_check_rebinds_image_to_authoritative_digest(self) -> None:
        store, artifact = self.preserve()
        inspect_count = 0

        def docker(command: list[str], **_: object) -> mock.Mock:
            nonlocal inspect_count
            if command[:3] == ["docker", "image", "inspect"]:
                inspect_count += 1
                if inspect_count == 1:
                    return mock.Mock(
                        returncode=1, stdout=b"", stderr=b"No such image"
                    )
                return self.inspect(str(artifact["image_id"]))
            if command[:3] == ["docker", "image", "load"]:
                manifest_path = (
                    store
                    / str(artifact["path"])
                    / "bot-artifact-manifest.json"
                )
                manifest_path.chmod(0o644)
                manifest = json.loads(manifest_path.read_text())
                manifest["artifact_digest"] = digest("f")
                manifest_path.write_text(json.dumps(manifest))
                return mock.Mock(returncode=0, stdout=b"", stderr=b"")
            self.fail("unexpected Docker command: " + repr(command))

        with (
            mock.patch("rps_runner.artifact_store.subprocess.run", side_effect=docker),
            self.assertRaisesRegex(ArtifactStoreIntegrityError, "digest mismatch"),
        ):
            resolve_artifact(
                store,
                str(artifact["artifact_digest"]),
                str(artifact["platform"]),
            )


if __name__ == "__main__":
    unittest.main()
