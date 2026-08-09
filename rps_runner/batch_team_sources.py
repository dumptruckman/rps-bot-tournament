"""Map organizer-selected local sources to explicit Team domain values."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping, Optional

from rps_runner.batch_repair import CompatibilityRepair


MINIMUM_TEAMS = 4
MAXIMUM_TEAMS = 32
_TEAM_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")


@dataclass(frozen=True, order=True)
class TeamId:
    value: str

    def __post_init__(self) -> None:
        if _TEAM_ID.fullmatch(self.value) is None:
            raise ValueError("is not a valid Team ID")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TeamDisplayName:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("must be a non-empty string")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TeamSource:
    team_id: TeamId
    display_name: TeamDisplayName
    source_directory: Path
    repair: Optional[CompatibilityRepair] = None


def load_team_sources(path: Path) -> tuple[TeamSource, ...]:
    root = _read_mapping(path, "Team source mapping")
    values = root.get("teams")
    if not isinstance(values, list):
        raise ValueError("Team source mapping.teams must be an array")
    if not MINIMUM_TEAMS <= len(values) <= MAXIMUM_TEAMS:
        raise ValueError(
            "Team source mapping must contain four through thirty-two Teams"
        )

    teams = []
    seen: set[TeamId] = set()
    for ordinal, value in enumerate(values):
        location = "Team source mapping.teams[" + str(ordinal) + "]"
        if not isinstance(value, dict):
            raise ValueError(location + " must be an object")
        team_id_value = _required_string(value, "team_id", location)
        try:
            team_id = TeamId(team_id_value)
        except ValueError as error:
            raise ValueError(location + ".team_id " + str(error)) from error
        if team_id in seen:
            raise ValueError("Team IDs must be unique: " + str(team_id))
        seen.add(team_id)
        try:
            display_name = TeamDisplayName(
                _required_string(value, "display_name", location)
            )
        except ValueError as error:
            raise ValueError(location + ".display_name " + str(error)) from error
        source_directory = _source_directory(value, "source_directory", location)

        repair_value = value.get("repair")
        repair: Optional[CompatibilityRepair] = None
        if repair_value is not None:
            if not isinstance(repair_value, dict):
                raise ValueError(location + ".repair must be an object")
            repair_location = location + ".repair"
            repair = CompatibilityRepair(
                source_directory=_source_directory(
                    repair_value, "source_directory", repair_location
                ),
                explanation=_required_string(
                    repair_value, "explanation", repair_location
                ).strip(),
            )
        teams.append(TeamSource(team_id, display_name, source_directory, repair))
    return tuple(teams)


def _read_mapping(path: Path, description: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(description + " must be an existing non-symlink file")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("could not read " + description + ": " + str(error))
    if not isinstance(value, dict):
        raise ValueError(description + " must be a JSON object")
    return value


def _required_string(value: Mapping[str, Any], field: str, location: str) -> str:
    selected = value.get(field)
    if not isinstance(selected, str) or not selected.strip():
        raise ValueError(location + "." + field + " must be a non-empty string")
    return selected


def _source_directory(
    value: Mapping[str, Any], field: str, location: str
) -> Path:
    return Path(_required_string(value, field, location)).expanduser().absolute()
