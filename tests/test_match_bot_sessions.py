from __future__ import annotations

from collections import deque
import os
from typing import Deque, Optional
import unittest

from rps_runner.engine import (
    BotArtifactDisconnected,
    InfrastructureError,
    MatchConfig,
    run_match,
)


class ScriptedSession:
    def __init__(
        self,
        harness: "SessionHarness",
        bot_position: str,
        artifact_reference: str,
        config: MatchConfig,
    ) -> None:
        self.harness = harness
        self.bot_position = bot_position
        self.artifact_reference = artifact_reference
        self.config = config
        self.responses: Deque[bytes] = deque(
            harness.responses[bot_position]
        )
        self.requests: list[bytes] = []
        self.started = False
        self.terminated = False
        self.stopped = False
        self.force_stopped = False
        self.finished = False
        self.read_descriptor, self.write_descriptor = os.pipe()

    @property
    def output_descriptor(self) -> int:
        return self.read_descriptor

    def start(self) -> None:
        self.started = True

    def send(self, request: bytes) -> None:
        if self.harness.send_failure_position == self.bot_position:
            if self.harness.disconnect_on_send:
                raise BotArtifactDisconnected
            raise InfrastructureError("test session transport failed")
        self.requests.append(request)
        os.write(self.write_descriptor, self.responses.popleft())

    def read_output(self, maximum_bytes: int) -> bytes:
        self.harness.read_observations.append(
            sum(len(session.requests) for session in self.harness.sessions)
        )
        return os.read(self.read_descriptor, maximum_bytes)

    def disconnection_fault(
        self, turn: int, default_detail: str
    ) -> dict[str, object]:
        return {"kind": "unexpected_exit", "turn": turn, "detail": default_detail}

    def terminate(self) -> None:
        self.terminated = True

    def stop(self) -> None:
        if self.stopped:
            return
        self.stopped = True

    def force_stop(self) -> None:
        self.harness.force_stop_observations.append(
            all(session.stopped for session in self.harness.sessions)
        )
        self.force_stopped = True

    def finish_stop(self) -> None:
        self.harness.finish_observations.append(
            all(
                session.force_stopped
                for session in self.harness.sessions
            )
        )
        if self.finished:
            return
        self.finished = True
        os.close(self.read_descriptor)
        os.close(self.write_descriptor)

    def stderr_text(self) -> str:
        return f"{self.bot_position} diagnostic"

    @property
    def stderr_truncated(self) -> bool:
        return False

    def operational_telemetry(self) -> dict[str, object]:
        return {}


class SessionHarness:
    def __init__(
        self,
        responses: dict[str, list[bytes]],
        *,
        send_failure_position: Optional[str] = None,
        disconnect_on_send: bool = False,
    ) -> None:
        self.responses = responses
        self.send_failure_position = send_failure_position
        self.disconnect_on_send = disconnect_on_send
        self.sessions: list[ScriptedSession] = []
        self.read_observations: list[int] = []
        self.force_stop_observations: list[bool] = []
        self.finish_observations: list[bool] = []

    def create(
        self,
        bot_position: str,
        artifact_reference: str,
        config: MatchConfig,
    ) -> ScriptedSession:
        session = ScriptedSession(
            self, bot_position, artifact_reference, config
        )
        self.sessions.append(session)
        return session


class RuntimeNeutralBotSessionTests(unittest.TestCase):
    def config(self, *, rounds: int = 2) -> MatchConfig:
        return MatchConfig(
            bot_a="artifact-a",
            bot_b="artifact-b",
            rounds=rounds,
            seed=999,
            bot_a_seed=111,
            bot_b_seed=222,
        )

    def test_non_process_sessions_play_through_the_public_match_seam(self) -> None:
        harness = SessionHarness(
            {"a": [b"R\n", b"P\n"], "b": [b"S\n", b"P\n"]}
        )

        result = run_match(self.config(), session_factory=harness.create)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["score"], {"a": 1, "b": 0, "draws": 1})
        self.assertEqual(result["moves"], {"a": "RP", "b": "SP"})
        self.assertTrue(all(session.started for session in harness.sessions))
        self.assertTrue(all(session.stopped for session in harness.sessions))
        self.assertTrue(
            all(session.force_stopped for session in harness.sessions)
        )
        self.assertTrue(all(session.finished for session in harness.sessions))
        self.assertTrue(all(harness.force_stop_observations))
        self.assertTrue(all(harness.finish_observations))
        self.assertEqual(
            harness.sessions[0].requests,
            [b"0\n-\n-\n", b"1\nR\nS\n"],
        )
        self.assertEqual(
            harness.sessions[1].requests,
            [b"0\n-\n-\n", b"1\nS\nR\n"],
        )
        self.assertTrue(
            all(
                observation % 2 == 0
                for observation in harness.read_observations
            )
        )
        self.assertEqual(result["bots"]["a"]["stderr"], "a diagnostic")

    def test_session_infrastructure_failure_is_not_a_competitive_fault(self) -> None:
        harness = SessionHarness(
            {"a": [b"R\n"], "b": [b"S\n"]},
            send_failure_position="a",
        )

        with self.assertRaisesRegex(InfrastructureError, "transport failed"):
            run_match(self.config(rounds=1), session_factory=harness.create)

        self.assertTrue(all(session.stopped for session in harness.sessions))

    def test_bot_artifact_disconnect_remains_a_forfeit(self) -> None:
        harness = SessionHarness(
            {"a": [b"R\n"], "b": [b"S\n"]},
            send_failure_position="a",
            disconnect_on_send=True,
        )

        result = run_match(self.config(rounds=1), session_factory=harness.create)

        self.assertEqual(result["status"], "forfeit")
        self.assertEqual(result["winner"], "b")
        self.assertEqual(result["faults"]["a"]["kind"], "unexpected_exit")


if __name__ == "__main__":
    unittest.main()
