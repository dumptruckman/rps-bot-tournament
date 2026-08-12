from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMAND = PROJECT_ROOT / "freeze-tournament-catalog"


class CatalogReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = Path(self.temporary_directory.name) / "runner"
        self.bundle = Path(self.temporary_directory.name) / "catalog-release.bundle"
        self._copy_release_sources()
        self._git("init", "--quiet")
        self._git("config", "user.email", "catalog-release@example.invalid")
        self._git("config", "user.name", "Catalog Release Test")
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "frozen runner catalog"
        )

    def _copy_release_sources(self) -> None:
        self.repository.mkdir()
        for name in (
            ".github",
            "language_environments",
            "rps_runner",
        ):
            shutil.copytree(
                PROJECT_ROOT / name,
                self.repository / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for name in (".gitignore", "freeze-tournament-catalog", "setup.cfg"):
            shutil.copy2(PROJECT_ROOT / name, self.repository / name)

    def _git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self._run_in(self.repository, *arguments)

    def _run_in(
        self, repository: Path, *arguments: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(repository / COMMAND.name), *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
        )

    def _commit_all(self, message: str) -> None:
        self._git("add", ".")
        self._git("commit", "--quiet", "--no-gpg-sign", "-m", message)

    def test_create_manifest_records_every_runner_owned_release_identity(self) -> None:
        completed = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        manifest = json.loads(completed.stdout)
        self.assertEqual(manifest["release_format_version"], "catalog-release-v1")
        self.assertEqual(manifest["repository"]["tag"], "catalog-v1")
        self.assertRegex(manifest["runner"]["commit"], r"^[0-9a-f]{40}$")
        self.assertEqual(manifest["runner"]["package_version"], "0.1.0")
        self.assertEqual(
            manifest["catalog"]["path"],
            "language_environments/catalog-v1/catalog.json",
        )
        self.assertEqual(
            manifest["catalog"]["identity"],
            "rps-language-environment-catalog-v1@sha256:"
            "d105931abfa77b3e0dc67bf6f6b71e2fc0b0cede4b99ae05decd9b7c54688231",
        )
        self.assertEqual(
            set(manifest["catalog"]["assets"]),
            {
                "contract-fixture.base_runtime",
                "contract-fixture.build_toolchain",
                "contract-fixture.build_target",
                "contract-fixture.conformance",
                "contract-fixture.dependency_definition",
                "contract-fixture.entrypoint",
                "contract-fixture.platform",
                "contract-fixture.readiness",
                "contract-fixture.recipe",
                "contract-fixture.workflow",
                "contract-fixture.wrapper",
                "go.base_runtime",
                "go.build_toolchain",
                "go.build_target",
                "go.conformance",
                "go.dependency_definition",
                "go.entrypoint",
                "go.platform",
                "go.readiness",
                "go.recipe",
                "go.workflow",
                "go.wrapper",
                "java.base_runtime",
                "java.build_toolchain",
                "java.build_target",
                "java.conformance",
                "java.dependency_definition",
                "java.entrypoint",
                "java.platform",
                "java.readiness",
                "java.recipe",
                "java.workflow",
                "java.wrapper",
                "csharp.base_runtime",
                "csharp.build_toolchain",
                "csharp.build_target",
                "csharp.conformance",
                "csharp.dependency_definition",
                "csharp.entrypoint",
                "csharp.platform",
                "csharp.readiness",
                "csharp.recipe",
                "csharp.workflow",
                "csharp.wrapper",
                "typescript.base_runtime",
                "typescript.build_toolchain",
                "typescript.build_target",
                "typescript.conformance",
                "typescript.dependency_definition",
                "typescript.entrypoint",
                "typescript.platform",
                "typescript.readiness",
                "typescript.recipe",
                "typescript.workflow",
                "typescript.wrapper",
                "internal-shell.base_runtime",
                "internal-shell.build_toolchain",
                "internal-shell.build_target",
                "internal-shell.conformance",
                "internal-shell.dependency_definition",
                "internal-shell.entrypoint",
                "internal-shell.platform",
                "internal-shell.readiness",
                "internal-shell.recipe",
                "internal-shell.workflow",
                "internal-shell.wrapper",
                "python.base_runtime",
                "python.build_toolchain",
                "python.build_target",
                "python.conformance",
                "python.dependency_definition",
                "python.entrypoint",
                "python.platform",
                "python.readiness",
                "python.recipe",
                "python.workflow",
                "python.wrapper",
            },
        )
        self.assertEqual(
            manifest["execution_profile"]["identity"],
            "docker-execution-v1@sha256:"
            "54b69b7eae0b15191a13b2b14fcc75c4537358b971b8f84a65731589b8ad3bb1",
        )
        self.assertEqual(
            manifest["certification_suites"],
            {
                "internal-shell": "internal-shell-artifact-conformance-v1@sha256:"
                "664168210a06c8e77b15e9166e2ee394ad1f0bff05e7d31e8014361110c94f9e",
                "go": "go-artifact-conformance-v1@sha256:"
                "d791f1719d0becbcb1b36bf4f94a006484637d8762685d9b7471ca1f8f39c1e8",
                "java": "java-artifact-conformance-v1@sha256:"
                "f29543b7644c0a65dc46ed3c88e5215b5177a2434f156f27130e81c613d4aa3f",
                "csharp": "csharp-artifact-conformance-v1@sha256:"
                "a1715ef34a2bfef92976a30ac490d498e913cbf2ae0ad4f1a8b4ae8235b98c6f",
                "python": "python-artifact-conformance-v1@sha256:"
                "0541ac0e19bedc42241e65ffb462d894833c6c30d268fa054162bdff8615c057",
                "typescript": "typescript-artifact-conformance-v1@sha256:"
                "dddd1c15d1d0f2bf87677f71bb4fc18b7f72965a213121ef0d226914efbeb9ed",
            },
        )
        self.assertEqual(
            set(manifest["platform_runtimes"]),
            {"csharp", "go", "java", "python", "typescript"},
        )
        python_runtimes = manifest["platform_runtimes"]["python"]
        self.assertEqual(
            python_runtimes["selection"]["policy"],
            "latest-upstream-supported-stable",
        )
        self.assertEqual(
            python_runtimes["selection"]["python_version"], "3.14.6"
        )
        self.assertEqual(
            manifest["platform_runtimes"]["java"]["selection"]["policy"],
            "latest-upstream-supported-lts",
        )
        self.assertEqual(
            manifest["platform_runtimes"]["csharp"]["selection"]["sdk_version"],
            "10.0.302",
        )
        for platform in ("linux/amd64", "linux/arm64"):
            runtime = python_runtimes["platforms"][platform]
            self.assertRegex(
                runtime["build_toolchain"]["digest"], r"^sha256:[0-9a-f]{64}$"
            )
            self.assertRegex(
                runtime["execution_runtime"]["digest"], r"^sha256:[0-9a-f]{64}$"
            )
        self.assertRegex(
            manifest["offline_bundle"]["identity"],
            r"^rps-runner-offline-bundle-v1@sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            manifest["compatibility_coordinates"],
            {
                "format_version": "rps-catalog-compatibility-v1",
                "runner": manifest["runner"],
                "catalog": {
                    "path": manifest["catalog"]["path"],
                    "identity": manifest["catalog"]["identity"],
                    "assets": manifest["catalog"]["assets"],
                },
                "offline_bundle": manifest["offline_bundle"],
            },
        )

    def test_create_rejects_a_mutable_ci_action_reference(self) -> None:
        workflow = self.repository / ".github/workflows/python-39-compatibility.yml"
        workflow.write_text(
            workflow.read_text().replace(
                "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683",
                "actions/checkout@main",
            )
        )
        self._commit_all("use mutable action")

        completed = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mutable action ref", completed.stderr)

    def test_annotated_tag_and_bundle_verify_from_a_clean_clone_offline(self) -> None:
        created = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        manifest = json.loads(created.stdout)
        self.assertEqual(self._git("cat-file", "-t", "catalog-v1"), "tag")
        self.assertEqual(
            self._git("rev-parse", "catalog-v1^{}"), manifest["runner"]["commit"]
        )

        clean_clone = Path(self.temporary_directory.name) / "clean-clone"
        subprocess.run(
            ["git", "clone", "--quiet", str(self.repository), str(clean_clone)],
            check=True,
        )
        verified = self._run_in(
            clean_clone, "verify", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertEqual(json.loads(verified.stdout), manifest)

        restored = Path(self.temporary_directory.name) / "offline-runner"
        subprocess.run(
            ["git", "clone", "--quiet", str(self.bundle), str(restored)],
            check=True,
            env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
        )
        restored_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=restored,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(restored_commit, manifest["runner"]["commit"])
        restored_identity = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "from rps_runner.language_environment import load_catalog; "
                "print(load_catalog(Path('language_environments/catalog-v1/catalog.json')).identity)",
            ],
            cwd=restored,
            check=True,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},
        ).stdout.strip()
        self.assertEqual(restored_identity, manifest["catalog"]["identity"])

    def test_release_operations_reject_a_dirty_repository(self) -> None:
        (self.repository / "untracked.txt").write_text("dirty\n")

        completed = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("repository must be clean", completed.stderr)

    def test_create_rejects_missing_or_drifted_catalog_assets(self) -> None:
        wrapper = self.repository / "language_environments/catalog-v1/python/wrapper.py"
        wrapper.write_text(wrapper.read_text() + "\n# drift\n")
        self._commit_all("drift catalog asset")

        completed = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("does not match", completed.stderr)

        wrapper.unlink()
        self._commit_all("remove catalog asset")
        completed = self._run(
            "create", "catalog-v2", "--bundle", str(self.bundle) + ".missing"
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("could not read", completed.stderr)

    def test_verify_rejects_bundle_drift_and_a_tag_on_the_wrong_commit(self) -> None:
        created = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertEqual(created.returncode, 0, created.stderr)

        with self.bundle.open("ab") as stream:
            stream.write(b"drift")
        drifted = self._run(
            "verify", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertNotEqual(drifted.returncode, 0)
        self.assertIn("release manifest does not match", drifted.stderr)

        self.bundle.write_bytes(self.bundle.read_bytes()[: -len(b"drift")])
        self._git("commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "next")
        wrong_commit = self._run(
            "verify", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertNotEqual(wrong_commit.returncode, 0)
        self.assertIn("wrong Runner commit", wrong_commit.stderr)

    def test_verify_rejects_a_lightweight_release_tag(self) -> None:
        created = self._run(
            "create", "catalog-v1", "--bundle", str(self.bundle)
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self._git("tag", "--delete", "catalog-v1")
        self._git("tag", "catalog-v1")

        completed = self._run(
            "verify", "catalog-v1", "--bundle", str(self.bundle)
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Catalog Release failure", completed.stderr)

    def test_ci_retains_the_integrated_independence_proof(self) -> None:
        workflow = (
            PROJECT_ROOT / ".github/workflows/catalog-release-contract.yml"
        ).read_text()

        self.assertIn("./freeze-tournament-catalog prove", workflow)
        self.assertIn("catalog-independence-evidence.json", workflow)
        self.assertIn("catalog-release-notes.md", workflow)
        self.assertIn("JavaLanguageEnvironmentDockerTests", workflow)
        self.assertIn("CSharpLanguageEnvironmentDockerTests", workflow)
        self.assertIn("RPS_DOCKER_PLATFORM: linux/amd64", workflow)
        self.assertRegex(
            workflow,
            r"uses: actions/upload-artifact@[0-9a-f]{40}",
        )
        self.assertIn("retention-days: 90", workflow)


class CatalogIndependenceProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.repository = self.root / "runner"
        self.bundle = self.root / "catalog-release.bundle"
        self.evidence = self.root / "catalog-independence.json"
        self.release_notes = self.root / "catalog-release.md"
        shutil.copytree(
            PROJECT_ROOT,
            self.repository,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                ".scratch",
                "node_modules",
                "__pycache__",
                "*.pyc",
            ),
        )
        self._git("init", "--quiet")
        self._git("config", "user.email", "catalog-proof@example.invalid")
        self._git("config", "user.name", "Catalog Independence Proof")
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "catalog proof checkout"
        )

    def _git(self, *arguments: str) -> str:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _prove(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(self.repository / COMMAND.name),
                "prove",
                "catalog-proof-v1",
                "--bundle",
                str(self.bundle),
                "--evidence",
                str(self.evidence),
                "--release-notes",
                str(self.release_notes),
            ],
            cwd=self.repository,
            capture_output=True,
            text=True,
            timeout=180,
        )

    def test_clean_isolated_checkout_retains_complete_independence_evidence(
        self,
    ) -> None:
        unrelated_checkout = (
            self.repository / ".github/workflows/unrelated-checkout.yml"
        )
        unrelated_checkout.write_text(
            "steps:\n"
            "  - uses: actions/checkout@"
            "11bd71901bbe5b1630ceea73d27597364c9af683\n"
            "    with:\n"
            "      repository: example/unrelated-tools\n"
        )
        self._git("add", ".")
        self._git(
            "commit",
            "--quiet",
            "--no-gpg-sign",
            "-m",
            "add unrelated external checkout",
        )

        completed = self._prove()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        evidence = json.loads(self.evidence.read_text())
        self.assertEqual(
            evidence["evidence_format_version"],
            "runner-catalog-independence-v1",
        )
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(
            evidence["compatibility_coordinates"],
            evidence["catalog_release"]["manifest"][
                "compatibility_coordinates"
            ],
        )
        self.assertEqual(
            evidence["compatibility_coordinates"]["catalog"]["identity"],
            evidence["catalog_release"]["manifest"]["catalog"]["identity"],
        )
        manifest = evidence["catalog_release"]["manifest"]
        notes = self.release_notes.read_text()
        self.assertIn("# Catalog Release catalog-proof-v1", notes)
        self.assertIn("## Compatibility coordinates", notes)
        self.assertIn(
            json.dumps(manifest["compatibility_coordinates"], indent=2, sort_keys=True),
            notes,
        )
        self.assertIn("## Python Team Template build toolchains", notes)
        self.assertIn("## Go Team Template build toolchains", notes)
        self.assertIn("## Java Team Template build toolchains", notes)
        self.assertIn("## C# Team Template build toolchains", notes)
        self.assertIn("## TypeScript Team Template build toolchains", notes)
        for language in ("csharp", "go", "java", "python", "typescript"):
            for platform in ("linux/amd64", "linux/arm64"):
                build = manifest["platform_runtimes"][language]["platforms"][platform][
                    "build_toolchain"
                ]
                self.assertIn(platform, notes)
                self.assertIn(build["reference"], notes)
                self.assertIn(build["version"], notes)
        self.assertEqual(
            evidence["repository_scan"]["companion_repository"], "absent"
        )
        self.assertEqual(
            evidence["repository_scan"]["dependency_matches"], []
        )
        for scanned_path in (
            ".github/workflows/unrelated-checkout.yml",
            "language_environments/catalog-v1/python/workflow.yml",
            "rps_runner/presentation/assets/app.js",
            "tests/browser/presentation.spec.js",
        ):
            with self.subTest(scanned_path=scanned_path):
                self.assertIn(
                    scanned_path,
                    evidence["repository_scan"]["dependency_surfaces"],
                )
        self.assertEqual(
            evidence["catalog_release"]["participant_template_asset_paths"], []
        )
        self.assertEqual(
            evidence["catalog_release"]["unowned_catalog_paths"], []
        )
        self.assertEqual(
            evidence["catalog_release"]["participant_template_paths"], []
        )
        self.assertEqual(
            evidence["catalog_release"]["participant_template_digest_fields"],
            [],
        )
        self.assertEqual(evidence["organizer_workflows"]["status"], "passed")
        self.assertEqual(
            evidence["organizer_workflows"]["checkout_source"],
            "offline_bundle",
        )
        self.assertEqual(
            set(evidence["organizer_workflows"]["test_files"]),
            {
                "tests/test_prepare_cli.py",
                "tests/test_source_validation_cli.py",
                "tests/test_artifact_builder_cli.py",
                "tests/test_artifact_certification_cli.py",
                "tests/test_multi_language_environment.py",
                "tests/test_csharp_language_environment.py",
                "tests/test_java_language_environment.py",
                "tests/test_typescript_language_environment.py",
                "tests/test_batch_plan_cli.py",
                "tests/test_tournament_plan_cli.py",
                "tests/test_tournament_cli.py",
                "tests/test_rehearsal_cli.py",
                "tests/test_presentation.py",
                "tests/test_presentation_cli.py",
            },
        )
        self.assertEqual(
            evidence["internal_practice_fixtures"]["participant_command_exposed"],
            False,
        )
        self.assertRegex(
            evidence["internal_practice_fixtures"]["module_identity"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            evidence["internal_practice_fixtures"]["offline_module_identity"],
            evidence["internal_practice_fixtures"]["module_identity"],
        )
        self.assertEqual(
            evidence["internal_practice_fixtures"]["offline_reproducible"],
            True,
        )
        self.assertEqual(json.loads(completed.stdout), evidence)

    def test_proof_rejects_a_companion_checkout_or_active_dependency(self) -> None:
        companion_name = "rps-" + "bot-templates"
        companion = self.root / companion_name
        companion.mkdir()

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("without the companion repository", completed.stderr)
        self.assertFalse(self.bundle.exists())
        companion.rmdir()

        workflow = self.repository / ".github/workflows/companion.yml"
        workflow.write_text(
            "steps:\n"
            "  - uses: actions/checkout@"
            "11bd71901bbe5b1630ceea73d27597364c9af683\n"
            "    with:\n"
            "      repository: example/"
            + companion_name
            + "\n"
        )
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "add reverse dependency"
        )

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("dependency surfaces", completed.stderr)
        self.assertIn(".github/workflows/companion.yml", completed.stderr)
        self.assertFalse(self.bundle.exists())

    def test_proof_rejects_participant_template_paths_in_the_runner(self) -> None:
        participant_source = self.repository / "team_source/strategy.py"
        participant_source.parent.mkdir()
        participant_source.write_text(
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return 'R'\n"
        )
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "add participant starter"
        )

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Team Template paths remain", completed.stderr)
        self.assertIn("team_source/strategy.py", completed.stderr)
        self.assertFalse(self.bundle.exists())

    def test_proof_rejects_an_undeclared_file_in_the_catalog_tree(self) -> None:
        participant_source = (
            self.repository
            / "language_environments/catalog-v1/python/starter-strategy.py"
        )
        participant_source.write_text("def choose_move():\n    return 'R'\n")
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "add undeclared starter"
        )

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("undeclared paths", completed.stderr)
        self.assertIn("python/starter-strategy.py", completed.stderr)

    def test_proof_rejects_a_companion_module_import_without_a_repo_path(
        self,
    ) -> None:
        companion_module = "catalog_" + "compatibility"
        injected = self.repository / "rps_runner/reverse_dependency.py"
        injected.write_text("import " + companion_module + "\n")
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "add reverse import"
        )

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("dependency surfaces", completed.stderr)
        self.assertIn("rps_runner/reverse_dependency.py", completed.stderr)

    def test_proof_rejects_a_neutral_path_submodule_of_the_companion(self) -> None:
        companion_name = "rps-" + "bot-templates"
        modules = self.repository / ".gitmodules"
        modules.write_text(
            '[submodule "vendor/adapter"]\n'
            "  path = vendor/adapter\n"
            "  url = ../"
            + companion_name
            + "\n"
        )
        self._git("add", ".")
        self._git(
            "commit", "--quiet", "--no-gpg-sign", "-m", "add reverse submodule"
        )

        completed = self._prove()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("dependency surfaces", completed.stderr)
        self.assertIn(".gitmodules", completed.stderr)


if __name__ == "__main__":
    unittest.main()
