import configparser
import importlib
from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_PYTHON = (3, 9)
PUBLIC_COMMAND_MODULES = (
    "rps_runner.cli",
    "rps_runner.tournament_cli",
    "rps_runner.certification_cli",
    "rps_runner.prepare_cli",
    "rps_runner.batch_plan_cli",
    "rps_runner.rehearsal_cli",
    "rps_runner.tournament.capacity",
)


class PythonCompatibilityTests(unittest.TestCase):
    def test_public_commands_import_on_supported_python(self) -> None:
        self.assertGreaterEqual(sys.version_info[:2], MINIMUM_PYTHON)

        for module_name in PUBLIC_COMMAND_MODULES:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_documentation_and_package_metadata_declare_python_39(self) -> None:
        configuration = configparser.ConfigParser()
        configuration.read(PROJECT_ROOT / "setup.cfg")

        self.assertEqual(configuration["options"]["python_requires"], ">=3.9")
        self.assertIn(
            "Python 3.9 or newer",
            (PROJECT_ROOT / "README.md").read_text(),
        )


if __name__ == "__main__":
    unittest.main()
