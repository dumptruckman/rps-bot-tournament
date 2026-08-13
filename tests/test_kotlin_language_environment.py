from __future__ import annotations

import json
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

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


class KotlinLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = load_catalog(CATALOG_PATH).environment("kotlin")

    def test_selects_kotlin_2_4_10_with_java_25_lts_on_both_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(runtimes["selection"]["kotlin_version"], "2.4.10")
        self.assertEqual(runtimes["selection"]["java_version"], "25.0.3+9")
        self.assertEqual(runtimes["selection"]["java_lts_release"], "25")
        for platform in ("linux/amd64", "linux/arm64"):
            build = runtimes["platforms"][platform]["build_toolchain"]
            runtime = runtimes["platforms"][platform]["execution_runtime"]
            self.assertRegex(build["image"], r"^docker.io/library/eclipse-temurin@sha256:[0-9a-f]{64}$")
            self.assertRegex(runtime["image"], r"^docker.io/library/eclipse-temurin@sha256:[0-9a-f]{64}$")
            self.assertEqual(
                build["kotlin_compiler"]["sha256"],
                "sha256:473dd66c7a3ef4b182065b3da670466c1bf2773a9dbb0ed8b33a39fe9d4f876d",
            )

    def test_accepts_only_the_kotlin_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "Strategy.kt").write_text(
                "import java.util.random.RandomGenerator\n\n"
                "object Strategy {\n"
                "  fun chooseMove(turn: Int, myHistory: String, "
                "opponentHistory: String, rng: RandomGenerator): String = \"R\"\n"
                "}\n"
            )
            validate_source(source, self.environment)

            (source / "build.gradle.kts").write_text("plugins {}\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden infrastructure"):
                validate_source(source, self.environment)

    def test_rejects_wrapper_responsibilities_and_contract_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            strategy = source / "Strategy.kt"
            strategy.write_text(
                "object Strategy {\n"
                "  // fun chooseMove(turn: Int, myHistory: String, opponentHistory: String, rng: RandomGenerator): String = \"R\"\n"
                "  @JvmStatic fun main(args: Array<String>) {}\n"
                "}\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "organizer-owned main"):
                validate_source(source, self.environment)

            strategy.write_text(
                "object Strategy {\n"
                "  val decoy = \"fun chooseMove(turn: Int, myHistory: String, opponentHistory: String, rng: RandomGenerator): String\"\n"
                "}\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "define exactly one"):
                validate_source(source, self.environment)

    def test_publishes_splitable_random_seed_vectors_without_ambient_randomness(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        adapter = conformance["seed_adapter"]

        self.assertEqual(adapter["version"], "kotlin-splittable-random-seed-adapter-v1")
        self.assertFalse(adapter["system_randomness"])
        self.assertEqual(
            adapter["golden_vectors"],
            [
                {"seed": "0", "first_long": [-2152535657050944081, 7960286522194355700, 487617019471545679]},
                {"seed": "1", "first_long": [-7995527694508729151, -4689498862643123097, -534904783426661026]},
                {"seed": "9223372036854775807", "first_long": [3055647633038352039, -1005427240264861369, -1435078927205645936]},
                {"seed": "18446744073709551615", "first_long": [-1956407806741107680, -1612297016619662647, 4048727598324417001]},
            ],
        )

        java = shutil.which("java")
        if java is not None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                compiler = PROJECT_ROOT / self.environment.assets[
                    "dependency_definition"
                ].path
                with zipfile.ZipFile(compiler) as archive:
                    archive.extractall(root / "compiler")
                source = root / "Vectors.kt"
                source.write_text(
                    "import java.util.SplittableRandom\n"
                    "fun main() {\n"
                    "  val seeds = arrayOf(\"0\", \"1\", \"9223372036854775807\", "
                    "\"18446744073709551615\")\n"
                    "  for (value in seeds) {\n"
                    "    val rng = SplittableRandom(java.lang.Long.parseUnsignedLong(value))\n"
                    "    println(\"$value:${rng.nextLong()},${rng.nextLong()},${rng.nextLong()}\")\n"
                    "  }\n"
                    "}\n"
                )
                compiler_command = root / "compiler/kotlinc/bin/kotlinc"
                compiler_command.chmod(0o755)
                subprocess.run(
                    [str(compiler_command), str(source), "-include-runtime", "-d", "vectors.jar"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                completed = subprocess.run(
                    [java, "-jar", "vectors.jar"],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            observed = []
            for line in completed.stdout.splitlines():
                seed, values = line.split(":")
                observed.append(
                    {"seed": seed, "first_long": [int(value) for value in values.split(",")]}
                )
            self.assertEqual(observed, adapter["golden_vectors"])

    def test_networkless_recipe_compiles_to_the_fixed_kotlin_entrypoint(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)

        self.assertIn("kotlin-compiler-2.4.10.zip", recipe)
        self.assertIn("-jvm-target 25", recipe)
        self.assertNotIn("curl ", recipe)
        self.assertNotIn("wget ", recipe)
        self.assertEqual(
            entrypoint["argv"],
            ["/opt/java/openjdk/bin/java", "-jar", "/opt/rps/rps-bot.jar"],
        )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class KotlinLanguageEnvironmentDockerTests(unittest.TestCase):
    def _build(self, root: Path, language: str, source_text: str, platform: str):
        catalog = load_catalog(CATALOG_PATH)
        source = root / (language + "-source")
        source.mkdir()
        filename = "Strategy.kt" if language == "kotlin" else "strategy.py"
        (source / filename).write_text(source_text)
        bundle = root / (language + "-bundle")
        freeze_source_bundle(source, bundle, catalog, catalog.environment(language))
        candidate = root / (language + "-candidate")
        return catalog, candidate, build_artifact_candidate(
            bundle, candidate, catalog, platform
        )

    def test_kotlin_passes_complete_conformance_and_a_mixed_language_plan(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        kotlin_source = (
            "import java.util.random.RandomGenerator\n\n"
            "object Strategy {\n"
            "  fun chooseMove(turn: Int, myHistory: String, opponentHistory: String, "
            "rng: RandomGenerator): String = arrayOf(\"R\", \"P\", \"S\")[rng.nextInt(3)]\n"
            "}\n"
        )
        python_source = (
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return rng.choice(('R', 'P', 'S'))\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, kotlin_candidate, kotlin_manifest = self._build(
                root, "kotlin", kotlin_source, platform
            )
            kotlin_certification = root / "kotlin-certification"
            result = certify_artifact_candidate(
                kotlin_candidate,
                kotlin_certification,
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            _, python_candidate, python_manifest = self._build(
                root, "python", python_source, platform
            )
            references = {
                kotlin_manifest["artifact_digest"]: kotlin_manifest["retention"]["local_image_id"],
                python_manifest["artifact_digest"]: python_manifest["retention"]["local_image_id"],
            }
            match = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            ).execute(
                _conformance_match_request(
                    kotlin_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language-kotlin",
                )
            )
            tournament_exit = None
            if platform == "linux/arm64":
                python_certification = root / "python-certification"
                python_result = certify_artifact_candidate(
                    python_candidate,
                    python_certification,
                    catalog,
                    CertificationInputs(mode, platform, "docker-execution-v1"),
                )
                store = root / "artifact-store"
                index = preserve_artifact_set(
                    store,
                    [
                        ArtifactSelection(kotlin_candidate, kotlin_certification),
                        ArtifactSelection(python_candidate, python_certification),
                    ],
                )
                resources = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
                resources.pop("version")
                resources.pop("recommended_match_parallelism")
                plan = {
                    "tournament_plan_format_version": "tournament-plan-v1",
                    "status": "draft",
                    "tournament_seed": 8675309,
                    "execution": {"mode": "step", "parallelism": 1},
                    "catalog": {"version": catalog.version, "identity": catalog.identity},
                    "execution_profile": {
                        "version": INITIAL_EXECUTION_PROFILE.version,
                        "identity": INITIAL_EXECUTION_PROFILE.identity,
                    },
                    "global_resources": resources,
                    "artifact_store": {"index_identity": index["integrity"]["index_identity"]},
                    "teams": [],
                }
                for ordinal in range(4):
                    manifest = [result["manifest"], python_result["manifest"]][ordinal % 2]
                    plan["teams"].append(
                        {
                            "team_id": "mixed-kotlin-team-" + str(ordinal),
                            "display_name": "Mixed Kotlin Team " + str(ordinal),
                            "roster_ready": True,
                            "selected_source": {"source_digest": manifest["source_digest"]},
                            "bot_artifact_manifest": manifest,
                            "canonical_artifact_identity": canonical_artifact_identity(manifest),
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
                        "plan", "--plan", str(plan_path), "--catalog", str(CATALOG_PATH),
                        "--artifact-store", str(store), "--directory", str(root / "tournament"),
                        "--tournament-id", "mixed-language-kotlin-proof",
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
