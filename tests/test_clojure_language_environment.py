from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationInputs,
    certify_artifact_candidate,
)
from rps_runner.language_environment import (
    SourceValidationError,
    freeze_source_bundle,
    load_catalog,
    validate_source,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "language_environments/catalog-v1/catalog.json"


class ClojureLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = load_catalog(CATALOG).environment("clojure")

    def test_selects_clojure_1_12_5_with_java_25_lts_on_both_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(runtimes["selection"]["clojure_version"], "1.12.5")
        self.assertEqual(runtimes["selection"]["clojure_cli_version"], "1.12.5.1664")
        self.assertEqual(runtimes["selection"]["java_version"], "25.0.3+9")
        expected = {
            "linux/amd64": {
                "build_toolchain": (
                    "docker.io/library/clojure@sha256:"
                    "c50576e2fcb26300d09dae1f3b5d3a7a1482334c5113ea7bcd3f6a17b0141aca"
                ),
                "execution_runtime": (
                    "docker.io/library/eclipse-temurin@sha256:"
                    "c650e8097620a27a61f476d2a269e02078dc9f316136ecd9821dedd98b89e719"
                ),
            },
            "linux/arm64": {
                "build_toolchain": (
                    "docker.io/library/clojure@sha256:"
                    "394388e78b78fc48d385ca92d42df15501d48996a157f663c5c788a7d3bb86fc"
                ),
                "execution_runtime": (
                    "docker.io/library/eclipse-temurin@sha256:"
                    "57f9a2046d0ff628c24c0c127bd9d37a57e372064b30fdade9c00683382c1ab3"
                ),
            },
        }
        for platform, roles in expected.items():
            for role, image in roles.items():
                self.assertEqual(runtimes["platforms"][platform][role]["image"], image)

    def test_accepts_only_the_clojure_strategy_contract(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source = Path(name)
            strategy = source / "strategy.clj"
            strategy.write_text(
                "(ns strategy)\n"
                "(defn choose-move [turn my-history opponent-history rng] \"R\")\n"
            )
            validate_source(source, self.environment)

            (source / "deps.edn").write_text("{:deps {}}\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden_paths"):
                validate_source(source, self.environment)
            (source / "deps.edn").unlink()

            strategy.write_text(
                "(ns strategy)\n"
                "; (defn choose-move [turn my-history opponent-history rng] \"R\")\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "define exactly one"):
                validate_source(source, self.environment)

            strategy.write_text(
                "(ns strategy)\n"
                "(deftype RpsRandom [])\n"
                "(defn choose-move [turn my-history opponent-history rng] \"R\")\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "organizer-owned"):
                validate_source(source, self.environment)

    def test_publishes_seed_vectors_and_networkless_fixed_entrypoint(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        adapter = conformance["seed_adapter"]
        self.assertEqual(adapter["version"], "clojure-splitmix64-seed-adapter-v1")
        self.assertFalse(adapter["system_randomness"])
        self.assertEqual(
            adapter["golden_vectors"][0]["first_uint64"],
            ["16294208416658607535", "7960286522194355700", "487617019471545679"],
        )

        recipe = self.environment.assets["recipe"].content.decode().lower()
        for mutable in ("clojure -p", "clojure -x", "curl ", "wget ", "maven", "clojars"):
            self.assertNotIn(mutable, recipe)
        self.assertIn("sha256sum -c /opt/rps/dependencies.lock", recipe)
        self.assertEqual(
            json.loads(self.environment.assets["entrypoint"].content)["argv"],
            [
                "/opt/java/openjdk/bin/java",
                "-XX:+UseSerialGC",
                "-XX:TieredStopAtLevel=1",
                "-Xms32m",
                "-Xmx128m",
                "-cp",
                "/opt/rps/lib/*:/opt/rps/team:/opt/rps/organizer",
                "clojure.main",
                "-m",
                "rps-wrapper",
            ],
        )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "enable Docker integration",
)
class ClojureLanguageEnvironmentDockerTests(unittest.TestCase):
    def test_clojure_passes_complete_conformance(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        catalog = load_catalog(CATALOG)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source"
            source.mkdir()
            (source / "strategy.clj").write_text(
                "(ns strategy)\n"
                "(defn choose-move [turn my-history opponent-history rng]\n"
                "  (nth [\"R\" \"P\" \"S\"] (.nextInt rng 3)))\n"
            )
            bundle = root / "bundle"
            freeze_source_bundle(source, bundle, catalog, catalog.environment("clojure"))
            build_artifact_candidate(bundle, root / "candidate", catalog, platform)
            result = certify_artifact_candidate(
                root / "candidate",
                root / "certification",
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
        self.assertEqual(result["report"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
