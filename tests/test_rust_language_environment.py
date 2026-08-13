from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import (
    CertificationInputs,
    _conformance_match_request,
    certify_artifact_candidate,
)
from rps_runner.engine import ContainerOperations
from rps_runner.language_environment import (
    SourceValidationError,
    freeze_source_bundle,
    load_catalog,
    validate_source,
)
from rps_runner.tournament.match_executor import ContainerMatchExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "language_environments/catalog-v1/catalog.json"


class RustLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self.environment = self.catalog.environment("rust")

    def test_selects_rust_1_97_1_and_pins_both_supported_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)
        self.assertEqual(
            runtimes["selection"],
            {
                "policy": "latest-upstream-supported-stable",
                "rust_version": "1.97.1",
                "rationale": (
                    "Rust does not designate an LTS release; 1.97.1 was the "
                    "latest stable upstream release when selected."
                ),
                "selected_on": "2026-08-12",
                "upstream_release": "https://blog.rust-lang.org/2026/07/16/Rust-1.97.1/",
            },
        )
        expected = {
            "linux/amd64": "sha256:408fe88047cef61a2087653b0c5255fa51c0f2d6d94ddedd7a2562a9b91a46f6",
            "linux/arm64": "sha256:6e957ef098dcc77d33e310261e4ed5843bb108d5c3b5dc2b476cbc8b6caf53fa",
        }
        for platform, digest in expected.items():
            for role in ("build_toolchain", "execution_runtime"):
                coordinate = runtimes["platforms"][platform][role]
                self.assertEqual(
                    coordinate["image"],
                    "docker.io/library/rust@" + digest,
                )
                self.assertIn("rust-1.97.1", coordinate["version"])

    def test_accepts_only_the_rust_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.rs").write_text(
                "pub fn choose_move(_turn: usize, _my_history: &str, "
                "_opponent_history: &str, _rng: &mut RpsRandom) -> &'static str "
                "{ \"R\" }\n"
            )
            validate_source(source, self.environment)

            (source / "Cargo.toml").write_text("[package]\nname = \"team\"\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden_paths"):
                validate_source(source, self.environment)

    def test_accepts_rust_literals_and_nested_comments_before_the_contract(self) -> None:
        for declaration in (
            "const ROCK: char = 'R';",
            "const ROCK: u8 = b'R';",
            'const TEXT: &str = r#"fn main() {}"#;',
            "/* outer /* inner */ fn main() {} */",
        ):
            with self.subTest(declaration=declaration), tempfile.TemporaryDirectory() as name:
                source = Path(name)
                (source / "strategy.rs").write_text(
                    declaration
                    + "\npub fn choose_move(_turn: usize, _my_history: &str, "
                    "_opponent_history: &str, _rng: &mut RpsRandom) -> &'static str "
                    "{ \"R\" }\n"
                )
                validate_source(source, self.environment)

    def test_rejects_wrapper_responsibilities_and_contract_decoys(self) -> None:
        cases = {
            "missing": "pub const MOVE: &str = \"R\";\n",
            "decoy": (
                "const DECOY: &str = r#\"pub fn choose_move(turn: usize, "
                "my_history: &str, opponent_history: &str, "
                "rng: &mut RpsRandom) -> &'static str\"#;\n"
            ),
            "wrapper": (
                "fn main() {}\n"
                "pub fn choose_move(_turn: usize, _my_history: &str, "
                "_opponent_history: &str, _rng: &mut RpsRandom) -> &'static str "
                "{ \"R\" }\n"
            ),
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                source = Path(name)
                (source / "strategy.rs").write_text(content)
                with self.assertRaises(SourceValidationError):
                    validate_source(source, self.environment)

    def test_publishes_splitmix64_seed_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        adapter = conformance["seed_adapter"]
        self.assertEqual(adapter["version"], "rust-splitmix64-seed-adapter-v1")
        self.assertEqual(
            adapter["golden_vectors"],
            [
                {"seed": "0", "first_uint64": ["16294208416658607535", "7960286522194355700", "487617019471545679"]},
                {"seed": "1", "first_uint64": ["10451216379200822465", "13757245211066428519", "17911839290282890590"]},
                {"seed": "9223372036854775807", "first_uint64": ["3055647633038352039", "17441316833444690247", "17011665146503905680"]},
                {"seed": "18446744073709551615", "first_uint64": ["16490336266968443936", "16834447057089888969", "4048727598324417001"]},
            ],
        )
        self.assertFalse(adapter["system_randomness"])

    @unittest.skipUnless(shutil.which("rustc"), "rustc is required to execute seed vectors")
    def test_rust_seed_adapter_executes_published_golden_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        vectors = conformance["seed_adapter"]["golden_vectors"]
        wrapper = self.environment.assets["wrapper"].content.decode()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "wrapper.rs").write_text(wrapper)
            (root / "strategy.rs").write_text(
                "pub fn choose_move(_turn: usize, _my_history: &str, "
                "_opponent_history: &str, _rng: &mut RpsRandom) -> &'static str "
                "{ \"R\" }\n"
            )
            cases = ",".join(item["seed"] for item in vectors)
            (root / "vectors.rs").write_text(
                "mod wrapper { include!(\"wrapper.rs\"); }\n"
                "fn main() { for seed in [" + cases + "] { "
                "let mut rng = wrapper::RpsRandom::new(seed); "
                "println!(\"{} {} {}\", rng.next_u64(), rng.next_u64(), "
                "rng.next_u64()); } }\n"
            )
            executable = root / "vectors"
            subprocess.run(
                [shutil.which("rustc"), "--edition=2024", str(root / "vectors.rs"), "-o", str(executable)],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run(
                [str(executable)], check=True, capture_output=True, text=True
            )
        self.assertEqual(
            completed.stdout.splitlines(),
            [" ".join(item["first_uint64"]) for item in vectors],
        )

    def test_networkless_recipe_has_fixed_entrypoint_and_no_crate_resolution(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)
        self.assertIn("rustc", recipe)
        self.assertIn("--edition=2024", recipe)
        for mutable_input in ("cargo fetch", "cargo install", "crates.io", "curl ", "wget "):
            self.assertNotIn(mutable_input, recipe.lower())
        self.assertEqual(entrypoint["argv"], ["/opt/rps/bin/bot"])


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class RustLanguageEnvironmentDockerTests(unittest.TestCase):
    def test_rust_passes_complete_conformance_and_a_mixed_language_match(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        catalog = load_catalog(CATALOG_PATH)
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "source"
            source.mkdir()
            (source / "strategy.rs").write_text(
                "pub fn choose_move(_turn: usize, _my_history: &str, "
                "_opponent_history: &str, rng: &mut RpsRandom) -> &'static str "
                "{ [\"R\", \"P\", \"S\"][rng.next_usize(3)] }\n"
            )
            bundle = root / "bundle"
            freeze_source_bundle(source, bundle, catalog, catalog.environment("rust"))
            rust_manifest = build_artifact_candidate(
                bundle, root / "candidate", catalog, platform
            )
            result = certify_artifact_candidate(
                root / "candidate",
                root / "certification",
                catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
            python_source = root / "python-source"
            python_source.mkdir()
            (python_source / "strategy.py").write_text(
                "def choose_move(turn, my_history, opponent_history, rng):\n"
                "    return rng.choice(('R', 'P', 'S'))\n"
            )
            python_bundle = root / "python-bundle"
            freeze_source_bundle(
                python_source, python_bundle, catalog, catalog.environment("python")
            )
            python_manifest = build_artifact_candidate(
                python_bundle, root / "python-candidate", catalog, platform
            )
            references = {
                rust_manifest["artifact_digest"]: rust_manifest["retention"]["local_image_id"],
                python_manifest["artifact_digest"]: python_manifest["retention"]["local_image_id"],
            }
            match = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            ).execute(
                _conformance_match_request(
                    rust_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language-rust",
                )
            )
        self.assertEqual(result["report"]["status"], "passed")
        self.assertFalse(match.infrastructure_failure)
        self.assertEqual(
            match.competitive_outcome["faults"],
            {"candidate-a": None, "candidate-b": None},
        )


if __name__ == "__main__":
    unittest.main()
