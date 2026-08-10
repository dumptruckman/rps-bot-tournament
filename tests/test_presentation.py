from __future__ import annotations

from contextlib import contextmanager
import http.client
import json
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterator
import unittest
from unittest.mock import patch

from rps_runner.presentation.contract import ProjectionContractError, project_live
from rps_runner.presentation.server import create_server


def projection(
    *,
    tournament_id: str = "summer-cup",
    status: str = "paused",
    display_name: str = "Alpha",
    standing_points: int = 3,
) -> dict[str, Any]:
    return {
        "version": 1,
        "tournament_id": tournament_id,
        "status": status,
        "phase": "qualifying",
        "teams": [
            {
                "team_id": "alpha",
                "display_name": display_name,
                "eligible": True,
                "status": "eligible",
                "bot_artifact": {"artifact_digest": "secret"},
            },
            {"team_id": "beta", "display_name": "Beta"},
        ],
        "standings": [
            {
                "team_id": "alpha",
                "standing_points": standing_points,
                "series_wins": 1,
                "match_differential": 2,
                "round_differential": 7,
                "protocol_fault_forfeits": 0,
                "tie_break_key": "99",
                "seed": "secret",
            }
        ],
        "fixtures": [
            {
                "fixture_id": "qualifying-0001",
                "team_ids": ["alpha", "beta"],
                "status": "scheduled",
                "matches": [],
                "fixture_seed": "secret",
            }
        ],
        "champion": None,
        "operator_abort": {"note": "secret"},
    }


