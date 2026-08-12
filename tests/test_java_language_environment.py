from __future__ import annotations

import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rps_runner.language_environment import (
    SourceValidationError,
    freeze_source_bundle,
    load_catalog,
    validate_source,
)
from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationInputs,
    _conformance_match_request,
    certify_artifact_candidate,
)
from rps_runner.artifact_store import ArtifactSelection, preserve_artifact_set
from rps_runner.engine import ContainerOperations
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.tournament.match_executor import ContainerMatchExecutor
from rps_runner.tournament.retained_artifacts import canonical_artifact_identity
from rps_runner.tournament_cli import main as tournament_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "language_environments/catalog-v1/catalog.json"


class JavaLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self.environment = self.catalog.environment("java")

    def test_selects_java_25_lts_and_pins_both_supported_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(
            runtimes["selection"],
            {
                "policy": "latest-upstream-supported-lts",
                "java_version": "25.0.3+9",
                "lts_release": "25",
                "rationale": (
                    "Java 25 is the latest upstream-designated LTS line; "
                    "Temurin 25.0.3+9 was the latest matching official "
                    "container build available when selected."
                ),
                "selected_on": "2026-08-12",
                "upstream_release": (
                    "https://adoptium.net/temurin/releases/?version=25"
                ),
            },
        )
        expected = {
            "linux/amd64": {
                "build_toolchain": (
                    "sha256:78e1c29a95bd36513e7d67eb730b699c6e6f46ef975e35e937c66eb726539609"
                ),
                "execution_runtime": (
                    "sha256:c650e8097620a27a61f476d2a269e02078dc9f316136ecd9821dedd98b89e719"
                ),
            },
            "linux/arm64": {
                "build_toolchain": (
                    "sha256:9d41aef0f1b800791a4c1e3e2ae52fc36a5b154a9edd08f0ab382b1999401e83"
                ),
                "execution_runtime": (
                    "sha256:57f9a2046d0ff628c24c0c127bd9d37a57e372064b30fdade9c00683382c1ab3"
                ),
            },
        }
        for platform, roles in expected.items():
            for role, digest in roles.items():
                coordinate = runtimes["platforms"][platform][role]
                self.assertEqual(
                    coordinate["image"],
                    "docker.io/library/eclipse-temurin@" + digest,
                )
                self.assertIn("java-25.0.3+9", coordinate["version"])

    def test_accepts_only_the_java_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "Strategy.java").write_text(
                "import java.util.random.RandomGenerator;\n\n"
                "public final class Strategy {\n"
                "  public static String chooseMove(int turn, String myHistory, "
                "String opponentHistory, RandomGenerator rng) { return \"R\"; }\n"
                "}\n"
            )
            validate_source(source, self.environment)

            (source / "pom.xml").write_text("<project/>\n")
            with self.assertRaisesRegex(
                SourceValidationError, "forbidden infrastructure"
            ):
                validate_source(source, self.environment)

    def test_rejects_wrapper_responsibilities_and_contract_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            strategy = source / "Strategy.java"
            strategy.write_text(
                "public final class Strategy {\n"
                "  // public static String chooseMove(int turn, String myHistory, "
                "String opponentHistory, RandomGenerator rng) { return \"R\"; }\n"
                "  public static void main(String[] args) {}\n"
                "}\n"
            )
            with self.assertRaisesRegex(
                SourceValidationError, "organizer-owned main"
            ):
                validate_source(source, self.environment)

            strategy.write_text(
                "public final class Strategy {\n"
                "  String decoy = \"public static String chooseMove(int turn, "
                "String myHistory, String opponentHistory, RandomGenerator rng)\";\n"
                "}\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "define exactly one"):
                validate_source(source, self.environment)

    def test_publishes_and_executes_splittable_random_seed_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        adapter = conformance["seed_adapter"]

        self.assertEqual(adapter["version"], "java-splittable-random-seed-adapter-v1")
        self.assertEqual(
            adapter["golden_vectors"],
            [
                {
                    "seed": "0",
                    "first_long": [
                        -2152535657050944081,
                        7960286522194355700,
                        487617019471545679,
                    ],
                },
                {
                    "seed": "1",
                    "first_long": [
                        -7995527694508729151,
                        -4689498862643123097,
                        -534904783426661026,
                    ],
                },
                {
                    "seed": "9223372036854775807",
                    "first_long": [
                        3055647633038352039,
                        -1005427240264861369,
                        -1435078927205645936,
                    ],
                },
                {
                    "seed": "18446744073709551615",
                    "first_long": [
                        -1956407806741107680,
                        -1612297016619662647,
                        4048727598324417001,
                    ],
                },
            ],
        )

        if shutil.which("javac") and shutil.which("java"):
            with tempfile.TemporaryDirectory() as temporary_name:
                root = Path(temporary_name)
                source = root / "Vectors.java"
                source.write_text(
                    "import java.util.SplittableRandom;\n"
                    "public final class Vectors { public static void main(String[] a) {\n"
                    "  String[] seeds = {\"0\", \"1\", \"9223372036854775807\", "
                    "\"18446744073709551615\"};\n"
                    "  for (String value : seeds) {\n"
                    "    var rng = new SplittableRandom(Long.parseUnsignedLong(value));\n"
                    "    System.out.printf(\"%s:%d,%d,%d%n\", value, rng.nextLong(), "
                    "rng.nextLong(), rng.nextLong());\n"
                    "  }\n} }\n"
                )
                subprocess.run(["javac", "Vectors.java"], cwd=root, check=True)
                completed = subprocess.run(
                    ["java", "-cp", str(root), "Vectors"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            observed = []
            for line in completed.stdout.splitlines():
                seed, values = line.split(":")
                observed.append(
                    {"seed": seed, "first_long": [int(v) for v in values.split(",")]}
                )
            self.assertEqual(observed, adapter["golden_vectors"])

    def test_networkless_recipe_compiles_to_the_fixed_java_entrypoint(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)

        self.assertIn("javac --release 25", recipe)
        self.assertNotIn("curl ", recipe)
        self.assertNotIn("wget ", recipe)
        self.assertEqual(
            entrypoint["argv"],
            [
                "/opt/java/openjdk/bin/java",
                "-cp",
                "/opt/rps/classes",
                "RpsWrapper",
            ],
        )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class JavaLanguageEnvironmentDockerTests(unittest.TestCase):
    def _build(self, root: Path, language: str, source_text: str, platform: str):
        catalog = load_catalog(CATALOG_PATH)
        source = root / (language + "-source")
        source.mkdir()
        filename = "Strategy.java" if language == "java" else "strategy.py"
        (source / filename).write_text(source_text)
        bundle = root / (language + "-bundle")
        freeze_source_bundle(source, bundle, catalog, catalog.environment(language))
        candidate = root / (language + "-candidate")
        return catalog, candidate, build_artifact_candidate(
            bundle, candidate, catalog, platform
        )

    def test_java_passes_complete_conformance_and_a_mixed_language_plan(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        java_source = (
            "import java.util.random.RandomGenerator;\n\n"
            "public final class Strategy {\n"
            "  public static String chooseMove(int turn, String myHistory, "
            "String opponentHistory, RandomGenerator rng) {\n"
            "    return new String[] {\"R\", \"P\", \"S\"}[rng.nextInt(3)];\n"
            "  }\n}\n"
        )
        python_source = (
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return rng.choice(('R', 'P', 'S'))\n"
        )

        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            catalog, java_candidate, java_manifest = self._build(
                root, "java", java_source, platform
            )
            result = certify_artifact_candidate(
                java_candidate,
                root / "java-certification",
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            _, python_candidate, python_manifest = self._build(
                root, "python", python_source, platform
            )
            references = {
                java_manifest["artifact_digest"]: java_manifest["retention"][
                    "local_image_id"
                ],
                python_manifest["artifact_digest"]: python_manifest["retention"][
                    "local_image_id"
                ],
            }
            executor = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            )
            match = executor.execute(
                _conformance_match_request(
                    java_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language",
                )
            )
            tournament_exit = None
            if platform == "linux/arm64":
                python_certification = root / "python-certification"
                python_result = certify_artifact_candidate(
                    python_candidate,
                    python_certification,
                    catalog,
                    CertificationInputs(
                        "organizer-final", platform, "docker-execution-v1"
                    ),
                )
                store = root / "artifact-store"
                index = preserve_artifact_set(
                    store,
                    [
                        ArtifactSelection(java_candidate, root / "java-certification"),
                        ArtifactSelection(python_candidate, python_certification),
                    ],
                )
                manifests = [result["manifest"], python_result["manifest"]]
                resources = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
                resources.pop("version")
                resources.pop("recommended_match_parallelism")
                plan = {
                    "tournament_plan_format_version": "tournament-plan-v1",
                    "status": "draft",
                    "tournament_seed": 8675309,
                    "execution": {"mode": "step", "parallelism": 1},
                    "catalog": {
                        "version": catalog.version,
                        "identity": catalog.identity,
                    },
                    "execution_profile": {
                        "version": INITIAL_EXECUTION_PROFILE.version,
                        "identity": INITIAL_EXECUTION_PROFILE.identity,
                    },
                    "global_resources": resources,
                    "artifact_store": {
                        "index_identity": index["integrity"]["index_identity"]
                    },
                    "teams": [],
                }
                for ordinal in range(4):
                    manifest = manifests[ordinal % 2]
                    plan["teams"].append(
                        {
                            "team_id": "mixed-team-" + str(ordinal),
                            "display_name": "Mixed Team " + str(ordinal),
                            "roster_ready": True,
                            "selected_source": {
                                "source_digest": manifest["source_digest"]
                            },
                            "bot_artifact_manifest": manifest,
                            "canonical_artifact_identity": (
                                canonical_artifact_identity(manifest)
                            ),
                            "artifact_store_reference": {
                                "index_identity": index["integrity"]["index_identity"],
                                "artifact_digest": manifest["artifact_digest"],
                                "platform": platform,
                            },
                        }
                    )
                plan_path = root / "tournament-plan.json"
                plan_path.write_text(json.dumps(plan))
                tournament_exit = tournament_main(
                    [
                        "plan",
                        "--plan",
                        str(plan_path),
                        "--catalog",
                        str(CATALOG_PATH),
                        "--artifact-store",
                        str(store),
                        "--directory",
                        str(root / "tournament"),
                        "--tournament-id", "mixed-language-java-proof",
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )

        self.assertEqual(result["report"]["status"], "passed")
        self.assertFalse(match.infrastructure_failure)
        self.assertEqual(
            match.competitive_outcome["faults"],
            {"candidate-a": None, "candidate-b": None},
        )
        if platform == "linux/arm64":
            self.assertEqual(tournament_exit, 0)


if __name__ == "__main__":
    unittest.main()
