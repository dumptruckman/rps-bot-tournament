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
from rps_runner.tournament.match_executor import ContainerMatchExecutor
from rps_runner.tournament.retained_artifacts import canonical_artifact_identity
from rps_runner.tournament_cli import main as tournament_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "language_environments/catalog-v1/catalog.json"


class TypeScriptLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self.environment = self.catalog.environment("typescript")

    def test_selects_node_24_19_lts_and_typescript_6_0_3(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(
            runtimes["selection"],
            {
                "policy": "latest-upstream-supported-lts",
                "node_version": "24.19.0",
                "node_lts_release": "24",
                "typescript_version": "6.0.3",
                "rationale": (
                    "Node.js 24.19.0 is the latest release on the newest "
                    "upstream-supported LTS line; TypeScript 6.0.3 is the "
                    "latest compatible stable compiler."
                ),
                "selected_on": "2026-08-12",
                "upstream_node_release": (
                    "https://nodejs.org/en/download/archive/v24"
                ),
                "upstream_typescript_release": (
                    "https://github.com/microsoft/TypeScript/releases/tag/v6.0.3"
                ),
            },
        )
        expected = {
            "linux/amd64": (
                "sha256:65932751ed4073ed02f5c04e494e4b2572a891b7dbea0568a863dc80341bf848"
            ),
            "linux/arm64": (
                "sha256:c133efe216ffb6e785ed9a8be55a29fcb86775e8008ae0a9f0ed6af4f175bb03"
            ),
        }
        for platform, digest in expected.items():
            coordinates = runtimes["platforms"][platform]
            for role in ("build_toolchain", "execution_runtime"):
                self.assertEqual(
                    coordinates[role]["image"],
                    "docker.io/library/node@" + digest,
                )
                self.assertIn("node-24.19.0", coordinates[role]["version"])
            self.assertEqual(
                coordinates["build_toolchain"]["typescript"],
                {
                    "package": "typescript-6.0.3.tgz",
                    "sha256": (
                        "sha256:33cd0ee1beaa8c9e9d15a9da836c62ddea4c34a42d7c2d349dbc80d94165d22a"
                    ),
                    "version": "6.0.3",
                },
            )

    def test_accepts_only_the_typescript_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.ts").write_text(
                "export function chooseMove(turn: number, myHistory: string, "
                "opponentHistory: string, rng: { nextInt(limit: number): number })"
                ": string { return ['R', 'P', 'S'][rng.nextInt(3)]; }\n"
            )
            validate_source(source, self.environment)

            (source / "package.json").write_text("{}\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden_paths"):
                validate_source(source, self.environment)

    def test_rejects_missing_or_redefined_strategy_contract(self) -> None:
        cases = {
            "missing": "export const move = 'R';\n",
            "duplicate": (
                "export function chooseMove(turn: number, myHistory: string, "
                "opponentHistory: string, rng: { nextInt(limit: number): number })"
                ": string { return 'R'; }\n"
                "export const chooseMove = () => 'P';\n"
            ),
            "wrapper": (
                "process.stdin.on('data', () => {});\n"
                "export function chooseMove(turn: number, myHistory: string, "
                "opponentHistory: string, rng: { nextInt(limit: number): number })"
                ": string { return 'R'; }\n"
            ),
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                source = Path(name)
                (source / "strategy.ts").write_text(content)
                with self.assertRaises(SourceValidationError):
                    validate_source(source, self.environment)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_published_seed_vectors_execute_through_the_wrapper(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        vectors = conformance["seed_adapter"]["golden_vectors"]
        compiler_archive = (
            PROJECT_ROOT / "language_environments/catalog-v1/typescript/typescript-6.0.3.tgz"
        )
        wrapper = self.environment.assets["wrapper"].path

        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            subprocess.run(
                ["tar", "-xzf", str(compiler_archive), "-C", str(temporary)],
                check=True,
            )
            subprocess.run(
                [
                    "node",
                    str(temporary / "package/lib/tsc.js"),
                    "--target", "ES2022",
                    "--module", "commonjs",
                    "--outDir", str(temporary / "dist"),
                    str(wrapper),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            script = (
                "const { SeedAdapter } = require(process.argv[1]);"
                "const vectors = JSON.parse(process.argv[2]);"
                "const actual = vectors.map(({seed}) => {"
                "const rng = new SeedAdapter(seed);"
                "return {seed, first_uint64: [rng.nextUint64(), rng.nextUint64(), "
                "rng.nextUint64()].map(String)}; });"
                "process.stdout.write(JSON.stringify(actual));"
            )
            completed = subprocess.run(
                [
                    "node",
                    "-e",
                    script,
                    str(temporary / "dist/RpsWrapper.js"),
                    json.dumps(vectors),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(json.loads(completed.stdout), vectors)
        self.assertFalse(conformance["seed_adapter"]["system_randomness"])

    def test_networkless_recipe_uses_vendored_compiler_and_fixed_entrypoint(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode("utf-8")
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)

        self.assertIn("typescript-6.0.3.tgz", recipe)
        self.assertIn("package/lib/tsc.js", recipe)
        for mutable_input in ("npm install", "npm ci", "npx ", "curl ", "wget "):
            self.assertNotIn(mutable_input, recipe)
        self.assertEqual(
            self.environment.assets["dependency_definition"].digest,
            "sha256:33cd0ee1beaa8c9e9d15a9da836c62ddea4c34a42d7c2d349dbc80d94165d22a",
        )
        self.assertEqual(
            entrypoint["argv"], ["/usr/local/bin/node", "/opt/rps/dist/RpsWrapper.js"]
        )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class TypeScriptLanguageEnvironmentDockerTests(unittest.TestCase):
    def _build(self, root: Path, language: str, source_text: str, platform: str):
        catalog = load_catalog(CATALOG_PATH)
        source = root / (language + "-source")
        source.mkdir()
        filename = "strategy.ts" if language == "typescript" else "strategy.py"
        (source / filename).write_text(source_text)
        bundle = root / (language + "-bundle")
        freeze_source_bundle(source, bundle, catalog, catalog.environment(language))
        candidate = root / (language + "-candidate")
        return catalog, candidate, build_artifact_candidate(
            bundle, candidate, catalog, platform
        )

    def test_typescript_passes_conformance_and_a_mixed_language_match(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        typescript_source = (
            "export function chooseMove(turn: number, myHistory: string, "
            "opponentHistory: string, rng: { nextInt(limit: number): number })"
            ": string { return ['R', 'P', 'S'][rng.nextInt(3)]; }\n"
        )
        python_source = (
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return rng.choice(('R', 'P', 'S'))\n"
        )

        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            catalog, ts_candidate, ts_manifest = self._build(
                root, "typescript", typescript_source, platform
            )
            result = certify_artifact_candidate(
                ts_candidate,
                root / "typescript-certification",
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            _, python_candidate, python_manifest = self._build(
                root, "python", python_source, platform
            )
            references = {
                ts_manifest["artifact_digest"]: ts_manifest["retention"]["local_image_id"],
                python_manifest["artifact_digest"]: python_manifest["retention"]["local_image_id"],
            }
            match = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            ).execute(
                _conformance_match_request(
                    ts_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language-typescript",
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
                        ArtifactSelection(
                            ts_candidate, root / "typescript-certification"
                        ),
                        ArtifactSelection(python_candidate, python_certification),
                    ],
                )
                manifests = [result["manifest"], python_result["manifest"]]
                resources = dict(INITIAL_EXECUTION_PROFILE.as_mapping())
                resources.pop("version")
                resources.pop("recommended_match_parallelism")
                teams = []
                for ordinal in range(4):
                    manifest = manifests[ordinal % 2]
                    teams.append(
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
                plan_path.write_text(
                    json.dumps(
                        {
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
                            "teams": teams,
                        }
                    )
                )
                tournament_exit = tournament_main(
                    [
                        "plan", "--plan", str(plan_path), "--catalog", str(CATALOG_PATH),
                        "--artifact-store", str(store), "--directory",
                        str(root / "tournament"), "--tournament-id",
                        "mixed-language-typescript-proof",
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
