"""Tournament-to-Match execution boundary and result normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from rps_runner.engine import InfrastructureError, MatchConfig, run_match


ArtifactCommandResolver = Callable[[str, str], str]
MatchRunner = Callable[[MatchConfig], dict[str, object]]


def _immutable(*args: object, **kwargs: object) -> None:
    raise TypeError("Match execution values are immutable")


class _FrozenDict(dict):
    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


class _FrozenList(list):
    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable


def _deep_freeze(value: object) -> object:
    if isinstance(value, dict):
        return _FrozenDict(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return _FrozenList(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class MatchExecutionRequest:
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

    def __post_init__(self) -> None:
        if self.protocol_version != 1:
            raise ValueError("Tournament Matches require protocol version 1")
        if self.scheduled_turns != 300:
            raise ValueError("Tournament Matches must schedule exactly 300 Turns")


@dataclass(frozen=True)
class MatchExecutionResult:
    infrastructure_failure: bool
    competitive_outcome: Optional[dict[str, object]]
    operational_telemetry: dict[str, object]

    def __post_init__(self) -> None:
        if self.competitive_outcome is not None:
            object.__setattr__(
                self,
                "competitive_outcome",
                _deep_freeze(self.competitive_outcome),
            )
        object.__setattr__(
            self,
            "operational_telemetry",
            _deep_freeze(self.operational_telemetry),
        )


class LocalMatchExecutor:
    """Execute one canonical Match through the local Match Runner."""

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
                bot_a_seed=request.bot_visible_seed_a,
                bot_b_seed=request.bot_visible_seed_b,
            )
            raw_result = self.match_runner(config)
        except InfrastructureError as error:
            return _failed_match_attempt(request, commands, error)
        return MatchExecutionResult(
            infrastructure_failure=False,
            competitive_outcome=_competitive_outcome(request, raw_result),
            operational_telemetry=_operational_telemetry(request, raw_result),
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
    raw_score = raw_result["score"]
    assert isinstance(raw_score, dict)
    raw_moves = raw_result["moves"]
    assert isinstance(raw_moves, dict)
    raw_faults = raw_result["faults"]
    assert isinstance(raw_faults, dict)
    raw_rounds = raw_result["rounds"]
    assert isinstance(raw_rounds, list)

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
    assert isinstance(raw_round, dict)
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
    assert isinstance(raw_fault, dict)
    return {"kind": raw_fault["kind"], "turn": raw_fault["turn"]}


def _operational_telemetry(
    request: MatchExecutionRequest, raw_result: dict[str, object]
) -> dict[str, object]:
    team_by_position = {"a": request.team_a_id, "b": request.team_b_id}
    raw_rounds = raw_result["rounds"]
    assert isinstance(raw_rounds, list)
    raw_faults = raw_result["faults"]
    assert isinstance(raw_faults, dict)
    raw_timing = raw_result["timing"]
    assert isinstance(raw_timing, dict)
    timing = dict(raw_timing)
    total_response_ns = timing.get("total_response_ns")
    if isinstance(total_response_ns, dict):
        timing["total_response_ns"] = {
            team_by_position[position]: duration
            for position, duration in total_response_ns.items()
        }
    raw_bots = raw_result["bots"]
    assert isinstance(raw_bots, dict)
    return {
        "tournament_id": request.tournament_id,
        "fixture_id": request.fixture_id,
        "match_id": request.match_id,
        "attempt_number": request.attempt_number,
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
