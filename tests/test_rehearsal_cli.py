from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from io import StringIO

from rps_runner.rehearsal_cli import (
    CORRECTNESS_FAILURE_EXIT_CODE,
    OBJECTIVE_SECONDS,
    TIMING_OBJECTIVE_EXIT_CODE,
    RehearsalOperations,
    main,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT_ROOT / "language_environments" / "catalog-v1" / "catalog.json"


class SequenceClock:
    def __init__(self, values: tuple[float, ...]) -> None:
        self.values = iter(values)

    def __call__(self) -> float:
        return next(self.values)


class RehearsalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sources = []
        for ordinal in range(16):
            source = self.root / f"source-{ordinal + 1:02d}"
            source.mkdir()
            (source / "strategy.py").write_text(
                "def choose_move(history, seed=None):\n    return 'rock'\n"
            )
            self.sources.append(source)
        self.teams = self.root / "teams.json"
        self.teams.write_text(
            json.dumps(
                {
                    "teams": [
                        {
                            "team_id": f"team-{ordinal + 1:02d}",
                            "display_name": f"Team {ordinal + 1:02d}",
                            "source_directory": str(source),
                        }
                        for ordinal, source in enumerate(self.sources)
                    ]
                }
            )
        )
        self.output = self.root / "rehearsal"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def arguments(self) -> list[str]:
        return [
            "--teams",
            str(self.teams),
            "--catalog",
            str(CATALOG),
            "--output",
            str(self.output),
            "--tournament-seed",
            "8675309",
            "--profile",
            "docker-execution-v1",
            "--parallelism",
            "4",
            "--jobs",
            "4",
        ]

    def operations(self) -> RehearsalOperations:
        def inspect_configuration(request: object) -> dict[str, object]:
            self.assertEqual(len(request.organizer_images), 16)
            self.assertEqual(len(request.practice_artifacts), 4)
            return {
                "ready": True,
                "machine": {
                    "identity": "container-host-machine-v1@sha256:" + "a" * 64,
                    "hostname": "m4-max",
                    "architecture": "arm64",
                    "logical_cpus": 16,
                },
                "docker": {
                    "context": "orbstack",
                    "server_version": "27.5.1",
                    "server_platform": "linux/arm64",
                    "engine_identity": "docker-engine-v1@sha256:" + "b" * 64,
                },
            }

        def inspect_target_machine() -> dict[str, object]:
            return {
                "system": "Darwin",
                "architecture": "arm64",
                "logical_cpus": 16,
                "model": "Mac16,5",
                "processor": "Apple M4 Max",
                "memory_bytes": 128 * 1024**3,
            }

        def run_batch(arguments: list[str]) -> int:
            destination = Path(arguments[arguments.index("--output") + 1])
            destination.mkdir(parents=True)
            (destination / "artifact-store").mkdir()
            certification = destination / "teams" / "team-01" / "certification"
            certification.mkdir(parents=True)
            (certification / "validation-report.json").write_text(
                json.dumps(
                    {
                        "smoke_match": {
                            "practice_artifacts": {
                                name: {"cached_image_id": "sha256:" + character * 64}
                                for name, character in zip(
                                    ("fixed-move", "random", "copycat", "protocol-test"),
                                    "4567",
                                )
                            }
                        }
                    }
                )
            )
            plan = {
                "execution": {"mode": "continuous", "parallelism": 4},
                "teams": [
                    {
                        "team_id": f"team-{ordinal + 1:02d}",
                        "bot_artifact_manifest": {
                            "artifact_digest": "sha256:"
                            + format(ordinal + 1, "064x"),
                            "runtime_digest": "sha256:" + "c" * 64,
                            "validation_identity": "validation-report-v1@sha256:"
                            + format(ordinal + 1, "064x"),
                            "retention": {
                                "local_image_id": "sha256:"
                                + format(ordinal + 20, "064x")
                            },
                        },
                    }
                    for ordinal in range(16)
                ],
            }
            (destination / "tournament-plan.json").write_text(json.dumps(plan))
            return 0

        def review_plan(_plan: Path, _store: Path, _catalog: Path) -> dict[str, object]:
            return {
                "team_count": 16,
                "tournament_seed": 8675309,
                "execution_mode": "continuous",
                "parallelism": 4,
                "execution_profile": {
                    "version": "docker-execution-v1",
                    "identity": "docker-execution-v1@sha256:" + "8" * 64,
                },
                "resource_values": {"scheduled_turns_per_match": 300},
                "artifact_identities": [
                    "sha256:" + format(ordinal + 1, "064x")
                    for ordinal in range(16)
                ],
                "runtime_identities": ["sha256:" + "c" * 64],
                "validation_identities": [
                    "validation-report-v1@sha256:" + format(ordinal + 1, "064x")
                    for ordinal in range(16)
                ],
            }

        def prove_archive_restore(
            _plan: Path, _store: Path
        ) -> dict[str, object]:
            return {"selected_images": 16, "restored_images": 16, "status": "passed"}

        def run_tournament(_arguments: list[str]) -> int:
            tournament = self.output / "tournament"
            tournament.mkdir()
            (tournament / "canonical.marker").write_bytes(b"unchanged")
            return 0

        def verify_tournament(_directory: Path) -> dict[str, object]:
            return {
                "status": "complete",
                "scheduled_turns_per_match": 300,
                "fixture_count": 123,
                "match_count": 369,
                "all_series_used_three_matches": True,
                "competition_records_verified": True,
                "operational_telemetry_verified": True,
                "scoreboard_projection_verified": True,
                "state_reconstruction_verified": True,
                "timing_isolation_verified": True,
                "tournament_champion": "team-01",
                "canonical_no_champion": False,
                "competition_state_identity": "sha256:" + "d" * 64,
            }

        return RehearsalOperations(
            inspect_configuration=inspect_configuration,
            inspect_target_machine=inspect_target_machine,
            run_batch=run_batch,
            review_plan=review_plan,
            approve_plan=lambda _evidence, _output: True,
            prove_archive_restore=prove_archive_restore,
            run_tournament=run_tournament,
            verify_tournament=verify_tournament,
        )

    def test_public_command_records_complete_real_path_report(self) -> None:
        clock = SequenceClock(tuple(float(value) for value in range(17)))

        code = main(
            self.arguments(),
            operations=self.operations(),
            clock=clock,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        self.assertEqual(code, 0)
        report = json.loads((self.output / "rehearsal-report.json").read_text())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["objective_result"], "met")
        self.assertEqual(report["objective_seconds"], OBJECTIVE_SECONDS)
        self.assertEqual(report["team_count"], 16)
        self.assertEqual(report["platform"], "linux/arm64")
        self.assertEqual(report["parallelism"], 4)
        self.assertEqual(report["tournament"]["match_count"], 369)
        self.assertTrue(report["tournament"]["all_series_used_three_matches"])
        self.assertTrue(report["tournament"]["timing_isolation_verified"])
        self.assertEqual(
            set(report["phase_timings_seconds"]),
            {
                "configuration",
                "input_validation",
                "build_validation_preservation",
                "plan_review",
                "archive_restore",
                "tournament_execution",
                "public_verification",
            },
        )
        self.assertEqual(len(report["artifacts"]["artifact_identities"]), 16)
        self.assertEqual(report["artifacts"]["tournament_seed"], 8675309)
        self.assertEqual(
            report["artifacts"]["execution_profile"]["version"],
            "docker-execution-v1",
        )

    def test_timing_overrun_fails_only_readiness_after_completion(self) -> None:
        operations = self.operations()
        clock = SequenceClock(
            (0.0, 100.0, 100.0, 500.0, 500.0, 900.0, 900.0,
             1200.0, 1200.0, 1300.0, 1300.0, 1600.0, 1600.0,
             2000.0, 2000.0, 2400.0, 2501.0)
        )

        code = main(
            self.arguments(),
            operations=operations,
            clock=clock,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        self.assertEqual(code, TIMING_OBJECTIVE_EXIT_CODE)
        report = json.loads((self.output / "rehearsal-report.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["objective_result"], "exceeded")
        self.assertEqual(report["failure_kind"], "timing_objective")
        self.assertEqual(report["total_elapsed_seconds"], 2401.0)
        self.assertEqual(report["tournament"]["status"], "complete")
        self.assertEqual(
            (self.output / "tournament" / "canonical.marker").read_bytes(),
            b"unchanged",
        )

    def test_plan_must_be_approved_before_tournament_is_sealed(self) -> None:
        operations = replace(
            self.operations(), approve_plan=lambda _evidence, _output: False
        )

        code = main(
            self.arguments(),
            operations=operations,
            stdout=StringIO(),
            stderr=StringIO(),
        )

        self.assertEqual(code, CORRECTNESS_FAILURE_EXIT_CODE)
        report = json.loads((self.output / "rehearsal-report.json").read_text())
        self.assertIn("not approved", report["failure_detail"])
        self.assertFalse((self.output / "tournament").exists())

    def test_invalid_team_count_fails_before_work_begins(self) -> None:
        mapping = json.loads(self.teams.read_text())
        mapping["teams"].pop()
        self.teams.write_text(json.dumps(mapping))

        code = main(
            self.arguments(),
            operations=self.operations(),
            stdout=StringIO(),
            stderr=StringIO(),
        )

        self.assertEqual(code, CORRECTNESS_FAILURE_EXIT_CODE)
        report = json.loads((self.output / "rehearsal-report.json").read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure_kind"], "correctness")
        self.assertIn("exactly sixteen", report["failure_detail"])


if __name__ == "__main__":
    unittest.main()
