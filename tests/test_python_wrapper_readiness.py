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
