from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rps_runner.language_environment import (
    SourceValidationError,
    load_catalog,
    validate_source,
    freeze_source_bundle,
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


class BrainfCkLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = load_catalog(CATALOG_PATH).environment("brainf-ck")

    def test_publishes_the_catalog_owned_interpreter_and_pinned_python_runtime(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)

        self.assertEqual(runtimes["selection"]["dialect"], "brainf-ck-rps-v1")
        self.assertEqual(
            runtimes["selection"]["implementation_version"],
            "catalog-brainf-ck-interpreter-v1",
        )
        self.assertEqual(runtimes["selection"]["python_version"], "3.14.6")
        for platform in ("linux/amd64", "linux/arm64"):
            build = runtimes["platforms"][platform]["build_toolchain"]
            runtime = runtimes["platforms"][platform]["execution_runtime"]
            self.assertRegex(
                build["image"],
                r"^docker.io/library/python@sha256:[0-9a-f]{64}$",
            )
            self.assertRegex(
                runtime["image"],
                r"^docker.io/library/python@sha256:[0-9a-f]{64}$",
            )

    def test_accepts_only_one_bounded_brainf_ck_program(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            strategy = source / "strategy.bf"
            strategy.write_text(",.")
            validate_source(source, self.environment)

            strategy.write_text(",[.")
            with self.assertRaisesRegex(SourceValidationError, "unmatched"):
                validate_source(source, self.environment)

            strategy.write_text("++.")
            with self.assertRaisesRegex(SourceValidationError, "input command"):
                validate_source(source, self.environment)

            (source / "wrapper.py").write_text("raise SystemExit\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden infrastructure"):
                validate_source(source, self.environment)

    def test_interpreter_enforces_tape_step_and_output_bounds(self) -> None:
        path = PROJECT_ROOT / self.environment.assets["dependency_definition"].path
        spec = importlib.util.spec_from_file_location("catalog_brainf_ck", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        program = module.compile_program(",.")
        self.assertEqual(
            module.execute(program, b"R", tape_cells=8, step_limit=10, output_limit=1),
            b"R",
        )
        with self.assertRaisesRegex(module.ExecutionLimitError, "tape"):
            module.execute(module.compile_program(",>>>>>>>>"), b"R", tape_cells=8)
        with self.assertRaisesRegex(module.ExecutionLimitError, "step"):
            module.execute(module.compile_program(",+[]"), b"R", step_limit=20)
        with self.assertRaisesRegex(module.ExecutionLimitError, "time"):
            module.execute(
                module.compile_program(",+[]"),
                b"R",
                step_limit=100_000,
                time_limit_ms=0,
            )
        with self.assertRaisesRegex(module.ExecutionLimitError, "output"):
            module.execute(module.compile_program(",.."), b"R", output_limit=1)

    def test_wrapper_encodes_seed_turn_and_histories_deterministically(self) -> None:
        wrapper = PROJECT_ROOT / self.environment.assets["wrapper"].path
        environment = os.environ.copy()
        environment.update(
            {
                "RPS_PROTOCOL_VERSION": "1",
                "RPS_ROUNDS": "3",
                "RPS_SEED": "1",
                "RPS_BRAINF_CK_SOURCE": str(
                    PROJECT_ROOT / "tests/fixtures/brainf_ck_seed_probe.bf"
                ),
            }
        )
        completed = subprocess.run(
            [sys.executable, "-I", str(wrapper)],
            input="0\n-\n-\n1\nR\nP\n2\nRP\nPS\n",
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["P", "S", "S"])
        self.assertIn("RPS_READY_V1", completed.stderr)

    def test_contract_documents_encoding_and_golden_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)

        self.assertEqual(conformance["input_encoding"]["seed"], "8-byte little-endian unsigned")
        self.assertEqual(conformance["input_encoding"]["histories"], "ASCII R, P, or S bytes")
        self.assertEqual(conformance["move_output"], "exactly one ASCII R, P, or S byte")
        self.assertEqual(
            [vector["first_move"] for vector in conformance["seed_adapter"]["golden_vectors"]],
            ["P", "P", "R", "S"],
        )
        self.assertEqual(
            conformance["input_encoding"]["golden_vectors"],
            [
                {
                    "seed": "1",
                    "turn": 2,
                    "own_history": "RP",
                    "opponent_history": "PS",
                    "encoded_hex": "535353010000000000000002000000000000000200525002005053",
                }
            ],
        )

        wrapper_path = PROJECT_ROOT / self.environment.assets["wrapper"].path
        spec = importlib.util.spec_from_file_location("brainf_ck_wrapper", wrapper_path)
        assert spec is not None and spec.loader is not None
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        self.assertEqual(
            wrapper.encode_turn(1, 2, "RP", "PS").hex(),
            conformance["input_encoding"]["golden_vectors"][0]["encoded_hex"],
        )

    def test_networkless_recipe_uses_the_fixed_catalog_interpreter(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)

        self.assertIn("organizer/interpreter.py", recipe)
        self.assertNotIn("curl ", recipe)
        self.assertNotIn("wget ", recipe)
        self.assertNotIn("pip install", recipe)
        self.assertEqual(
            entrypoint["argv"],
            ["/usr/local/bin/python3", "-I", "/opt/rps/wrapper.py"],
        )


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class BrainfCkLanguageEnvironmentDockerTests(unittest.TestCase):
    def _build(self, root: Path, language: str, source_text: str, platform: str):
        catalog = load_catalog(CATALOG_PATH)
        source = root / (language + "-source")
        source.mkdir()
        filename = "strategy.bf" if language == "brainf-ck" else "strategy.py"
        (source / filename).write_text(source_text)
        bundle = root / (language + "-bundle")
        freeze_source_bundle(source, bundle, catalog, catalog.environment(language))
        candidate = root / (language + "-candidate")
        return catalog, candidate, build_artifact_candidate(
            bundle, candidate, catalog, platform
        )

    def test_brainf_ck_passes_complete_conformance_and_a_mixed_language_plan(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        python_source = (
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return rng.choice(('R', 'P', 'S'))\n"
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog, brainf_ck_candidate, brainf_ck_manifest = self._build(
                root, "brainf-ck", ",.", platform
            )
            certification = root / "brainf-ck-certification"
            result = certify_artifact_candidate(
                brainf_ck_candidate,
                certification,
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            _, python_candidate, python_manifest = self._build(
                root, "python", python_source, platform
            )
            references = {
                brainf_ck_manifest["artifact_digest"]: brainf_ck_manifest["retention"]["local_image_id"],
                python_manifest["artifact_digest"]: python_manifest["retention"]["local_image_id"],
            }
            match = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            ).execute(
                _conformance_match_request(
                    brainf_ck_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language-brainf-ck",
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
                        ArtifactSelection(brainf_ck_candidate, certification),
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
                            "team_id": "mixed-brainf-ck-team-" + str(ordinal),
                            "display_name": "Mixed Brainf-ck Team " + str(ordinal),
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
                        "mixed-language-brainf-ck-proof",
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