class LiveContractTests(unittest.TestCase):
    def test_copies_only_live_standings_fields_in_projection_order(self) -> None:
        source = projection()
        source["standings"].insert(
            0,
            {
                "team_id": "beta",
                "standing_points": 6,
                "series_wins": 2,
                "match_differential": 4,
                "round_differential": 11,
                "protocol_fault_forfeits": 0,
                "tie_break_key": "12",
            },
        )

        live = project_live(source)

        self.assertEqual(
            live,
            {
                "version": 1,
                "tournament_id": "summer-cup",
                "status": "paused",
                "phase": "qualifying",
                "teams": [
                    {
                        "team_id": "alpha",
                        "display_name": "Alpha",
                        "eligible": True,
                        "status": "eligible",
                    },
                    {"team_id": "beta", "display_name": "Beta"},
                ],
                "standings": [
                    {
                        "team_id": "beta",
                        "standing_points": 6,
                        "series_wins": 2,
                        "match_differential": 4,
                        "round_differential": 11,
                        "protocol_fault_forfeits": 0,
                        "tie_break_key": "12",
                    },
                    {
                        "team_id": "alpha",
                        "standing_points": 3,
                        "series_wins": 1,
                        "match_differential": 2,
                        "round_differential": 7,
                        "protocol_fault_forfeits": 0,
                        "tie_break_key": "99",
                    },
                ],
                "fixtures": [
                    {
                        "fixture_id": "qualifying-0001",
                        "team_ids": ["alpha", "beta"],
                        "status": "scheduled",
                        "matches": [],
                    }
                ],
                "champion": None,
            },
        )
        self.assertNotIn("secret", json.dumps(live))

    def test_copies_ordered_fixtures_history_bracket_and_terminal_facts(self) -> None:
        source = projection(status="complete")
        source["phase"] = "playoff"
        source["teams"][1].update(
            eligible=False,
            status="disqualified",
        )
        source["fixtures"] = [
            {
                "fixture_id": "qualifying-0002",
                "team_ids": ["beta", "alpha"],
                "status": "complete",
                "matches": [
                    {
                        "match_id": "qualifying-0002-match-1",
                        "outcome": "double_forfeit",
                        "winner_team_id": None,
                        "round_wins": {"alpha": 3, "beta": 2},
                    },
                    {
                        "match_id": "qualifying-0002-match-2",
                        "outcome": "win",
                        "winner_team_id": "alpha",
                    },
                ],
                "administrative_series_win": {
                    "winner_team_id": "alpha",
                    "reason_code": "opponent_disqualified",
                    "organizer_id": "secret",
                },
                "fixture_seed": "secret",
            },
            {
                "fixture_id": "qualifying-0001",
                "team_ids": ["alpha", "beta"],
                "status": "skipped",
                "matches": [],
                "skip_reason": "teams_disqualified",
            },
        ]
        source["bracket"] = {
            "locked": True,
            "seeds": [
                {"seed": 2, "team_id": "beta"},
                {"seed": 1, "team_id": "alpha"},
            ],
            "fixtures": [
                {
                    "fixture_id": "playoff-final",
                    "stage": "final",
                    "team_ids": ["alpha", None],
                    "status": "complete",
                    "matches": [],
                    "resolved_team_id": "alpha",
                    "bracket_position_replacement": {
                        "disqualified_team_id": "beta",
                        "reinstated_team_id": None,
                        "source_fixture_id": "playoff-semifinal-2",
                        "reason_code": "disqualified_advancer",
                    },
                    "fixture_seed": "secret",
                }
            ],
        }
        source["champion"] = "alpha"
        source["completion_reason"] = "score"

        live = project_live(source)

        self.assertEqual(
            live["teams"][1],
            {
                "team_id": "beta",
                "display_name": "Beta",
                "eligible": False,
                "status": "disqualified",
            },
        )
        self.assertEqual(
            [fixture["fixture_id"] for fixture in live["fixtures"]],
            ["qualifying-0002", "qualifying-0001"],
        )
        self.assertEqual(
            [match["match_id"] for match in live["fixtures"][0]["matches"]],
            ["qualifying-0002-match-1", "qualifying-0002-match-2"],
        )
        self.assertEqual(
            live["fixtures"][0]["matches"][0],
            {
                "match_id": "qualifying-0002-match-1",
                "outcome": "double_forfeit",
                "winner_team_id": None,
            },
        )
        self.assertEqual(
            live["bracket"],
            {
                "locked": True,
                "seeds": [
                    {"seed": 2, "team_id": "beta"},
                    {"seed": 1, "team_id": "alpha"},
                ],
                "fixtures": [
                    {
                        "fixture_id": "playoff-final",
                        "stage": "final",
                        "team_ids": ["alpha", None],
                        "status": "complete",
                        "matches": [],
                        "resolved_team_id": "alpha",
                        "bracket_position_replacement": {
                            "disqualified_team_id": "beta",
                            "reinstated_team_id": None,
                            "source_fixture_id": "playoff-semifinal-2",
                            "reason_code": "disqualified_advancer",
                        },
                    }
                ],
            },
        )
        self.assertEqual(live["champion"], "alpha")
        self.assertEqual(live["completion_reason"], "score")
        self.assertNotIn("secret", json.dumps(live))

    def test_security_review_and_abort_copy_only_audience_safe_fields(self) -> None:
        source = projection(status="awaiting_security_ruling")
        source["security_review"] = {
            "fixture_id": "qualifying-0001",
            "match_id": "qualifying-0001-match-1",
            "suspected_team_id": "alpha",
            "suspected_team_ids": ["alpha", "beta"],
            "evidence": "secret",
        }

        review = project_live(source)

        self.assertEqual(
            review["security_review"],
            {
                "fixture_id": "qualifying-0001",
                "match_id": "qualifying-0001-match-1",
            },
        )
        self.assertNotIn("alpha", json.dumps(review["security_review"]))

        source = projection(status="aborted")
        source["completion_reason"] = "operator_requested"
        source["operator_abort"] = {
            "organizer_id": "organizer-secret",
            "note": "secret note",
        }

        aborted = project_live(source)

        self.assertEqual(aborted["completion_reason"], "operator_requested")
        self.assertNotIn("operator_abort", aborted)
        self.assertNotIn("organizer-secret", json.dumps(aborted))

    def test_bracket_fields_are_required_only_for_playoff_fixtures(self) -> None:
        source = projection()
        source["fixtures"][0].update(
            stage="final",
            resolved_team_id="alpha",
            bracket_position_replacement={
                "disqualified_team_id": "beta",
                "reinstated_team_id": "alpha",
                "source_fixture_id": "playoff-semifinal-1",
                "reason_code": "disqualified_advancer",
            },
        )

        qualifying = project_live(source)["fixtures"][0]

        self.assertNotIn("stage", qualifying)
        self.assertNotIn("resolved_team_id", qualifying)
        self.assertNotIn("bracket_position_replacement", qualifying)

        source["phase"] = "playoff"
        source["bracket"] = {
            "locked": False,
            "seeds": [],
            "fixtures": [
                {
                    "fixture_id": "playoff-final",
                    "team_ids": ["alpha", "beta"],
                    "status": "scheduled",
                    "matches": [],
                }
            ],
        }
        with self.assertRaisesRegex(ProjectionContractError, "stage"):
            project_live(source)

    def test_accepts_running_and_rejects_unsupported_or_invalid_projection(
        self,
    ) -> None:
        self.assertEqual(
            project_live(projection(status="running"))["status"], "running"
        )

        unsupported = projection()
        unsupported["version"] = 2
        with self.assertRaisesRegex(ProjectionContractError, "version"):
            project_live(unsupported)

        malformed = projection()
        malformed["standings"][0]["standing_points"] = "three"
        with self.assertRaisesRegex(ProjectionContractError, "standing_points"):
            project_live(malformed)


class PresentationHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @contextmanager
    def serving(self) -> Iterator[tuple[str, int]]:
        server = create_server(self.directory, "127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address[:2]
            yield str(host), int(port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def write_projection(self, value: dict[str, Any]) -> None:
        replacement = self.directory / ".scoreboard.next"
        replacement.write_text(json.dumps(value), encoding="utf-8")
        replacement.replace(self.directory / "scoreboard.json")

    def request(
        self,
        address: tuple[str, int],
        path: str,
        *,
        etag: str | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection(*address, timeout=2)
        headers = {"If-None-Match": etag} if etag is not None else {}
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        body = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, response_headers, body

    def test_waits_for_projection_then_supports_conditional_requests(self) -> None:
        with self.serving() as address:
            status, headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 503)
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertFalse(json.loads(body)["freshness"]["available"])

            self.write_projection(projection())
            status, headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 200)
            etag = headers["etag"]
            response = json.loads(body)
            self.assertTrue(response["freshness"]["available"])
            self.assertEqual(response["tournament"]["status"], "paused")

            status, _headers, body = self.request(
                address, "/api/live", etag=etag
            )
            self.assertEqual(status, 304)
            self.assertEqual(body, b"")

    def test_serves_running_lifecycle_without_changing_standings(self) -> None:
        self.write_projection(projection(status="running"))
        with self.serving() as address:
            status, _headers, body = self.request(address, "/api/live")
            response = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(response["tournament"]["status"], "running")
            self.assertEqual(
                response["tournament"]["standings"],
                project_live(projection(status="running"))["standings"],
            )

            status, _headers, script = self.request(address, "/assets/app.js")
            self.assertEqual(status, 200)
            self.assertIn(b'Tournament running', script)

    def test_retains_last_generation_during_failure_and_recovers_atomically(
        self,
    ) -> None:
        self.write_projection(
            projection(tournament_id="first", standing_points=3)
        )
        with self.serving() as address:
            status, headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 200)
            first = json.loads(body)
            first_etag = headers["etag"]

            (self.directory / "scoreboard.json").write_text(
                "not json", encoding="utf-8"
            )
            status, headers, body = self.request(
                address, "/api/live", etag=first_etag
            )
            stale = json.loads(body)
            self.assertEqual(status, 200)
            self.assertFalse(stale["freshness"]["available"])
            self.assertEqual(stale["tournament"], first["tournament"])
            self.assertNotEqual(headers["etag"], first_etag)

            self.write_projection(
                projection(
                    tournament_id="second",
                    display_name="Beta",
                    standing_points=8,
                )
            )
            status, _headers, body = self.request(
                address, "/api/live", etag=headers["etag"]
            )
            recovered = json.loads(body)
            self.assertEqual(status, 200)
            self.assertTrue(recovered["freshness"]["available"])
            self.assertEqual(recovered["tournament"]["tournament_id"], "second")
            self.assertEqual(
                recovered["tournament"]["teams"][0]["display_name"], "Beta"
            )
            self.assertEqual(
                recovered["tournament"]["standings"][0]["standing_points"], 8
            )
            self.assertNotIn("first", json.dumps(recovered))

    def test_hostile_display_names_remain_data_and_assets_reject_traversal(
        self,
    ) -> None:
        hostile = '<img src=x onerror="alert(1)">'
        self.write_projection(projection(display_name=hostile))
        with self.serving() as address:
            status, _headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 200)
            encoded = json.loads(body)
            self.assertEqual(
                encoded["tournament"]["teams"][0]["display_name"], hostile
            )
            self.assertNotIn("artifact_digest", body.decode("utf-8"))

            status, _headers, script = self.request(address, "/assets/app.js")
            self.assertEqual(status, 200)
            self.assertIn(b"textContent", script)
            self.assertNotIn(b"innerHTML", script)
            self.assertIn(b'"If-None-Match"', script)
            self.assertIn(b"replaceChildren", script)
            self.assertIn(b"setTimeout(poll, 1000)", script)
            self.assertLess(
                script.index(b"render(payload.tournament)"),
                script.index(b"if (!payload.freshness.available)"),
            )

            status, _headers, _body = self.request(
                address, "/assets/../contract.py"
            )
            self.assertEqual(status, 404)

    def test_requests_do_not_change_tournament_store_files(self) -> None:
        self.write_projection(projection())
        before = {
            path.relative_to(self.directory): path.read_bytes()
            for path in self.directory.rglob("*")
            if path.is_file()
        }
        with self.serving() as address:
            self.assertEqual(self.request(address, "/")[0], 200)
            self.assertEqual(self.request(address, "/api/live")[0], 200)
        after = {
            path.relative_to(self.directory): path.read_bytes()
            for path in self.directory.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertFalse((self.directory / "run.lock").exists())

    def test_unsupported_generation_retains_the_last_valid_view(self) -> None:
        self.write_projection(projection())
        with self.serving() as address:
            status, _headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 200)
            accepted = json.loads(body)["tournament"]

            unsupported = projection(tournament_id="must-not-appear")
            unsupported["version"] = 2
            self.write_projection(unsupported)
            status, _headers, body = self.request(address, "/api/live")
            response = json.loads(body)
            self.assertEqual(status, 200)
            self.assertFalse(response["freshness"]["available"])
            self.assertEqual(response["tournament"], accepted)

    def test_unreadable_projection_retains_the_last_valid_view(self) -> None:
        self.write_projection(projection())
        with self.serving() as address:
            status, _headers, body = self.request(address, "/api/live")
            self.assertEqual(status, 200)
            accepted = json.loads(body)["tournament"]

            with patch.object(
                Path,
                "read_bytes",
                side_effect=PermissionError("scoreboard is unreadable"),
            ):
                status, _headers, body = self.request(address, "/api/live")
            response = json.loads(body)
            self.assertEqual(status, 200)
            self.assertFalse(response["freshness"]["available"])
            self.assertEqual(response["tournament"], accepted)


class PresentationBoundaryTests(unittest.TestCase):
    def test_presentation_python_does_not_import_competitive_modules(self) -> None:
        package = Path(__file__).resolve().parents[1] / "rps_runner" / "presentation"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in package.glob("*.py")
        )
        forbidden = (
            "tournament.runner",
            "tournament.state",
            "tournament.schedule",
            "tournament.scoring",
            "tournament.match_executor",
            "engine.",
            "TournamentRunLock",
        )
        for name in forbidden:
            with self.subTest(name=name):
                self.assertNotIn(name, source)


if __name__ == "__main__":
    unittest.main()
