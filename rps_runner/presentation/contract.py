"""Narrow, versioned browser contract for live Tournament standings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORTED_PROJECTION_VERSION = 1
_STATUSES = frozenset(
    (
        "paused",
        "running",
        "awaiting_security_ruling",
        "complete",
        "aborted",
    )
)
_PHASES = frozenset(("qualifying", "playoff"))
_STANDING_FIELDS = (
    "team_id",
    "standing_points",
    "series_wins",
    "match_differential",
    "round_differential",
    "protocol_fault_forfeits",
    "tie_break_key",
)
_INTEGER_STANDING_FIELDS = frozenset(_STANDING_FIELDS[1:-1])


class ProjectionContractError(ValueError):
    """A Scoreboard Projection cannot enter the browser contract."""


def project_live(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the allowlisted live standings contract."""

    if not isinstance(projection, Mapping):
        raise ProjectionContractError("Scoreboard Projection must be an object")
    version = projection.get("version")
    if version != SUPPORTED_PROJECTION_VERSION:
        raise ProjectionContractError(
            f"Unsupported Scoreboard Projection version: {version!r}"
        )
    tournament_id = _required_string(projection, "tournament_id")
    status = _required_string(projection, "status")
    if status not in _STATUSES:
        raise ProjectionContractError("Scoreboard Projection status is invalid")
    phase = _required_string(projection, "phase")
    if phase not in _PHASES:
        raise ProjectionContractError("Scoreboard Projection phase is invalid")

    raw_teams = _required_list(projection, "teams")
    teams: list[dict[str, Any]] = []
    team_ids: set[str] = set()
    for index, raw_team in enumerate(raw_teams):
        team = _required_mapping(raw_team, f"teams[{index}]")
        team_id = _required_string(team, "team_id", f"teams[{index}]")
        if team_id in team_ids:
            raise ProjectionContractError("Team IDs must be unique")
        team_ids.add(team_id)
        copied: dict[str, Any] = {
            "team_id": team_id,
            "display_name": _required_string(
                team, "display_name", f"teams[{index}]"
            ),
        }
        teams.append(copied)

    raw_standings = _required_list(projection, "standings")
    standings: list[dict[str, Any]] = []
    standing_team_ids: set[str] = set()
    for index, raw_standing in enumerate(raw_standings):
        standing = _required_mapping(raw_standing, f"standings[{index}]")
        copied_standing: dict[str, Any] = {}
        for field in _STANDING_FIELDS:
            value = standing.get(field)
            if field in _INTEGER_STANDING_FIELDS:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ProjectionContractError(
                        f"standings[{index}].{field} must be an integer"
                    )
            elif not isinstance(value, str) or not value:
                raise ProjectionContractError(
                    f"standings[{index}].{field} must be a non-empty string"
                )
            copied_standing[field] = value
        standing_team_id = copied_standing["team_id"]
        if standing_team_id not in team_ids:
            raise ProjectionContractError(
                f"standings[{index}].team_id does not identify a projected Team"
            )
        if standing_team_id in standing_team_ids:
            raise ProjectionContractError("Standings Team IDs must be unique")
        standing_team_ids.add(standing_team_id)
        standings.append(copied_standing)

    return {
        "version": SUPPORTED_PROJECTION_VERSION,
        "tournament_id": tournament_id,
        "status": status,
        "phase": phase,
        "teams": teams,
        "standings": standings,
    }


def _required_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionContractError(f"{location} must be an object")
    return value


def _required_list(value: Mapping[str, Any], field: str) -> list[Any]:
    candidate = value.get(field)
    if not isinstance(candidate, list):
        raise ProjectionContractError(f"{field} must be an array")
    return candidate


def _required_string(
    value: Mapping[str, Any], field: str, location: str = "projection"
) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ProjectionContractError(
            f"{location}.{field} must be a non-empty string"
        )
    return candidate
