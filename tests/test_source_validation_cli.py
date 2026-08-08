from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


class SourceValidationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_cli(
        self,
        source: Path,
        bundle: Path,
        *,
        environment: str = "python",
        catalog: Path = CATALOG,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "rps_runner.source_cli",
                "--catalog",
                str(catalog),
                "--environment",
                environment,
                "--source",
                str(source),
                "--bundle",
                str(bundle),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def valid_python_source(self, name: str) -> Path:
        source = self.directory / name
        (source / "helpers").mkdir(parents=True)
        (source / "resources").mkdir()
        (source / "strategy.py").write_text(
            "from helpers.moves import move\n\n"
            "def choose_move(turn, my_history, opponent_history, rng):\n"
            "    return move\n"
        )
        (source / "helpers" / "__init__.py").write_text("")
        (source / "helpers" / "moves.py").write_text("move = 'R'\n")
        (source / "resources" / "moves.json").write_text('{"move": "R"}\n')
        return source

    def read_result(
        self, completed: subprocess.CompletedProcess[str]
    ) -> dict[str, Any]:
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def write_catalog(self, data: dict[str, Any], name: str) -> Path:
        directory = self.directory / name
        shutil.copytree(CATALOG.parent, directory)
        catalog = directory / "catalog.json"
        catalog.write_text(json.dumps(data))
        return catalog

    def test_valid_python_source_is_frozen_with_a_deterministic_identity(self) -> None:
        first_source = self.valid_python_source("first")
        second_source = self.valid_python_source("second")
        os.utime(second_source / "strategy.py", (1, 1))

        first_bundle = self.directory / "first-bundle"
        second_bundle = self.directory / "second-bundle"
        first = self.read_result(self.run_cli(first_source, first_bundle))
        second = self.read_result(self.run_cli(second_source, second_bundle))

        self.assertEqual(first["source_digest"], second["source_digest"])
        self.assertRegex(first["source_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(first["environment"], "python")
        self.assertEqual(first["participant_contract"]["callable"], "choose_move")
        expected_versions = {
                "base_runtime": "python-runtime-v1",
                "build_target": "python-build-target-v1",
                "catalog": "rps-language-environment-catalog-v1",
                "conformance": "python-conformance-v1",
                "dependency_definition": "python-dependencies-v1",
                "descriptor": "python-language-environment-v1",
                "entrypoint": "python-entrypoint-v1",
                "platform": "oci-platforms-v1",
                "readiness": "wrapper-readiness-v1",
                "recipe": "python-build-recipe-v1",
                "source_schema": "python-source-schema-v1",
                "workflow": "source-validation-workflow-v1",
                "wrapper": "python-wrapper-v1",
            }
        self.assertEqual(set(first["versions"]), set(expected_versions))
        for identity_name, version in expected_versions.items():
            self.assertRegex(
                first["versions"][identity_name],
                "^" + version + r"@sha256:[0-9a-f]{64}$",
            )
        self.assertEqual((first_bundle / "source" / "strategy.py").read_bytes(),
                         (first_source / "strategy.py").read_bytes())
        self.assertFalse(
            stat.S_IMODE((first_bundle / "source" / "strategy.py").stat().st_mode)
            & stat.S_IWUSR
        )
        self.assertEqual(
            json.loads((first_bundle / "source-bundle.json").read_text()), first
        )

    def test_existing_bundle_is_not_replaced(self) -> None:
        source = self.valid_python_source("source")
        bundle = self.directory / "bundle"
        bundle.mkdir()
        marker = bundle / "keep.txt"
        marker.write_text("keep")

        completed = self.run_cli(source, bundle)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("bundle already exists", completed.stderr)
        self.assertEqual(marker.read_text(), "keep")

    def test_contract_only_descriptor_uses_the_same_public_path(self) -> None:
        source = self.directory / "contract-source"
        source.mkdir()
        (source / "strategy.contract").write_text("move=R\n")

        result = self.read_result(
            self.run_cli(
                source,
                self.directory / "contract-bundle",
                environment="contract-fixture",
            )
        )

        self.assertEqual(result["environment"], "contract-fixture")
        self.assertTrue(result["contract_only"])
        self.assertRegex(
            result["versions"]["descriptor"],
            r"^contract-fixture-v1@sha256:[0-9a-f]{64}$",
        )

    def test_forbidden_infrastructure_file_names_are_actionable(self) -> None:
        forbidden_paths = [
            "Dockerfile",
            "requirements.txt",
            "Makefile",
            "entrypoint.sh",
            "wrapper.py",
            ".github/workflows/validate.yml",
        ]

        for index, relative_path in enumerate(forbidden_paths):
            with self.subTest(path=relative_path):
                source = self.valid_python_source("forbidden-" + str(index))
                path = source / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("participant controlled\n")

                completed = self.run_cli(
                    source, self.directory / ("forbidden-bundle-" + str(index))
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(repr(relative_path), completed.stderr)
                self.assertIn("forbidden infrastructure path", completed.stderr)
                self.assertIn("rule: forbidden_paths", completed.stderr)

    def test_unsupported_file_type_names_the_path_and_rule(self) -> None:
        source = self.valid_python_source("unsupported")
        (source / "strategy.exe").write_bytes(b"binary")

        completed = self.run_cli(source, self.directory / "bundle")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("'strategy.exe'", completed.stderr)
        self.assertIn("unsupported file type", completed.stderr)
        self.assertIn("rule: allowed_files", completed.stderr)

    def test_symlinks_reject_relative_and_absolute_targets(self) -> None:
        outside = self.directory / "outside.py"
        outside.write_text("secret\n")
        targets = ["../outside.py", str(outside)]

        for index, target in enumerate(targets):
            with self.subTest(target=target):
                source = self.valid_python_source("symlink-" + str(index))
                (source / "escape.py").symlink_to(target)

                completed = self.run_cli(
                    source, self.directory / ("symlink-bundle-" + str(index))
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("'escape.py'", completed.stderr)
                self.assertIn("symbolic link", completed.stderr)
                self.assertIn("rule: no_symlinks", completed.stderr)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_special_files_are_rejected_as_non_regular(self) -> None:
        source = self.valid_python_source("special-file")
        os.mkfifo(source / "pipe.py")

        completed = self.run_cli(source, self.directory / "bundle")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("'pipe.py'", completed.stderr)
        self.assertIn("only regular files", completed.stderr)
        self.assertIn("rule: regular_files", completed.stderr)

    def test_catalog_identity_changes_when_catalog_content_changes(self) -> None:
        source = self.valid_python_source("source")
        first = self.read_result(self.run_cli(source, self.directory / "first"))
        catalog_data = json.loads(CATALOG.read_text())
        catalog_data["environments"]["python"]["source_schema"][
            "max_file_count"
        ] = 63
        catalog = self.write_catalog(catalog_data, "changed-catalog")

        second = self.read_result(
            self.run_cli(source, self.directory / "second", catalog=catalog)
        )

        self.assertNotEqual(first["catalog_digest"], second["catalog_digest"])
        self.assertNotEqual(
            first["versions"]["catalog"], second["versions"]["catalog"]
        )
        self.assertNotEqual(
            first["versions"]["descriptor"], second["versions"]["descriptor"]
        )
        self.assertNotEqual(
            first["versions"]["source_schema"],
            second["versions"]["source_schema"],
        )
        self.assertEqual(
            first["versions"]["wrapper"], second["versions"]["wrapper"]
        )

    def test_catalog_rejects_traversal_and_absolute_source_patterns(self) -> None:
        source = self.valid_python_source("source")
        invalid_patterns = ["../escape.py", "/absolute.py", "folder\\windows.py"]

        for index, pattern in enumerate(invalid_patterns):
            with self.subTest(pattern=pattern):
                catalog_data = json.loads(CATALOG.read_text())
                catalog_data["environments"]["python"]["source_schema"][
                    "allowed_files"
                ].append(pattern)
                catalog = self.write_catalog(
                    catalog_data, "unsafe-catalog-" + str(index)
                )

                completed = self.run_cli(
                    source,
                    self.directory / ("unsafe-bundle-" + str(index)),
                    catalog=catalog,
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("safe relative POSIX path", completed.stderr)

    def test_catalog_rejects_tampered_organizer_owned_assets(self) -> None:
        source = self.valid_python_source("source")
        catalog_data = json.loads(CATALOG.read_text())
        catalog = self.write_catalog(catalog_data, "tampered-catalog")
        (catalog.parent / "python" / "wrapper.py").write_text("tampered\n")

        completed = self.run_cli(source, self.directory / "bundle", catalog=catalog)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("'python/wrapper.py'", completed.stderr)
        self.assertIn("does not match", completed.stderr)

    def test_python_strategy_must_define_the_choose_move_contract(self) -> None:
        invalid_strategies = [
            "",
            "def choose_move(:\n    pass\n",
            "def another_function():\n    pass\n",
            "def choose_move(turn, history):\n    return 'R'\n",
        ]

        for index, content in enumerate(invalid_strategies):
            with self.subTest(content=content):
                source = self.valid_python_source("invalid-contract-" + str(index))
                (source / "strategy.py").write_text(content)

                completed = self.run_cli(
                    source, self.directory / ("invalid-contract-bundle-" + str(index))
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("'strategy.py'", completed.stderr)
                self.assertIn("rule: participant_contract", completed.stderr)

    def test_file_count_individual_and_aggregate_limits_are_enforced(self) -> None:
        cases = [
            ("max_file_count", {"extra.py": b"x", "other.py": b"x"}, 2),
            ("max_file_bytes", {"extra.py": b"12345"}, 4),
            ("max_total_bytes", {"extra.py": b"1234", "other.py": b"1234"}, 7),
        ]

        for index, (rule, files, limit) in enumerate(cases):
            with self.subTest(rule=rule):
                source = self.directory / ("limited-" + str(index))
                source.mkdir()
                (source / "strategy.py").write_bytes(b"x")
                for name, content in files.items():
                    (source / name).write_bytes(content)
                catalog_data = json.loads(CATALOG.read_text())
                catalog_data["environments"]["python"]["source_schema"][rule] = limit
                catalog = self.write_catalog(
                    catalog_data, "limited-catalog-" + str(index)
                )

                completed = self.run_cli(
                    source,
                    self.directory / ("limited-bundle-" + str(index)),
                    catalog=catalog,
                )

                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("rule: " + rule, completed.stderr)
                self.assertIn("source validation failed", completed.stderr)


if __name__ == "__main__":
    unittest.main()
