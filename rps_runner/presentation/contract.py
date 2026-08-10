"""Narrow, versioned browser contract for live Tournament facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SUPPORTED_PROJECTION_VERSION = 1
SUPPORTED_REPLAY_VERSION = 1
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
_FIXTURE_STATUSES = frozenset(
    ("scheduled", "active", "in_progress", "complete", "skipped")
)
_MATCH_OUTCOMES = frozenset(("win", "draw", "double_forfeit"))
_PLAYOFF_STAGES = frozenset(("semifinal", "final"))


class ProjectionContractError(ValueError):
    """A Scoreboard Projection cannot enter the browser contract."""


class ReplayContractError(ValueError):
    """A terminal Competition Record cannot enter the replay contract."""


def project_live(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the allowlisted live Tournament contract."""

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
        if "eligible" in team:
            eligible = team["eligible"]
            if not isinstance(eligible, bool):
                raise ProjectionContractError(
                    f"teams[{index}].eligible must be a boolean"
                )
            copied["eligible"] = eligible
        if "status" in team:
            copied["status"] = _required_string(
                team, "status", f"teams[{index}]"
            )
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

    fixtures = _project_fixtures(
        projection,
        "fixtures",
        team_ids,
        playoff=False,
    )
    champion = projection.get("champion")
    if champion is not None:
        if not isinstance(champion, str) or champion not in team_ids:
            raise ProjectionContractError(
                "projection.champion must identify a projected Team or be null"
            )

    live: dict[str, Any] = {
        "version": SUPPORTED_PROJECTION_VERSION,
        "tournament_id": tournament_id,
        "status": status,
        "phase": phase,
        "teams": teams,
        "standings": standings,
        "fixtures": fixtures,
        "champion": champion,
    }
    if "completion_reason" in projection:
        live["completion_reason"] = _required_string(
            projection, "completion_reason"
        )
    if "security_review" in projection:
        review = _required_mapping(
            projection["security_review"], "security_review"
        )
        live["security_review"] = {
            "fixture_id": _required_string(
                review, "fixture_id", "security_review"
            ),
            "match_id": _required_string(
                review, "match_id", "security_review"
            ),
        }
    if "bracket" in projection:
        live["bracket"] = _project_bracket(projection["bracket"], team_ids)
    return live


