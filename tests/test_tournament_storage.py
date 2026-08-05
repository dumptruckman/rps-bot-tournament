from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rps_runner.tournament.storage import (
    IntegrityError,
    ManifestAlreadySealedError,
    RecordSequenceError,
    append_competition_record,
    append_operational_telemetry,
    canonical_json_bytes,
    committed_match_ids,
    is_match_committed,
    load_competition_records,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    seal_manifest,
    write_scoreboard_projection,
)


class CanonicalJsonTests(unittest.TestCase):
    def test_serialization_has_stable_utf8_bytes_and_key_order(self) -> None:
        value = {"z": [3, 2, 1], "message": "café", "a": {"two": 2, "one": 1}}

        serialized = canonical_json_bytes(value)

        self.assertEqual(
            serialized,
            b'{"a":{"one":1,"two":2},"message":"caf\xc3\xa9","z":[3,2,1]}',
        )


class TournamentManifestTests(unittest.TestCase):
    manifest = {
        "tournament_id": "cup-2026",
        "seed": "42",
        "record_schema_version": 1,
    }

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_seal_writes_known_canonical_bytes_and_checksum(self) -> None:
        sealed = seal_manifest(self.directory, self.manifest)

        self.assertEqual(
            sealed.checksum,
            "c84ea946e670efe1699d5ff373325c7c50b3be4720bf5f614d1263dbb3c5aa2d",
        )
        self.assertEqual(
            (self.directory / "manifest.json").read_bytes(),
            b'{"checksum":"c84ea946e670efe1699d5ff373325c7c50b3be4720bf5f614d1263dbb3'
            b'c5aa2d",'
            b'"manifest":{"record_schema_version":1,"seed":"42",'
            b'"tournament_id":"cup-2026"}}',
        )
        self.assertEqual(load_manifest(self.directory), sealed)

    def test_sealed_manifest_cannot_be_replaced(self) -> None:
        seal_manifest(self.directory, self.manifest)

        with self.assertRaises(ManifestAlreadySealedError):
            seal_manifest(self.directory, self.manifest | {"seed": "43"})

        self.assertEqual(load_manifest(self.directory).manifest, self.manifest)

    def test_load_rejects_manifest_with_changed_canonical_facts(self) -> None:
        seal_manifest(self.directory, self.manifest)
        path = self.directory / "manifest.json"
        path.chmod(0o644)
        path.write_bytes(path.read_bytes().replace(b'"42"', b'"43"'))

        with self.assertRaisesRegex(IntegrityError, "Manifest checksum"):
            load_manifest(self.directory)


