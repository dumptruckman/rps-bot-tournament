from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rps_runner.tournament.storage import (
    IntegrityError,
    ManifestAlreadySealedError,
    RecordSequenceError,
    append_competition_record,
    append_competition_record_to_verified_sequence,
    append_operational_telemetry,
    canonical_json_bytes,
    committed_match_ids,
    is_match_committed,
    load_competition_records,
    load_control_state,
    load_manifest,
    load_operational_telemetry,
    load_scoreboard_projection,
    restore_competition_record,
    seal_manifest,
    initial_control_state,
    update_control_state,
    write_control_state,
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

    def test_sealed_and_loaded_manifest_values_are_deeply_immutable(self) -> None:
        manifest = dict(self.manifest)
        manifest["roster"] = [{"team_id": "red-team", "entrypoint": ["bot.py"]}]

        sealed = seal_manifest(self.directory, manifest)
        path = self.directory / "manifest.json"
        sealed_bytes = path.read_bytes()

        with self.assertRaises(TypeError):
            sealed.manifest["roster"][0]["team_id"] = "blue-team"
        with self.assertRaises(TypeError):
            sealed.manifest["roster"][0]["entrypoint"].append("--changed")
        loaded = load_manifest(self.directory)
        with self.assertRaises(TypeError):
            loaded.manifest["roster"].clear()

        self.assertEqual(path.read_bytes(), sealed_bytes)
        self.assertEqual(loaded.checksum, sealed.checksum)


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

    def test_append_with_verified_sequence_preserves_canonical_bytes(self) -> None:
        first = append_competition_record(self.directory, self.started)

        second = append_competition_record_to_verified_sequence(
            self.directory,
            self.terminal,
            [first],
        )

        self.assertEqual(load_competition_records(self.directory), [first, second])
        self.assertEqual(
            (self.directory / "records" / "00000002.json").read_bytes(),
            b'{"content_hash":"3f491d64739e972b785cc909f95c3b3f632b401d01ce9dabea4d8f4b35a10a00",'
            b'"record":{"match_id":"q-001-m1",'
            b'"outcome":"completed","type":"match_terminal","winner":"red"},'
            b'"sequence":2}',
        )

    def test_append_with_stale_verified_sequence_is_rejected(self) -> None:
        first = append_competition_record(self.directory, self.started)
        append_competition_record_to_verified_sequence(
            self.directory,
            self.terminal,
            [first],
        )

        with self.assertRaisesRegex(RecordSequenceError, "verified sequence"):
            append_competition_record_to_verified_sequence(
                self.directory,
                self.started,
                [first],
            )

    def test_append_with_verified_sequence_rejects_corrupt_prior_payload(self) -> None:
        first = append_competition_record(self.directory, self.started)
        path = self.directory / "records" / "00000001.json"
        path.chmod(0o644)
        path.write_bytes(path.read_bytes().replace(b'"q-001"', b'"q-002"'))

        with self.assertRaisesRegex(IntegrityError, "content hash"):
            append_competition_record_to_verified_sequence(
                self.directory,
                self.terminal,
                [first],
            )

        self.assertFalse(
            (self.directory / "records" / "00000002.json").exists()
        )

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

    def test_appended_and_loaded_records_are_deeply_immutable(self) -> None:
        record = {
            "type": "match_terminal",
            "match_id": "q-001-m1",
            "rounds": [{"turn": 0, "moves": ["R", "S"]}],
        }

        stored = append_competition_record(self.directory, record)
        path = self.directory / "records" / "00000001.json"
        stored_bytes = path.read_bytes()
        stored_hash = stored.content_hash

        with self.assertRaises(TypeError):
            stored.record["rounds"][0]["moves"][0] = "P"
        loaded = load_competition_records(self.directory)[0]
        with self.assertRaises(TypeError):
            loaded.record["rounds"].append({"turn": 1})

        self.assertEqual(path.read_bytes(), stored_bytes)
        self.assertEqual(loaded.content_hash, stored_hash)

    def test_restore_replaces_one_corrupt_record_from_verified_backup(self) -> None:
        stored = append_competition_record(self.directory, self.started)
        record_path = self.directory / "records" / "00000001.json"
        backup_path = self.directory / "record-backup.json"
        backup_bytes = record_path.read_bytes()
        backup_path.write_bytes(backup_bytes)
        record_path.chmod(0o644)
        record_path.write_bytes(backup_bytes.replace(b'"q-001"', b'"q-999"'))

        restored = restore_competition_record(self.directory, backup_path)

        self.assertEqual(restored, stored)
        self.assertEqual(record_path.read_bytes(), backup_bytes)
        self.assertEqual(backup_path.read_bytes(), backup_bytes)
        self.assertEqual(load_competition_records(self.directory), [stored])

    def test_restore_replaces_one_missing_record_bound_by_the_index(self) -> None:
        first = append_competition_record(self.directory, self.started)
        second = append_competition_record(self.directory, self.terminal)
        record_path = self.directory / "records" / "00000002.json"
        backup_path = self.directory / "record-backup.json"
        backup_bytes = record_path.read_bytes()
        backup_path.write_bytes(backup_bytes)
        record_path.unlink()

        restored = restore_competition_record(self.directory, backup_path)

        self.assertEqual(restored, second)
        self.assertEqual(load_competition_records(self.directory), [first, second])
        self.assertEqual(backup_path.read_bytes(), backup_bytes)

    def test_restore_rejects_unverified_or_noncanonical_backup(self) -> None:
        stored = append_competition_record(self.directory, self.started)
        record_path = self.directory / "records" / "00000001.json"
        canonical_backup = record_path.read_bytes()
        record_path.chmod(0o644)
        record_path.write_bytes(b"corrupt")

        invalid_backups: list[tuple[str, bytes, str]] = []
        invalid_backups.append(
            ("noncanonical", b"\n" + canonical_backup, "canonical JSON")
        )
        stale_hash = json.loads(canonical_backup)
        stale_hash["content_hash"] = "0" * 64
        invalid_backups.append(
            ("stale hash", canonical_json_bytes(stale_hash), "content hash")
        )
        wrong_sequence = json.loads(canonical_backup)
        wrong_sequence["sequence"] = 2
        wrong_sequence["content_hash"] = hashlib.sha256(
            canonical_json_bytes(
                {
                    "record": wrong_sequence["record"],
                    "sequence": wrong_sequence["sequence"],
                }
            )
        ).hexdigest()
        invalid_backups.append(
            ("wrong sequence", canonical_json_bytes(wrong_sequence), "index")
        )
        wrong_record = json.loads(canonical_backup)
        wrong_record["record"]["fixture_id"] = "q-999"
        wrong_record["content_hash"] = hashlib.sha256(
            canonical_json_bytes(
                {
                    "record": wrong_record["record"],
                    "sequence": wrong_record["sequence"],
                }
            )
        ).hexdigest()
        invalid_backups.append(
            ("wrong record", canonical_json_bytes(wrong_record), "canonical index")
        )

        for name, backup_bytes, message in invalid_backups:
            with self.subTest(name=name):
                backup_path = self.directory / f"{name}.json"
                backup_path.write_bytes(backup_bytes)
                target_before = record_path.read_bytes()

                with self.assertRaisesRegex(IntegrityError, message):
                    restore_competition_record(self.directory, backup_path)

                self.assertEqual(record_path.read_bytes(), target_before)
                self.assertEqual(backup_path.read_bytes(), backup_bytes)
        self.assertEqual(stored.sequence, 1)

    def test_restore_refuses_to_overwrite_a_healthy_verified_record(self) -> None:
        append_competition_record(self.directory, self.started)
        record_path = self.directory / "records" / "00000001.json"
        backup_path = self.directory / "record-backup.json"
        backup_path.write_bytes(record_path.read_bytes())

        with self.assertRaisesRegex(IntegrityError, "healthy verified"):
            restore_competition_record(self.directory, backup_path)

    def test_restore_rejects_corruption_outside_the_target_or_in_the_index(
        self,
    ) -> None:
        append_competition_record(self.directory, self.started)
        append_competition_record(self.directory, self.terminal)
        first_path = self.directory / "records" / "00000001.json"
        second_path = self.directory / "records" / "00000002.json"
        backup_path = self.directory / "record-backup.json"
        backup_bytes = second_path.read_bytes()
        backup_path.write_bytes(backup_bytes)
        second_path.unlink()
        first_path.chmod(0o644)
        first_path.write_bytes(b"corrupt elsewhere")

        with self.assertRaisesRegex(IntegrityError, "Competition Record"):
            restore_competition_record(self.directory, backup_path)

        self.assertFalse(second_path.exists())
        self.assertEqual(backup_path.read_bytes(), backup_bytes)

        first_path.write_bytes(
            b'{"content_hash":"invalid","record":{},"sequence":1}'
        )
        index_path = self.directory / "records.index.json"
        index_bytes = index_path.read_bytes()
        index_path.write_bytes(b"\n" + index_bytes)
        with self.assertRaisesRegex(IntegrityError, "canonical JSON"):
            restore_competition_record(self.directory, backup_path)
        self.assertFalse(second_path.exists())


class TournamentControlStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_control_state_is_durable_atomic_and_separate_from_competition_records(
        self,
    ) -> None:
        seal_manifest(self.directory, {"tournament_id": "control-cup"})
        manifest_bytes = (self.directory / "manifest.json").read_bytes()
        write_control_state(self.directory, initial_control_state("continuous"))

        updated = update_control_state(
            self.directory,
            lambda control: {
                **control,
                "lifecycle": "running",
                "pause_requested": True,
            },
        )

        self.assertEqual(load_control_state(self.directory), updated)
        self.assertEqual(updated["current_mode"], "continuous")
        self.assertEqual(updated["lifecycle"], "running")
        self.assertFalse(updated["match_active"])
        self.assertTrue(updated["pause_requested"])
        self.assertEqual(
            (self.directory / "manifest.json").read_bytes(), manifest_bytes
        )
        self.assertEqual(load_competition_records(self.directory), [])

    def test_control_state_rejects_unknown_or_malformed_values(self) -> None:
        invalid_states = (
            {**initial_control_state("step"), "current_mode": "parallel"},
            {**initial_control_state("step"), "lifecycle": "active"},
            {**initial_control_state("step"), "pause_requested": 1},
        )
        for state in invalid_states:
            with self.subTest(state=state):
                with self.assertRaises(IntegrityError):
                    write_control_state(self.directory, state)


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
