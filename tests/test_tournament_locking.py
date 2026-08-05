from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import uuid

from rps_runner.tournament.locking import (
    LockOwner,
    TournamentRunLock,
    TournamentRunLockHeldError,
    TournamentRunLockOwnershipError,
)


class TournamentRunLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.tournament_directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_context_manager_records_owner_diagnostics_and_releases(self) -> None:
        with TournamentRunLock(self.tournament_directory) as run_lock:
            record = json.loads(run_lock.lock_path.read_text(encoding="utf-8"))

            self.assertEqual(record["token"], run_lock.owner.token)
            self.assertEqual(record["pid"], os.getpid())
            self.assertEqual(record["hostname"], socket.gethostname())
            self.assertEqual(uuid.UUID(record["token"]).version, 4)
            self.assertTrue(run_lock.lock_path.exists())

        self.assertFalse(run_lock.lock_path.exists())

    def test_second_instance_reports_the_current_owner_without_removing_lock(
        self,
    ) -> None:
        with TournamentRunLock(self.tournament_directory) as first_lock:
            with self.assertRaises(TournamentRunLockHeldError) as caught:
                with TournamentRunLock(self.tournament_directory):
                    self.fail("a second holder entered the protected operation")

            self.assertEqual(caught.exception.lock_path, first_lock.lock_path)
            self.assertEqual(caught.exception.owner, first_lock.owner)
            self.assertTrue(first_lock.lock_path.exists())

    def test_tampered_lock_is_preserved_for_operator_intervention(self) -> None:
        replacement_owner = LockOwner(
            token="00000000-0000-4000-8000-000000000001",
            pid=4242,
            hostname="replacement-host",
        )
        replacement_record = (
            '{"hostname":"replacement-host","pid":4242,'
            '"token":"00000000-0000-4000-8000-000000000001"}'
        )

        with self.assertRaises(TournamentRunLockOwnershipError) as caught:
            with TournamentRunLock(self.tournament_directory) as run_lock:
                run_lock.lock_path.write_text(
                    replacement_record, encoding="utf-8"
                )

        self.assertEqual(caught.exception.expected_owner, run_lock.owner)
        self.assertEqual(caught.exception.observed_owner, replacement_owner)
        self.assertEqual(
            run_lock.lock_path.read_text(encoding="utf-8"), replacement_record
        )

    def test_released_lock_can_be_reacquired_with_a_new_owner_token(self) -> None:
        with TournamentRunLock(self.tournament_directory) as first_lock:
            first_token = first_lock.owner.token

        with TournamentRunLock(self.tournament_directory) as second_lock:
            self.assertNotEqual(second_lock.owner.token, first_token)

    def test_lock_is_released_when_the_protected_operation_raises(self) -> None:
        pending_lock = TournamentRunLock(self.tournament_directory)

        with self.assertRaisesRegex(RuntimeError, "protected operation failed"):
            with pending_lock:
                raise RuntimeError("protected operation failed")

        self.assertFalse(pending_lock.lock_path.exists())

    def test_existing_stale_lock_requires_operator_intervention(self) -> None:
        pending_lock = TournamentRunLock(self.tournament_directory)
        stale_record = (
            '{"hostname":"old-host","pid":99,'
            '"token":"00000000-0000-4000-8000-000000000099"}'
        )
        pending_lock.lock_path.write_text(stale_record, encoding="utf-8")

        with self.assertRaises(TournamentRunLockHeldError) as caught:
            with pending_lock:
                self.fail("a stale lock was silently removed")

        self.assertEqual(
            caught.exception.owner,
            LockOwner(
                token="00000000-0000-4000-8000-000000000099",
                pid=99,
                hostname="old-host",
            ),
        )
        self.assertEqual(
            pending_lock.lock_path.read_text(encoding="utf-8"), stale_record
        )

    def test_lock_contends_across_processes(self) -> None:
        child_program = """
import pathlib
import sys
from rps_runner.tournament.locking import (
    TournamentRunLock,
    TournamentRunLockHeldError,
)

try:
    with TournamentRunLock(pathlib.Path(sys.argv[1])):
        print("acquired")
except TournamentRunLockHeldError as error:
    print(f"held-by:{error.owner.pid}")
"""

        with TournamentRunLock(self.tournament_directory):
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child_program,
                    str(self.tournament_directory),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), f"held-by:{os.getpid()}")


if __name__ == "__main__":
    unittest.main()
