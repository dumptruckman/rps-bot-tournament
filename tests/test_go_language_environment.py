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
from rps_runner.engine import ContainerOperations
from rps_runner.artifact_store import ArtifactSelection, preserve_artifact_set
from rps_runner.execution_profile import INITIAL_EXECUTION_PROFILE
from rps_runner.tournament.retained_artifacts import canonical_artifact_identity
from rps_runner.tournament.match_executor import ContainerMatchExecutor
from rps_runner.tournament_cli import main as tournament_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "language_environments/catalog-v1/catalog.json"


class GoLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self.environment = self.catalog.environment("go")

    def test_selects_go_1_26_5_and_pins_both_supported_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(
            runtimes["selection"],
            {
                "policy": "latest-upstream-supported-stable",
                "go_version": "1.26.5",
                "rationale": (
                    "Go does not designate an LTS release; 1.26.5 was the latest "
                    "stable upstream release when selected."
                ),
                "selected_on": "2026-08-12",
                "upstream_release": "https://go.dev/dl/#go1.26.5",
            },
        )
        expected = {
            "linux/amd64": (
                "sha256:0d327c83532d3cdeeeebab56ce85962bf09cb89545355b10207c7771b0c3713f"
            ),
            "linux/arm64": (
                "sha256:b1a0cc29a7e13e0595e21087eeb930dc494976b18ba68279bf52c665f3170aa0"
            ),
        }
        for platform, digest in expected.items():
            coordinates = runtimes["platforms"][platform]
            self.assertEqual(
                set(coordinates), {"build_toolchain", "execution_runtime"}
            )
            for role in coordinates.values():
                self.assertEqual(role["image"], "docker.io/library/golang@" + digest)
                self.assertIn("go-1.26.5", role["version"])

    def test_accepts_only_the_go_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.go").write_text(
                'package main\n\nimport rand "math/rand/v2"\n\n'
                "func ChooseMove(turn int, myHistory, opponentHistory string, "
                "rng *rand.Rand) string {\n\treturn \"R\"\n}\n"
            )
            validate_source(source, self.environment)

            (source / "go.mod").write_text("module example.invalid/team\n")
            with self.assertRaisesRegex(
                SourceValidationError, "forbidden infrastructure"
            ):
                validate_source(source, self.environment)

    def test_rejects_a_strategy_that_redefines_wrapper_responsibilities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.go").write_text(
                "package main\n\nfunc main() {}\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "organizer-owned main"):
                validate_source(source, self.environment)

    def test_ignores_contract_text_inside_comments_and_literals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.go").write_text(
                "package main\n\n"
                "/* func ChooseMove(turn int, myHistory, opponentHistory string, "
                "rng *rand.Rand) string { } */\n"
                "var decoy = `func ChooseMove(turn int, myHistory, "
                "opponentHistory string, rng *rand.Rand) string { }`\n"
            )
            with self.assertRaisesRegex(SourceValidationError, "define exactly one"):
                validate_source(source, self.environment)

    def test_publishes_seed_adapter_golden_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)

        self.assertEqual(
            conformance["seed_adapter"]["version"], "go-pcg-seed-adapter-v1"
        )

    @unittest.skipUnless(shutil.which("go"), "Go is required to verify seed vectors")
    def test_seed_vectors_match_go_pcg_execution(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name) / "vectors.go"
            source.write_text(
                "package main\n\n"
                'import (\n\t"encoding/json"\n\t"os"\n'
                '\trand "math/rand/v2"\n)\n\n'
                "type vector struct { Seed uint64 `json:\"seed\"`; "
                "First []uint64 `json:\"first_uint64\"` }\n\n"
                "func main() {\n"
                "\tseeds := []uint64{0, 1, 9223372036854775807, "
                "18446744073709551615}\n"
                "\tresult := make([]vector, 0, len(seeds))\n"
                "\tfor _, seed := range seeds {\n"
                "\t\trng := rand.New(rand.NewPCG(seed, "
                "seed^uint64(0x9e3779b97f4a7c15)))\n"
                "\t\tresult = append(result, vector{seed, "
                "[]uint64{rng.Uint64(), rng.Uint64(), rng.Uint64()}})\n"
                "\t}\n"
                "\tif err := json.NewEncoder(os.Stdout).Encode(result); "
                "err != nil { panic(err) }\n}\n"
            )
            completed = subprocess.run(
                ["go", "run", source.name],
                cwd=source.parent,
                env={
                    **os.environ,
                    "GO111MODULE": "off",
                    "GOTOOLCHAIN": "local",
                    "GOPROXY": "off",
                    "GOSUMDB": "off",
                },
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            json.loads(completed.stdout),
            conformance["seed_adapter"]["golden_vectors"],
        )
        self.assertEqual(
            conformance["seed_adapter"]["golden_vectors"],
            [
                {
                    "seed": 0,
                    "first_uint64": [
                        8526951665006212644,
                        13293009889659832503,
                        18260787277176026961,
                    ],
                },
                {
                    "seed": 1,
                    "first_uint64": [
                        9729921568035403839,
                        567202678178297188,
                        12608104588819958962,
                    ],
                },
                {
                    "seed": 9223372036854775807,
                    "first_uint64": [
                        15421105985091242257,
                        9907233703736512638,
                        17147262756482350429,
                    ],
                },
                {
                    "seed": 18446744073709551615,
                    "first_uint64": [
                        7564132954489565118,
                        5218201376529462932,
                        15597715256427447486,
                    ],
                },
            ],
        )

    def test_networkless_recipe_compiles_the_catalog_wrapper_to_fixed_entrypoint(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)

        self.assertIn("GOTOOLCHAIN=local", recipe)
        self.assertIn("GOPROXY=off", recipe)
        self.assertIn("CGO_ENABLED=0", recipe)
        self.assertNotIn("go get", recipe)
        self.assertEqual(entrypoint["argv"], ["/opt/rps/bin/bot"])


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class GoLanguageEnvironmentDockerTests(unittest.TestCase):
    def _build(self, root: Path, language: str, source_text: str, platform: str):
        catalog = load_catalog(CATALOG_PATH)
        source = root / (language + "-source")
        source.mkdir()
        suffix = "go" if language == "go" else "py"
        (source / ("strategy." + suffix)).write_text(source_text)
        bundle = root / (language + "-bundle")
        freeze_source_bundle(source, bundle, catalog, catalog.environment(language))
        candidate = root / (language + "-candidate")
        return catalog, candidate, build_artifact_candidate(
            bundle, candidate, catalog, platform
        )

    def test_go_passes_complete_conformance_and_a_mixed_language_match(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        go_source = (
            'package main\n\nimport rand "math/rand/v2"\n\n'
            "func ChooseMove(turn int, myHistory, opponentHistory string, "
            "rng *rand.Rand) string {\n"
            "\treturn []string{\"R\", \"P\", \"S\"}[rng.IntN(3)]\n}\n"
        )
        python_source = (
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return rng.choice(('R', 'P', 'S'))\n"
        )

        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            catalog, go_candidate, go_manifest = self._build(
                root, "go", go_source, platform
            )
            result = certify_artifact_candidate(
                go_candidate,
                root / "go-certification",
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            _, python_candidate, python_manifest = self._build(
                root, "python", python_source, platform
            )
            references = {
                go_manifest["artifact_digest"]: go_manifest["retention"][
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
                    go_manifest["artifact_digest"],
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
                        ArtifactSelection(go_candidate, root / "go-certification"),
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
                                "index_identity": index["integrity"][
                                    "index_identity"
                                ],
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
                        "--tournament-id",
                        "mixed-language-proof",
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
