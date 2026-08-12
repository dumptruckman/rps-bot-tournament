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


class CSharpLanguageEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = load_catalog(CATALOG_PATH)
        self.environment = self.catalog.environment("csharp")

    def test_selects_dotnet_10_lts_and_pins_both_supported_platforms(self) -> None:
        runtimes = json.loads(self.environment.assets["base_runtime"].content)
        self.assertEqual(
            runtimes["selection"],
            {
                "policy": "latest-upstream-supported-lts",
                "dotnet_release": "10",
                "sdk_version": "10.0.302",
                "runtime_version": "10.0.10",
                "csharp_version": "14",
                "rationale": (
                    ".NET 10 is the latest upstream-supported LTS line; SDK "
                    "10.0.302 and runtime 10.0.10 were the latest servicing "
                    "releases available when selected."
                ),
                "selected_on": "2026-08-12",
                "upstream_release": "https://dotnet.microsoft.com/download/dotnet/10.0",
            },
        )
        expected = {
            "linux/amd64": {
                "build_toolchain": "sha256:7a91ccecc26d71bf7688c627a6b5eae2e27bb2cd1e37e8abe738348904245692",
                "execution_runtime": "sha256:4d3f0fed221262600ace6384e809d7954a2d77266bc2f08193f763c5702bedce",
            },
            "linux/arm64": {
                "build_toolchain": "sha256:683d16913974bf1311381ccd6d6aba55213f313501c39ef964b0458f44c0c4bc",
                "execution_runtime": "sha256:9c6a00c4c4f36b64f9d1bef6226fff9b219ceca3f75ede924d06649710a3ebba",
            },
        }
        for platform, roles in expected.items():
            for role, digest in roles.items():
                coordinate = runtimes["platforms"][platform][role]
                self.assertEqual(
                    coordinate["image"],
                    "mcr.microsoft.com/dotnet/"
                    + ("sdk" if role == "build_toolchain" else "runtime")
                    + "@"
                    + digest,
                )

    def test_accepts_only_the_csharp_strategy_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "Strategy.cs").write_text(
                "public static class Strategy {\n"
                "  public static string ChooseMove(int turn, string myHistory, "
                "string opponentHistory, RpsRandom rng) => \"R\";\n}\n"
            )
            validate_source(source, self.environment)

            (source / "RpsBot.csproj").write_text("<Project />\n")
            with self.assertRaisesRegex(SourceValidationError, "forbidden_paths"):
                validate_source(source, self.environment)

    def test_rejects_wrapper_responsibilities_and_contract_decoys(self) -> None:
        cases = {
            "missing": "public static class Strategy { public const string Move = \"R\"; }\n",
            "decoy": (
                "public static class Strategy {\n"
                "  const string Decoy = \"public static string ChooseMove(int turn, "
                "string myHistory, string opponentHistory, RpsRandom rng)\";\n}\n"
            ),
            "wrapper": (
                "public static class Program { public static void Main() {} }\n"
                "public static class Strategy { public static string ChooseMove("
                "int turn, string myHistory, string opponentHistory, RpsRandom rng) "
                "=> \"R\"; }\n"
            ),
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as name:
                source = Path(name)
                (source / "Strategy.cs").write_text(content)
                with self.assertRaises(SourceValidationError):
                    validate_source(source, self.environment)

    def test_publishes_splitmix64_seed_vectors(self) -> None:
        conformance = json.loads(self.environment.assets["conformance"].content)
        adapter = conformance["seed_adapter"]
        self.assertEqual(adapter["version"], "csharp-splitmix64-seed-adapter-v1")
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

    def test_networkless_recipe_has_fixed_entrypoint_and_no_package_resolution(self) -> None:
        recipe = self.environment.assets["recipe"].content.decode()
        entrypoint = json.loads(self.environment.assets["entrypoint"].content)
        self.assertIn("csc.dll", recipe)
        self.assertIn("-nostdlib+", recipe)
        for mutable_input in ("dotnet restore", "nuget", "curl ", "wget "):
            self.assertNotIn(mutable_input, recipe.lower())
        self.assertEqual(entrypoint["argv"], ["/usr/bin/dotnet", "/opt/rps/RpsBot.dll"])


@unittest.skipUnless(
    os.environ.get("RPS_RUN_DOCKER_INTEGRATION") == "1",
    "set RPS_RUN_DOCKER_INTEGRATION=1 after preparing pinned Docker runtimes",
)
class CSharpLanguageEnvironmentDockerTests(unittest.TestCase):
    def test_csharp_passes_complete_conformance_and_a_mixed_language_match(self) -> None:
        platform = os.environ.get("RPS_DOCKER_PLATFORM", "linux/amd64")
        mode = "organizer-final" if platform == "linux/arm64" else "github-advisory"
        catalog = load_catalog(CATALOG_PATH)
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            source = root / "source"
            source.mkdir()
            (source / "Strategy.cs").write_text(
                "public static class Strategy { public static string ChooseMove("
                "int turn, string myHistory, string opponentHistory, RpsRandom rng) "
                "=> new[] { \"R\", \"P\", \"S\" }[rng.NextInt(3)]; }\n"
            )
            bundle = root / "bundle"
            freeze_source_bundle(source, bundle, catalog, catalog.environment("csharp"))
            candidate = root / "candidate"
            csharp_manifest = build_artifact_candidate(
                bundle, candidate, catalog, platform
            )
            result = certify_artifact_candidate(
                candidate,
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
                python_source,
                python_bundle,
                catalog,
                catalog.environment("python"),
            )
            python_manifest = build_artifact_candidate(
                python_bundle, root / "python-candidate", catalog, platform
            )
            references = {
                csharp_manifest["artifact_digest"]: csharp_manifest["retention"][
                    "local_image_id"
                ],
                python_manifest["artifact_digest"]: python_manifest["retention"][
                    "local_image_id"
                ],
            }
            match = ContainerMatchExecutor(
                lambda _team_id, digest: references[digest],
                operations=ContainerOperations(),
            ).execute(
                _conformance_match_request(
                    csharp_manifest["artifact_digest"],
                    python_manifest["artifact_digest"],
                    8675309,
                    99,
                    namespace="mixed-language-csharp",
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
