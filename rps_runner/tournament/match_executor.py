"""Tournament-to-Match execution boundary and result normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, cast

from rps_runner.engine import InfrastructureError, MatchConfig, run_match
from rps_runner.tournament.immutable import FrozenJsonDict, freeze_json


ArtifactCommandResolver = Callable[[str, str], str]
MatchRunner = Callable[[MatchConfig], dict[str, object]]


class InvalidMatchResultError(InfrastructureError):
    """The Match Runner returned data that violates its sealed request."""


@dataclass(frozen=True)
class MatchExecutionRequest:
    """Sealed Match inputs forwarded to an execution boundary.

    The local subprocess executor enforces the protocol timeouts and stream
    limits. CPU, memory, process, filesystem-write, and network restrictions
    are explicit here for a separate hardened executor boundary; the local
    executor records but does not claim to enforce them.
    """

    tournament_id: str
    fixture_id: str
    series_id: str
    match_id: str
    attempt_number: int
    team_a_id: str
    team_b_id: str
    artifact_digest_a: str
    artifact_digest_b: str
    match_seed: int
    bot_visible_seed_a: int
    bot_visible_seed_b: int
    protocol_version: int
    scheduled_turns: int
    first_move_timeout_ms: int
    move_timeout_ms: int
    total_timeout_ms: int
    stderr_limit_bytes: int
    stdout_limit_bytes: int
    cpu_limit_ms: int
    memory_limit_bytes: int
    process_limit: int
    filesystem_write_limit_bytes: int
    network_access_allowed: bool

    def __post_init__(self) -> None:
        if self.protocol_version != 1:
            raise ValueError("Tournament Matches require protocol version 1")
        if self.scheduled_turns != 300:
            raise ValueError("Tournament Matches must schedule exactly 300 Turns")
        positive_limit_fields = (
            "first_move_timeout_ms",
            "move_timeout_ms",
            "total_timeout_ms",
            "stderr_limit_bytes",
            "stdout_limit_bytes",
            "cpu_limit_ms",
            "memory_limit_bytes",
            "process_limit",
        )
        for field_name in positive_limit_fields:
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            not isinstance(self.filesystem_write_limit_bytes, int)
            or isinstance(self.filesystem_write_limit_bytes, bool)
            or self.filesystem_write_limit_bytes < 0
        ):
            raise ValueError(
                "filesystem_write_limit_bytes must be a non-negative integer"
            )
        if not isinstance(self.network_access_allowed, bool):
            raise ValueError("network_access_allowed must be a boolean")


@dataclass(frozen=True)
class MatchExecutionResult:
    infrastructure_failure: bool
    competitive_outcome: Optional[FrozenJsonDict]
    operational_telemetry: FrozenJsonDict

    def __post_init__(self) -> None:
        if self.competitive_outcome is not None:
            object.__setattr__(
                self,
                "competitive_outcome",
                _frozen_json_object(self.competitive_outcome),
            )
        object.__setattr__(
            self,
            "operational_telemetry",
            _frozen_json_object(self.operational_telemetry),
        )


def _frozen_json_object(value: dict[str, object]) -> FrozenJsonDict:
    frozen = freeze_json(value)
    if not isinstance(frozen, FrozenJsonDict):
        raise TypeError("Match execution payload must be a JSON object")
    return frozen


class LocalMatchExecutor:
    """Execute one canonical Match through the local Match Runner.

    This adapter enforces protocol timing and stream limits. The remaining
    resource and security fields stay on the request and in telemetry for a
    separate hardened executor; local subprocesses do not enforce them.
    """

    def __init__(
        self,
        artifact_command_resolver: ArtifactCommandResolver,
        match_runner: MatchRunner = run_match,
    ) -> None:
        self.artifact_command_resolver = artifact_command_resolver
        self.match_runner = match_runner

    def execute(self, request: MatchExecutionRequest) -> MatchExecutionResult:
        commands: dict[str, str] = {}
        try:
            bot_a_command = self.artifact_command_resolver(
                request.team_a_id, request.artifact_digest_a
            )
            commands[request.team_a_id] = bot_a_command
            bot_b_command = self.artifact_command_resolver(
                request.team_b_id, request.artifact_digest_b
            )
            commands[request.team_b_id] = bot_b_command
            config = MatchConfig(
                bot_a=bot_a_command,
                bot_b=bot_b_command,
                rounds=request.scheduled_turns,
                seed=request.match_seed,
                first_move_timeout_ms=request.first_move_timeout_ms,
                move_timeout_ms=request.move_timeout_ms,
                total_timeout_ms=request.total_timeout_ms,
                stderr_limit_bytes=request.stderr_limit_bytes,
                stdout_limit_bytes=request.stdout_limit_bytes,
                bot_a_seed=request.bot_visible_seed_a,
                bot_b_seed=request.bot_visible_seed_b,
            )
            raw_result = self.match_runner(config)
            _validate_match_result(request, raw_result)
        except InfrastructureError as error:
            return _failed_match_attempt(request, commands, error)
        return MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=_competitive_outcome(request, raw_result),
            operational_telemetry=_operational_telemetry(request, raw_result),
        )


def _validate_match_result(
    request: MatchExecutionRequest, raw_result: object
) -> None:
    if not isinstance(raw_result, dict):
        raise InvalidMatchResultError("Match result must be a JSON object")
    protocol_version = raw_result.get("protocol_version")
    if (
        not isinstance(protocol_version, int)
        or isinstance(protocol_version, bool)
        or protocol_version != request.protocol_version
    ):
        raise InvalidMatchResultError(
            "Match result protocol_version does not match the sealed request"
        )
    scheduled_rounds = raw_result.get("scheduled_rounds")
    if (
        not isinstance(scheduled_rounds, int)
        or isinstance(scheduled_rounds, bool)
        or scheduled_rounds != request.scheduled_turns
    ):
        raise InvalidMatchResultError(
            "Match result scheduled_rounds does not match the sealed request"
        )
    match_seed = raw_result.get("seed")
    if (
        not isinstance(match_seed, int)
        or isinstance(match_seed, bool)
        or match_seed != request.match_seed
    ):
        raise InvalidMatchResultError(
            "Match result seed does not match the sealed Match seed"
        )
    status = raw_result.get("status")
    winner = raw_result.get("winner")
    if not isinstance(status, str) or not (
        winner is None or isinstance(winner, str)
    ):
        raise InvalidMatchResultError(
            "Match result status/winner combination is invalid"
        )
    status_and_winner = (status, winner)
    valid_status_and_winner = {
        ("completed", "a"),
        ("completed", "b"),
        ("completed", "draw"),
        ("forfeit", "a"),
        ("forfeit", "b"),
        ("double_forfeit", None),
    }
    if status_and_winner not in valid_status_and_winner:
        raise InvalidMatchResultError(
            "Match result status/winner combination is invalid"
        )
    faults = raw_result.get("faults")
    if not isinstance(faults, dict) or set(faults) != {"a", "b"}:
        raise InvalidMatchResultError("Match result faults shape is invalid")
    faulted_positions = {
        position for position, fault in faults.items() if fault is not None
    }
    status, winner = status_and_winner
    if status == "completed" and faulted_positions:
        raise InvalidMatchResultError("Completed Match result cannot contain faults")
    if status == "forfeit":
        losing_position = "b" if winner == "a" else "a"
        if faulted_positions != {losing_position}:
            raise InvalidMatchResultError(
                "Forfeit Match result must contain exactly the losing bot fault"
            )
    if status == "double_forfeit" and faulted_positions != {"a", "b"}:
        raise InvalidMatchResultError(
            "Double Forfeit Match result must contain both bot faults"
        )
    _validate_match_result_collections(raw_result, faults)
    if status == "double_forfeit":
        fault_a = cast(dict[str, object], faults["a"])
        fault_b = cast(dict[str, object], faults["b"])
        if fault_a["turn"] != fault_b["turn"]:
            raise InvalidMatchResultError(
                "Double Forfeit Match result faults must share one Turn"
            )


def _validate_match_result_collections(
    raw_result: dict[str, object], faults: dict[str, object]
) -> None:
    try:
        freeze_json(raw_result)
    except (TypeError, ValueError) as error:
        raise InvalidMatchResultError(
            f"Match result is not valid JSON: {error}"
        ) from error

    score = raw_result.get("score")
    if not isinstance(score, dict) or set(score) != {"a", "b", "draws"}:
        raise InvalidMatchResultError("Match result score shape is invalid")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in score.values()
    ):
        raise InvalidMatchResultError("Match result score values are invalid")

    moves = raw_result.get("moves")
    if not isinstance(moves, dict) or set(moves) != {"a", "b"}:
        raise InvalidMatchResultError("Match result moves shape is invalid")
    if any(
        not isinstance(value, str) or any(move not in "RPS" for move in value)
        for value in moves.values()
    ):
        raise InvalidMatchResultError("Match result moves values are invalid")

    rounds = raw_result.get("rounds")
    if not isinstance(rounds, list):
        raise InvalidMatchResultError("Match result rounds shape is invalid")
    completed_rounds = raw_result.get("completed_rounds")
    if (
        not isinstance(completed_rounds, int)
        or isinstance(completed_rounds, bool)
        or completed_rounds != len(rounds)
    ):
        raise InvalidMatchResultError(
            "Match result completed_rounds does not match rounds"
        )
    for expected_turn, round_result in enumerate(rounds):
        _validate_round_result(round_result, expected_turn)

    for position, fault in faults.items():
        if fault is None:
            continue
        if not isinstance(fault, dict):
            raise InvalidMatchResultError(
                f"Match result faults.{position} shape is invalid"
            )
        kind = fault.get("kind")
        turn = fault.get("turn")
        if (
            not isinstance(kind, str)
            or not kind
            or not isinstance(turn, int)
            or isinstance(turn, bool)
            or turn < 0
        ):
            raise InvalidMatchResultError(
                f"Match result faults.{position} values are invalid"
            )

    timing = raw_result.get("timing")
    if not isinstance(timing, dict):
        raise InvalidMatchResultError("Match result timing shape is invalid")
    total_response_ns = timing.get("total_response_ns")
    if not isinstance(total_response_ns, dict) or set(total_response_ns) != {"a", "b"}:
        raise InvalidMatchResultError(
            "Match result timing.total_response_ns shape is invalid"
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in total_response_ns.values()
    ):
        raise InvalidMatchResultError(
            "Match result timing.total_response_ns values are invalid"
        )

    bots = raw_result.get("bots")
    if (
        not isinstance(bots, dict)
        or set(bots) != {"a", "b"}
        or any(not isinstance(value, dict) for value in bots.values())
    ):
        raise InvalidMatchResultError("Match result bots shape is invalid")


def _validate_round_result(round_result: object, expected_turn: int) -> None:
    if not isinstance(round_result, dict):
        raise InvalidMatchResultError("Match result rounds item shape is invalid")
    required_fields = {"turn", "a", "b", "winner", "response_time_ns"}
    if not required_fields.issubset(round_result):
        raise InvalidMatchResultError("Match result rounds item shape is invalid")
    turn = round_result["turn"]
    if (
        not isinstance(turn, int)
        or isinstance(turn, bool)
        or turn != expected_turn
    ):
        raise InvalidMatchResultError("Match result rounds turn sequence is invalid")
    if not isinstance(round_result["a"], str) or round_result["a"] not in {
        "R",
        "P",
        "S",
    }:
        raise InvalidMatchResultError("Match result rounds.a move is invalid")
    if not isinstance(round_result["b"], str) or round_result["b"] not in {
        "R",
        "P",
        "S",
    }:
        raise InvalidMatchResultError("Match result rounds.b move is invalid")
    if not isinstance(round_result["winner"], str) or round_result[
        "winner"
    ] not in {"a", "b", "draw"}:
        raise InvalidMatchResultError("Match result rounds winner is invalid")
    response_times = round_result["response_time_ns"]
    if not isinstance(response_times, dict) or set(response_times) != {"a", "b"}:
        raise InvalidMatchResultError(
            "Match result rounds response_time_ns shape is invalid"
        )
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in response_times.values()
    ):
        raise InvalidMatchResultError(
            "Match result rounds response_time_ns values are invalid"
        )


def _failed_match_attempt(
    request: MatchExecutionRequest,
    commands: dict[str, str],
    error: InfrastructureError,
) -> MatchExecutionResult:
    return MatchExecutionResult(
        infrastructure_failure=True,
        competitive_outcome=None,
        operational_telemetry={
            "tournament_id": request.tournament_id,
            "fixture_id": request.fixture_id,
            "match_id": request.match_id,
            "attempt_number": request.attempt_number,
            "resource_limits": _resource_limits(request),
            "commands": commands,
            "infrastructure_failure": {
                "kind": type(error).__name__,
                "message": str(error),
            },
        },
    )


def _competitive_outcome(
    request: MatchExecutionRequest, raw_result: dict[str, object]
) -> dict[str, object]:
    team_by_position = {"a": request.team_a_id, "b": request.team_b_id}
    raw_winner = raw_result["winner"]
    winner_team_id = team_by_position.get(raw_winner)
    status = raw_result["status"]
    outcome = (
        "double_forfeit"
        if status == "double_forfeit"
        else "draw" if raw_winner == "draw" else "win"
    )
    raw_score = cast(dict[str, object], raw_result["score"])
    raw_moves = cast(dict[str, object], raw_result["moves"])
    raw_faults = cast(dict[str, object], raw_result["faults"])
    raw_rounds = cast(list[dict[str, object]], raw_result["rounds"])

    return {
        "tournament_id": request.tournament_id,
        "fixture_id": request.fixture_id,
        "series_id": request.series_id,
        "match_id": request.match_id,
        "protocol_version": request.protocol_version,
        "scheduled_turns": request.scheduled_turns,
        "match_seed": request.match_seed,
        "positions": {
            "a": {
                "team_id": request.team_a_id,
                "artifact_digest": request.artifact_digest_a,
                "bot_visible_seed": request.bot_visible_seed_a,
            },
            "b": {
                "team_id": request.team_b_id,
                "artifact_digest": request.artifact_digest_b,
                "bot_visible_seed": request.bot_visible_seed_b,
            },
        },
        "status": status,
        "outcome": outcome,
        "winner_team_id": winner_team_id,
        "score": {
            request.team_a_id: raw_score["a"],
            request.team_b_id: raw_score["b"],
            "draws": raw_score["draws"],
        },
        "moves": {
            request.team_a_id: raw_moves["a"],
            request.team_b_id: raw_moves["b"],
        },
        "rounds": [
            _competitive_round(round_result, team_by_position)
            for round_result in raw_rounds
        ],
        "faults": {
            request.team_a_id: _normalized_fault(raw_faults["a"]),
            request.team_b_id: _normalized_fault(raw_faults["b"]),
        },
    }


def _competitive_round(
    raw_round: object, team_by_position: dict[str, str]
) -> dict[str, object]:
    raw_round = cast(dict[str, object], raw_round)
    return {
        "turn": raw_round["turn"],
        "moves": {
            team_by_position["a"]: raw_round["a"],
            team_by_position["b"]: raw_round["b"],
        },
        "winner_team_id": team_by_position.get(raw_round["winner"]),
    }


def _normalized_fault(raw_fault: object) -> Optional[dict[str, object]]:
    if raw_fault is None:
        return None
    raw_fault = cast(dict[str, object], raw_fault)
    return {"kind": raw_fault["kind"], "turn": raw_fault["turn"]}


def _operational_telemetry(
    request: MatchExecutionRequest, raw_result: dict[str, object]
) -> dict[str, object]:
    team_by_position = {"a": request.team_a_id, "b": request.team_b_id}
    raw_rounds = cast(list[dict[str, object]], raw_result["rounds"])
    raw_faults = cast(dict[str, object], raw_result["faults"])
    raw_timing = cast(dict[str, object], raw_result["timing"])
    timing = dict(raw_timing)
    total_response_ns = timing.get("total_response_ns")
    if isinstance(total_response_ns, dict):
        timing["total_response_ns"] = {
            team_by_position[position]: duration
            for position, duration in total_response_ns.items()
        }
    raw_bots = cast(dict[str, object], raw_result["bots"])
    return {
        "tournament_id": request.tournament_id,
        "fixture_id": request.fixture_id,
        "match_id": request.match_id,
        "attempt_number": request.attempt_number,
        "resource_limits": _resource_limits(request),
        "timing": timing,
        "bots": {
            team_by_position[position]: diagnostics
            for position, diagnostics in raw_bots.items()
        },
        "round_response_times_ns": [
            {
                request.team_a_id: round_result["response_time_ns"]["a"],
                request.team_b_id: round_result["response_time_ns"]["b"],
            }
            for round_result in raw_rounds
        ],
        "fault_details": {
            team_by_position[position]: fault
            for position, fault in raw_faults.items()
            if fault is not None
        },
    }


def _resource_limits(request: MatchExecutionRequest) -> dict[str, object]:
    """Return the complete sealed resource/security request for auditing."""

    return {
        "first_move_timeout_ms": request.first_move_timeout_ms,
        "move_timeout_ms": request.move_timeout_ms,
        "total_timeout_ms": request.total_timeout_ms,
        "stderr_limit_bytes": request.stderr_limit_bytes,
        "stdout_limit_bytes": request.stdout_limit_bytes,
        "cpu_limit_ms": request.cpu_limit_ms,
        "memory_limit_bytes": request.memory_limit_bytes,
        "process_limit": request.process_limit,
        "filesystem_write_limit_bytes": request.filesystem_write_limit_bytes,
        "network_access_allowed": request.network_access_allowed,
    }
