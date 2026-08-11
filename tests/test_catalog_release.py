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
            "8724e24a870b6004a01bca95d23059c94cb9abe2c73e15018db2ad0d0a02c181",
        )
        self.assertEqual(
            set(manifest["catalog"]["assets"]),
            {
                "contract-fixture.base_runtime",
                "contract-fixture.build_target",
                "contract-fixture.conformance",
                "contract-fixture.dependency_definition",
                "contract-fixture.entrypoint",
                "contract-fixture.platform",
                "contract-fixture.readiness",
                "contract-fixture.recipe",
                "contract-fixture.workflow",
                "contract-fixture.wrapper",
                "python.base_runtime",
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
                "python": "python-artifact-conformance-v1@sha256:"
                "5122994b6067b438de7b9bc1720cb94296cda3a022dc629bc9269e3f1968e15b"
            },
        )
        self.assertEqual(
            set(manifest["platform_runtimes"]), {"linux/amd64", "linux/arm64"}
        )
        for runtime in manifest["platform_runtimes"].values():
            self.assertRegex(runtime["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(
            manifest["offline_bundle"]["identity"],
            r"^rps-runner-offline-bundle-v1@sha256:[0-9a-f]{64}$",
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


if __name__ == "__main__":
    unittest.main()
