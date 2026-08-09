from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = PROJECT_ROOT / "language_environments" / "catalog-v1" / "python" / "wrapper.py"


class PythonWrapperReadinessTests(unittest.TestCase):
    def test_team_code_sees_only_the_versioned_environment_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.py").write_text(
                "import json\n"
                "import os\n"
                "import sys\n"
                "print(json.dumps(dict(os.environ), sort_keys=True), "
                "file=sys.stderr, flush=True)\n"
                "def choose_move(turn, my_history, opponent_history, rng):\n"
                "    return 'R'\n"
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(source),
                    "HOST_CREDENTIAL": "must-not-leak",
                    "TEAM_ID": "must-not-leak",
                    "RPS_PROTOCOL_VERSION": "1",
                    "RPS_ROUNDS": "1",
                    "RPS_SEED": "7",
                }
            )
            completed = subprocess.run(
                [sys.executable, str(WRAPPER)],
                cwd=source,
                env=environment,
                input=b"0\n-\n-\n",
                capture_output=True,
                timeout=2,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        visible = completed.stderr.splitlines()[0]
        self.assertEqual(
            visible,
            b'{"HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", '
            b'"RPS_PROTOCOL_VERSION": "1", "RPS_ROUNDS": "1", '
            b'"RPS_SEED": "7", "TMPDIR": "/tmp", "TZ": "UTC"}',
        )

    def test_team_import_stderr_cannot_spoof_wrapper_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            source = Path(temporary_name)
            (source / "strategy.py").write_text(
                "import sys\n"
                "print('team-before', file=sys.stderr, flush=True)\n"
                "print('RPS_READY_V1', file=sys.stderr, flush=True)\n"
                "def choose_move(turn, my_history, opponent_history, rng):\n"
                "    return 'R'\n"
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(source),
                    "RPS_PROTOCOL_VERSION": "1",
                    "RPS_ROUNDS": "1",
                    "RPS_SEED": "1",
                }
            )
            completed = subprocess.run(
                [sys.executable, str(WRAPPER)],
                cwd=source,
                env=environment,
                input=b"0\n-\n-\n",
                capture_output=True,
                timeout=2,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, b"R\n")
        self.assertEqual(
            completed.stderr.splitlines(),
            [
                b"team-before",
                b"RPS_STDERR_ESCAPE_V1:RPS_READY_V1",
                b"RPS_READY_V1",
            ],
        )


if __name__ == "__main__":
    unittest.main()
