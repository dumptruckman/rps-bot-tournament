from __future__ import annotations

from io import StringIO
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch
import unittest

from rps_runner.tournament_cli import main


class PresentationCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.stdout = StringIO()
        self.stderr = StringIO()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_present(self, *arguments: str) -> int:
        return main(
            ["present", "--directory", str(self.directory), *arguments],
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def test_present_starts_without_scoreboard_and_prints_bound_url(self) -> None:
        captured: dict[str, object] = {}

        def serve(directory: Path, host: str, port: int, output: StringIO) -> None:
            captured.update(directory=directory, host=host, port=port)
            print("http://127.0.0.1:8765/", file=output)

        with patch("rps_runner.tournament_cli.serve_presentation", serve):
            exit_code = self.run_present("--port", "8765")

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(
            captured,
            {"directory": self.directory.resolve(), "host": "127.0.0.1", "port": 8765},
        )
        self.assertEqual(self.stdout.getvalue(), "http://127.0.0.1:8765/\n")

    def test_present_passes_a_configured_loopback_host(self) -> None:
        captured: dict[str, object] = {}

        def serve(directory: Path, host: str, port: int, output: StringIO) -> None:
            captured.update(host=host, port=port)

        with patch("rps_runner.tournament_cli.serve_presentation", serve):
            exit_code = self.run_present("--host", "127.0.0.2", "--port", "9123")

        self.assertEqual(exit_code, 0, self.stderr.getvalue())
        self.assertEqual(captured, {"host": "127.0.0.2", "port": 9123})

    def test_rejects_missing_directory_and_non_loopback_host(self) -> None:
        missing = self.directory / "missing"
        exit_code = main(
            ["present", "--directory", str(missing)],
            stdout=self.stdout,
            stderr=self.stderr,
        )
        self.assertNotEqual(exit_code, 0)
        self.assertIn("readable Tournament directory", self.stderr.getvalue())

        self.stderr.seek(0)
        self.stderr.truncate(0)
        exit_code = self.run_present("--host", "0.0.0.0")
        self.assertNotEqual(exit_code, 0)
        self.assertIn("loopback", self.stderr.getvalue())

    def test_unavailable_port_is_rejected(self) -> None:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        try:
            exit_code = self.run_present("--port", str(port))
            self.assertNotEqual(exit_code, 0)
            self.assertIn("rps-tournament:", self.stderr.getvalue())
        finally:
            occupied.close()

    def test_unreadable_directory_is_rejected(self) -> None:
        with patch("rps_runner.presentation.server.os.access", return_value=False):
            exit_code = self.run_present()

        self.assertNotEqual(exit_code, 0)
        self.assertIn("readable Tournament directory", self.stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