class CompetitionRecordTests(unittest.TestCase):
    started = {
        "type": "match_started",
        "match_id": "q-001-m1",
        "fixture_id": "q-001",
    }
    terminal = {
        "type": "match_terminal",
        "match_id": "q-001-m1",
        "outcome": "completed",
        "winner": "red",
    }

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_append_assigns_canonical_sequence_and_known_content_hash(self) -> None:
        stored = append_competition_record(self.directory, self.started)

        self.assertEqual(stored.sequence, 1)
        self.assertEqual(
            stored.content_hash,
            "9018955a920f026e88ed0f23869e7bb1d29493187aaf644e8133505d877722f6",
        )
        self.assertEqual(
            (self.directory / "records" / "00000001.json").read_bytes(),
            b'{"content_hash":"9018955a920f026e88ed0f23869e7bb1d29493187aaf644e8133505'
            b'd877722f6",'
            b'"record":{"fixture_id":"q-001","match_id":"q-001-m1",'
            b'"type":"match_started"},"sequence":1}',
        )
        self.assertEqual(load_competition_records(self.directory), [stored])

    def test_terminal_record_is_the_match_commit_boundary(self) -> None:
        append_competition_record(self.directory, self.started)
        self.assertFalse(is_match_committed(self.directory, "q-001-m1"))

        terminal = append_competition_record(self.directory, self.terminal)

        self.assertEqual(terminal.sequence, 2)
        self.assertEqual(
            terminal.content_hash,
            "3f491d64739e972b785cc909f95c3b3f632b401d01ce9dabea4d8f4b35a10a00",
        )
        self.assertTrue(is_match_committed(self.directory, "q-001-m1"))
        self.assertEqual(committed_match_ids(self.directory), {"q-001-m1"})

    def test_load_detects_a_missing_last_record(self) -> None:
        append_competition_record(self.directory, self.started)
        (self.directory / "records" / "00000001.json").unlink()

        with self.assertRaisesRegex(RecordSequenceError, "count"):
            load_competition_records(self.directory)

    def test_load_rejects_noncanonical_record_bytes(self) -> None:
        append_competition_record(self.directory, self.started)
        path = self.directory / "records" / "00000001.json"
        path.chmod(0o644)
        path.write_bytes(b"\n" + path.read_bytes())

        with self.assertRaisesRegex(IntegrityError, "canonical"):
            load_competition_records(self.directory)

    def test_variable_telemetry_does_not_change_canonical_record(self) -> None:
        sealed = seal_manifest(
            self.directory,
            {"record_schema_version": 1, "tournament_id": "cup-2026"},
        )
        manifest_bytes = (self.directory / "manifest.json").read_bytes()
        stored = append_competition_record(self.directory, self.terminal)
        record_path = self.directory / "records" / "00000001.json"
        canonical_bytes = record_path.read_bytes()

        first_sequence = append_operational_telemetry(
            self.directory,
            {
                "match_id": "q-001-m1",
                "attempt": 1,
                "host": "worker-a",
                "stderr": "first run",
                "duration_ns": 1200,
            },
        )
        second_sequence = append_operational_telemetry(
            self.directory,
            {
                "match_id": "q-001-m1",
                "attempt": 2,
                "host": "worker-b",
                "stderr": "different run",
                "duration_ns": 9800,
            },
        )

        self.assertEqual((first_sequence, second_sequence), (1, 2))
        self.assertEqual(
            load_manifest(self.directory).checksum,
            sealed.checksum,
        )
        self.assertEqual(
            (self.directory / "manifest.json").read_bytes(), manifest_bytes
        )
        self.assertEqual(record_path.read_bytes(), canonical_bytes)
        self.assertEqual(
            load_competition_records(self.directory)[0].content_hash,
            stored.content_hash,
        )
        self.assertEqual(
            [entry["host"] for entry in load_operational_telemetry(self.directory)],
            ["worker-a", "worker-b"],
        )

    def test_load_rejects_changed_record_facts_with_old_hash(self) -> None:
        append_competition_record(self.directory, self.terminal)
        path = self.directory / "records" / "00000001.json"
        path.chmod(0o644)
        path.write_bytes(path.read_bytes().replace(b'"red"', b'"blu"'))

        with self.assertRaisesRegex(IntegrityError, "content hash"):
            load_competition_records(self.directory)

    def test_load_rejects_reordered_record_files(self) -> None:
        append_competition_record(self.directory, self.started)
        append_competition_record(self.directory, self.terminal)
        first = self.directory / "records" / "00000001.json"
        second = self.directory / "records" / "00000002.json"
        first_bytes = first.read_bytes()
        second_bytes = second.read_bytes()
        first.chmod(0o644)
        second.chmod(0o644)
        first.write_bytes(second_bytes)
        second.write_bytes(first_bytes)

        with self.assertRaisesRegex(RecordSequenceError, "sequence"):
            load_competition_records(self.directory)


class ScoreboardProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_projection_is_atomically_replaced_without_changing_records(self) -> None:
        sealed = seal_manifest(
            self.directory,
            {"record_schema_version": 1, "tournament_id": "cup-2026"},
        )
        manifest_bytes = (self.directory / "manifest.json").read_bytes()
        record = append_competition_record(
            self.directory,
            {
                "type": "match_terminal",
                "match_id": "q-001-m1",
                "winner": "red",
            },
        )
        canonical_bytes = (
            self.directory / "records" / "00000001.json"
        ).read_bytes()

        write_scoreboard_projection(
            self.directory,
            {"version": 1, "status": "running", "champion": None},
        )
        write_scoreboard_projection(
            self.directory,
            {"version": 1, "status": "complete", "champion": "red"},
        )

        self.assertEqual(
            load_scoreboard_projection(self.directory),
            {"version": 1, "status": "complete", "champion": "red"},
        )
        self.assertEqual(load_manifest(self.directory).checksum, sealed.checksum)
        self.assertEqual(
            (self.directory / "manifest.json").read_bytes(), manifest_bytes
        )
        self.assertEqual(
            (self.directory / "scoreboard.json").read_bytes(),
            b'{"champion":"red","status":"complete","version":1}',
        )
        self.assertEqual(
            load_competition_records(self.directory)[0].content_hash,
            record.content_hash,
        )
        self.assertEqual(
            (self.directory / "records" / "00000001.json").read_bytes(),
            canonical_bytes,
        )
        self.assertEqual(list(self.directory.glob(".scoreboard.json.*")), [])


if __name__ == "__main__":
    unittest.main()
