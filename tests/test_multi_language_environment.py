from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from rps_runner.language_environment import freeze_source_bundle, load_catalog
from rps_runner.artifact_builder import ArtifactBuildFailure, build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationInputs,
    certify_artifact_candidate,
)
from rps_runner.artifact_store import (
    ArtifactSelection,
    preserve_artifact_set,
    resolve_artifact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments/catalog-v1/catalog.json"


class SecondExecutableEnvironmentTests(unittest.TestCase):
    def test_internal_shell_environment_freezes_without_python_validation(self) -> None:
        catalog = load_catalog(CATALOG)
        environment = catalog.environment("internal-shell")
        self.assertEqual(environment.language, "shell-fixture")
        self.assertFalse(environment.contract_only)
        self.assertEqual(environment.publication, "internal")

        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "source"
            source.mkdir()
            (source / "strategy.sh").write_text("this is deliberately not Python\n")

            manifest = freeze_source_bundle(
                source, root / "bundle", catalog, environment
            )

        self.assertEqual(manifest["environment"], "internal-shell")
        self.assertEqual(
            manifest["participant_contract"]["static_validation"], "none-v1"
        )
        self.assertEqual(
            manifest["versions"]["descriptor"],
            environment.descriptor_identity,
        )

    def test_internal_shell_pins_distinct_build_and_execution_images(self) -> None:
        catalog = load_catalog(CATALOG)
        environment = catalog.environment("internal-shell")
        runtimes = json.loads(environment.assets["base_runtime"].content)

        self.assertEqual(set(runtimes["platforms"]), {"linux/amd64", "linux/arm64"})
        for platform in runtimes["platforms"].values():
            self.assertNotEqual(
                platform["build_toolchain"]["image"],
                platform["execution_runtime"]["image"],
            )
            for role in ("build_toolchain", "execution_runtime"):
                self.assertRegex(
                    platform[role]["image"], r"@sha256:[0-9a-f]{64}$"
                )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class SecondExecutableEnvironmentDockerTests(unittest.TestCase):
    def test_internal_shell_passes_build_certification_and_retention(self) -> None:
        catalog = load_catalog(CATALOG)
        environment = catalog.environment("internal-shell")
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"

        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "source"
            source.mkdir()
            (source / "strategy.sh").write_text(
                "choose_move() { case $(( ($4 + $1) % 3 )) in "
                "0) echo R;; 1) echo P;; *) echo S;; esac; }\n"
            )
            bundle = root / "bundle"
            freeze_source_bundle(source, bundle, catalog, environment)
            candidate = root / "candidate"
            try:
                candidate_manifest = build_artifact_candidate(
                    bundle, candidate, catalog, platform
                )
            except ArtifactBuildFailure as error:
                self.fail(str(error) + "\n" + error.diagnostics)
            certification = root / "certification"
            result = certify_artifact_candidate(
                candidate,
                certification,
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            store = root / "artifact-store"
            index = preserve_artifact_set(
                store, [ArtifactSelection(candidate, certification)]
            )
            restored = resolve_artifact(
                store,
                str(candidate_manifest["artifact_digest"]),
                platform,
            )

        self.assertEqual(result["manifest"]["language"], "shell-fixture")
        self.assertEqual(result["report"]["status"], "passed")
        self.assertEqual(restored, candidate_manifest["image"]["local_image_id"])
        self.assertRegex(
            index["integrity"]["index_identity"],
            r"^artifact-set-index-v1@sha256:[0-9a-f]{64}$",
        )


if __name__ == "__main__":
    unittest.main()