def project_replay(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy the allowlisted completed-Match replay contract."""

    if not isinstance(record, Mapping) or record.get("type") != "match_terminal":
        raise ReplayContractError("Replay requires a terminal Competition Record")
    phase = _replay_string(record, "phase")
    if phase not in _PHASES:
        raise ReplayContractError("Replay phase is invalid")
    fixture_id = _replay_string(record, "fixture_id")
    match_id = _replay_string(record, "match_id")
    match_ordinal = _replay_integer(record.get("match_ordinal"), "match_ordinal")
    if match_ordinal < 1:
        raise ReplayContractError("Replay match_ordinal must be positive")

    raw_team_ids = _replay_sequence(record.get("team_ids"), "team_ids")
    if (
        len(raw_team_ids) != 2
        or any(not isinstance(team_id, str) or not team_id for team_id in raw_team_ids)
        or raw_team_ids[0] == raw_team_ids[1]
    ):
        raise ReplayContractError("Replay team_ids must identify two Teams")
    team_ids = [raw_team_ids[0], raw_team_ids[1]]
    team_id_set = set(team_ids)

    outcome = _replay_string(record, "outcome")
    if outcome not in _MATCH_OUTCOMES:
        raise ReplayContractError("Replay outcome is invalid")
    winner_team_id = record.get("winner_team_id")
    if winner_team_id is not None and winner_team_id not in team_id_set:
        raise ReplayContractError("Replay winner_team_id is invalid")
    if outcome in ("draw", "double_forfeit") and winner_team_id is not None:
        raise ReplayContractError("Replay outcome cannot declare a Match winner")
    if outcome == "win" and winner_team_id is None:
        raise ReplayContractError("Winning replay must declare a Match winner")

    raw_round_wins = record.get("round_wins")
    if not isinstance(raw_round_wins, Mapping) or set(raw_round_wins) != team_id_set:
        raise ReplayContractError("Replay round_wins do not match Teams")
    round_wins: dict[str, int] = {}
    for team_id in team_ids:
        value = _replay_integer(raw_round_wins.get(team_id), "round_wins")
        if value < 0:
            raise ReplayContractError("Replay Round wins cannot be negative")
        round_wins[team_id] = value

    rounds: list[dict[str, Any]] = []
    for index, raw_round in enumerate(
        _replay_sequence(record.get("rounds"), "rounds")
    ):
        location = f"rounds[{index}]"
        if not isinstance(raw_round, Mapping):
            raise ReplayContractError(f"Replay {location} must be an object")
        turn = _replay_integer(raw_round.get("turn"), f"{location}.turn")
        if turn != index:
            raise ReplayContractError("Replay completed Round Turns are invalid")
        raw_moves = raw_round.get("moves")
        if not isinstance(raw_moves, Mapping) or set(raw_moves) != team_id_set:
            raise ReplayContractError(f"Replay {location}.moves do not match Teams")
        moves: dict[str, str] = {}
        for team_id in team_ids:
            move = raw_moves.get(team_id)
            if move not in ("R", "P", "S"):
                raise ReplayContractError(f"Replay {location}.moves are invalid")
            moves[team_id] = move
        round_winner = raw_round.get("winner_team_id")
        if round_winner is not None and round_winner not in team_id_set:
            raise ReplayContractError(f"Replay {location} winner is invalid")
        rounds.append(
            {
                "round": index + 1,
                "turn": turn,
                "moves": moves,
                "winner_team_id": round_winner,
            }
        )

    raw_faults = record.get("faults")
    if not isinstance(raw_faults, Mapping) or set(raw_faults) != team_id_set:
        raise ReplayContractError("Replay faults do not match Teams")
    faults: list[dict[str, Any]] = []
    for team_id in team_ids:
        raw_fault = raw_faults.get(team_id)
        if raw_fault is None:
            continue
        if not isinstance(raw_fault, Mapping) or set(raw_fault) != {"kind", "turn"}:
            raise ReplayContractError("Replay fault shape is invalid")
        kind = _replay_string(raw_fault, "kind", "fault")
        turn = _replay_integer(raw_fault.get("turn"), "fault.turn")
        if turn != len(rounds):
            raise ReplayContractError("Replay fault Turn is invalid")
        faults.append({"team_id": team_id, "kind": kind, "turn": turn})

    protocol_forfeit_team_id = record.get("protocol_forfeit_team_id")
    if (
        protocol_forfeit_team_id is not None
        and protocol_forfeit_team_id not in team_id_set
    ):
        raise ReplayContractError("Replay protocol_forfeit_team_id is invalid")
    if outcome == "double_forfeit":
        if len(faults) != 2 or protocol_forfeit_team_id is not None:
            raise ReplayContractError("Double Forfeit replay faults are invalid")
    elif protocol_forfeit_team_id is not None:
        if (
            outcome != "win"
            or len(faults) != 1
            or faults[0]["team_id"] != protocol_forfeit_team_id
            or winner_team_id == protocol_forfeit_team_id
        ):
            raise ReplayContractError("Protocol forfeit replay faults are invalid")
    elif faults:
        raise ReplayContractError("Ordinary replay cannot contain protocol faults")

    return {
        "version": SUPPORTED_REPLAY_VERSION,
        "phase": phase,
        "fixture_id": fixture_id,
        "match_id": match_id,
        "match_ordinal": match_ordinal,
        "team_ids": team_ids,
        "outcome": outcome,
        "winner_team_id": winner_team_id,
        "round_wins": round_wins,
        "protocol_forfeit_team_id": protocol_forfeit_team_id,
        "rounds": rounds,
        "faults": faults,
    }


def _replay_sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, (list, tuple)):
        raise ReplayContractError(f"Replay {field} must be an array")
    return list(value)


def _replay_string(
    value: Mapping[str, Any], field: str, location: str = "record"
) -> str:
    candidate = value.get(field)
    if not isinstance(candidate, str) or not candidate:
        raise ReplayContractError(
            f"Replay {location}.{field} must be a non-empty string"
        )
    return candidate


def _replay_integer(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReplayContractError(f"Replay {field} must be an integer")
    return value


def _project_bracket(
    value: Any, team_ids: set[str]
) -> dict[str, Any]:
    bracket = _required_mapping(value, "bracket")
    locked = bracket.get("locked")
    if not isinstance(locked, bool):
        raise ProjectionContractError("bracket.locked must be a boolean")
    raw_seeds = _required_list(bracket, "seeds", "bracket")
    seeds: list[dict[str, Any]] = []
    for index, raw_seed in enumerate(raw_seeds):
        seed = _required_mapping(raw_seed, f"bracket.seeds[{index}]")
        number = seed.get("seed")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise ProjectionContractError(
                f"bracket.seeds[{index}].seed must be a positive integer"
            )
        team_id = _projected_team_id(
            seed.get("team_id"),
            team_ids,
            f"bracket.seeds[{index}].team_id",
        )
        seeds.append({"seed": number, "team_id": team_id})
    return {
        "locked": locked,
        "seeds": seeds,
        "fixtures": _project_fixtures(
            bracket,
            "fixtures",
            team_ids,
            playoff=True,
            location="bracket",
        ),
    }


def _project_fixtures(
    value: Mapping[str, Any],
    field: str,
    projected_team_ids: set[str],
    *,
    playoff: bool,
    location: str = "projection",
) -> list[dict[str, Any]]:
    raw_fixtures = _required_list(value, field, location)
    fixtures: list[dict[str, Any]] = []
    fixture_location = field if location == "projection" else f"{location}.{field}"
    for index, raw_fixture in enumerate(raw_fixtures):
        item_location = f"{fixture_location}[{index}]"
        fixture = _required_mapping(raw_fixture, item_location)
        raw_team_ids = _required_list(fixture, "team_ids", item_location)
        if len(raw_team_ids) != 2:
            raise ProjectionContractError(
                f"{item_location}.team_ids must contain two bracket positions"
            )
        team_ids: list[Any] = []
        for team_index, raw_team_id in enumerate(raw_team_ids):
            team_location = f"{item_location}.team_ids[{team_index}]"
            if raw_team_id is None and playoff:
                team_ids.append(None)
            else:
                team_ids.append(
                    _projected_team_id(
                        raw_team_id, projected_team_ids, team_location
                    )
                )
        status = _required_string(fixture, "status", item_location)
        if status not in _FIXTURE_STATUSES:
            raise ProjectionContractError(f"{item_location}.status is invalid")
        copied: dict[str, Any] = {
            "fixture_id": _required_string(
                fixture, "fixture_id", item_location
            ),
            "team_ids": team_ids,
            "status": status,
            "matches": _project_matches(
                fixture, item_location, projected_team_ids
            ),
        }
        for optional_field in ("active_match_id", "skip_reason"):
            if optional_field in fixture:
                copied[optional_field] = _required_string(
                    fixture, optional_field, item_location
                )
        if playoff:
            stage = _required_string(fixture, "stage", item_location)
            if stage not in _PLAYOFF_STAGES:
                raise ProjectionContractError(f"{item_location}.stage is invalid")
            copied["stage"] = stage
        if "administrative_series_win" in fixture:
            administrative = _required_mapping(
                fixture["administrative_series_win"],
                f"{item_location}.administrative_series_win",
            )
            copied["administrative_series_win"] = {
                "winner_team_id": _projected_team_id(
                    administrative.get("winner_team_id"),
                    projected_team_ids,
                    f"{item_location}.administrative_series_win.winner_team_id",
                ),
                "reason_code": _required_string(
                    administrative,
                    "reason_code",
                    f"{item_location}.administrative_series_win",
                ),
            }
        if playoff and "resolved_team_id" in fixture:
            copied["resolved_team_id"] = _projected_team_id(
                fixture.get("resolved_team_id"),
                projected_team_ids,
                f"{item_location}.resolved_team_id",
            )
        if playoff and "bracket_position_replacement" in fixture:
            replacement_location = (
                f"{item_location}.bracket_position_replacement"
            )
            replacement = _required_mapping(
                fixture["bracket_position_replacement"], replacement_location
            )
            reinstated = replacement.get("reinstated_team_id")
            if reinstated is not None:
                reinstated = _projected_team_id(
                    reinstated,
                    projected_team_ids,
                    f"{replacement_location}.reinstated_team_id",
                )
            copied["bracket_position_replacement"] = {
                "disqualified_team_id": _projected_team_id(
                    replacement.get("disqualified_team_id"),
                    projected_team_ids,
                    f"{replacement_location}.disqualified_team_id",
                ),
                "reinstated_team_id": reinstated,
                "source_fixture_id": _required_string(
                    replacement, "source_fixture_id", replacement_location
                ),
                "reason_code": _required_string(
                    replacement, "reason_code", replacement_location
                ),
            }
        fixtures.append(copied)
    return fixtures


def _project_matches(
    fixture: Mapping[str, Any],
    location: str,
    projected_team_ids: set[str],
) -> list[dict[str, Any]]:
    raw_matches = _required_list(fixture, "matches", location)
    matches: list[dict[str, Any]] = []
    for index, raw_match in enumerate(raw_matches):
        item_location = f"{location}.matches[{index}]"
        match = _required_mapping(raw_match, item_location)
        outcome = _required_string(match, "outcome", item_location)
        if outcome not in _MATCH_OUTCOMES:
            raise ProjectionContractError(f"{item_location}.outcome is invalid")
        winner = match.get("winner_team_id")
        if winner is not None:
            winner = _projected_team_id(
                winner,
                projected_team_ids,
                f"{item_location}.winner_team_id",
            )
        matches.append(
            {
                "match_id": _required_string(match, "match_id", item_location),
                "outcome": outcome,
                "winner_team_id": winner,
            }
        )
    return matches


def _projected_team_id(
    value: Any, projected_team_ids: set[str], location: str
) -> str:
    if not isinstance(value, str) or value not in projected_team_ids:
        raise ProjectionContractError(
            f"{location} must identify a projected Team"
        )
    return value


def _required_mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionContractError(f"{location} must be an object")
    return value


def _required_list(
    value: Mapping[str, Any], field: str, location: str = "projection"
) -> list[Any]:
    candidate = value.get(field)
    if not isinstance(candidate, list):
        raise ProjectionContractError(f"{location}.{field} must be an array")
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
