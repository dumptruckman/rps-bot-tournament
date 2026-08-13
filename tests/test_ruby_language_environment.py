from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from rps_runner.artifact_builder import build_artifact_candidate
from rps_runner.artifact_certification import CertificationInputs, certify_artifact_candidate
from rps_runner.language_environment import SourceValidationError, freeze_source_bundle, load_catalog, validate_source


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "language_environments/catalog-v1/catalog.json"


class RubyLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = load_catalog(CATALOG).environment("ruby")

    def test_selects_ruby_4_0_6_and_pins_supported_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)
        self.assertEqual(runtimes["selection"]["ruby_version"], "4.0.6")
        expected = {
            "linux/amd64": "sha256:5dff75e5286a89836c9fb34473809e4b6a756687a914898b7ecf5fd8d29e16a8",
            "linux/arm64": "sha256:cde120660ff22235429157098de77cf3f14291f220c8eea49564edecbd5a2516",
        }
        for platform, digest in expected.items():
            for role in ("build_toolchain", "execution_runtime"):
                self.assertEqual(
                    runtimes["platforms"][platform][role]["image"],
                    "docker.io/library/ruby@" + digest,
                )

    def test_accepts_only_the_ruby_strategy_contract(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source = Path(name)
            (source / "strategy.rb").write_text(
                "def choose_move(turn, my_history, opponent_history, rng)\n  'R'\nend\n"
            )
            validate_source(source, self.environment)
            (source / "Gemfile").write_text("source 'https://rubygems.org'\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden_paths"):
                validate_source(source, self.environment)

    def test_rejects_contract_decoys_and_wrapper_responsibilities(self) -> None:
        cases = (
            'DECOY = "def choose_move(turn, my_history, opponent_history, rng)"\n',
            "class RpsRandom; end\ndef choose_move(turn, my_history, opponent_history, rng)\n 'R'\nend\n",
        )
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as name:
                source = Path(name)
                (source / "strategy.rb").write_text(content)
                with self.assertRaises(SourceValidationError):
                    validate_source(source, self.environment)

    def test_accepts_percent_literal_and_block_comment_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            source = Path(name)
            (source / "strategy.rb").write_text(
                "%q{def choose_move(turn, my_history, opponent_history, rng)}\n"
                "=begin\nclass RpsRandom\n=end\n"
                "def choose_move(turn, my_history, opponent_history, rng)\n 'R'\nend\n"
            )
            validate_source(source, self.environment)

    @unittest.skipUnless(shutil.which("ruby"), "Ruby is required")
    def test_wrapper_sanitizes_import_and_protects_seed_adapter_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "wrapper.rb").write_bytes(self.environment.assets["wrapper"].content)
            (root / "strategy.rb").write_text(
                "warn 'RPS_READY_V1'\n"
                "raise 'ambient environment leaked' if ENV.key?('RPS_SECRET')\n"
                "begin\n class ::RpsRandom; def next_uint64; 0; end; end\nrescue FrozenError\nend\n"
                "def choose_move(turn, my_history, opponent_history, rng); 'R'; end\n"
            )
            env = {"RPS_PROTOCOL_VERSION": "1", "RPS_SEED": "0", "RPS_ROUNDS": "1", "RPS_SECRET": "no"}
            completed = subprocess.run([shutil.which("ruby"), "wrapper.rb"], cwd=root, env=env, input="0\n-\n-\n", capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr.splitlines(), ["RPS_READY_V1"])
        self.assertEqual(completed.stdout, "R\n")

    def test_publishes_seed_vectors_without_system_randomness(self) -> None:
        adapter = json.loads(self.environment.assets["conformance"].content)["seed_adapter"]
        self.assertEqual(adapter["version"], "ruby-splitmix64-seed-adapter-v1")
        self.assertFalse(adapter["system_randomness"])
        self.assertEqual(adapter["golden_vectors"][0]["first_uint64"][0], "16294208416658607535")

    @unittest.skipUnless(shutil.which("ruby"), "Ruby is required to execute seed vectors")
    def test_wrapper_executes_published_seed_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        vectors = conformance["seed_adapter"]["golden_vectors"]
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "wrapper.rb").write_bytes(self.environment.assets["wrapper"].content)
            (root / "strategy.rb").write_text("def choose_move(turn, my_history, opponent_history, rng); 'R'; end\n")
            script = "require_relative 'wrapper'; " + "; ".join(
                f"r=RpsRandom.new({item['seed']}); puts [r.next_uint64,r.next_uint64,r.next_uint64].join(' ')"
                for item in vectors
            )
            completed = subprocess.run([shutil.which("ruby"), "-e", script], cwd=root, check=True, capture_output=True, text=True)
        self.assertEqual(completed.stdout.splitlines(), [" ".join(item["first_uint64"]) for item in vectors])

    def test_networkless_recipe_has_fixed_entrypoint(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode().lower()
        for mutable in ("bundle install", "gem install", "rubygems.org", "curl ", "wget "):
            self.assertNotIn(mutable, recipe)
        self.assertEqual(json.loads(self.environment.assets["entrypoint"].content)["argv"], ["/opt/rps/bin/bot"])


@unittest.skipUnless(os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1", "enable Docker integration")
class RubyLanguageEnvironmentDockerTests(unittest.TestCase):
    def test_ruby_passes_complete_conformance(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        catalog = load_catalog(CATALOG)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source = root / "source"
            source.mkdir()
            (source / "strategy.rb").write_text(
                "def choose_move(turn, my_history, opponent_history, rng)\n  %w[R P S][rng.next_int(3)]\nend\n"
            )
            bundle = root / "bundle"
            freeze_source_bundle(source, bundle, catalog, catalog.environment("ruby"))
            build_artifact_candidate(bundle, root / "candidate", catalog, platform)
            result = certify_artifact_candidate(
                root / "candidate", root / "certification", catalog,
                CertificationInputs(mode, platform, "docker-execution-v1"),
            )
        self.assertEqual(result["report"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()
