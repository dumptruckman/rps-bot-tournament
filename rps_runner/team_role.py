"""Immutable competitive roles for Teams in a Tournament."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class TeamRole(str, Enum):
    """Describe whether a Team may advance from qualification."""

    COMPETITOR = "competitor"
    CHALLENGER = "challenger"

    @property
    def playoff_eligible(self) -> bool:
        return self is TeamRole.COMPETITOR


def parse_team_role(value: object, location: str) -> TeamRole:
    """Parse an explicitly supplied JSON Team Role."""

    try:
        return TeamRole(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            location + " must be competitor or challenger"
        ) from error


def team_role_from_mapping(
    value: Mapping[str, object], location: str
) -> TeamRole:
    """Read a role while defaulting only an omitted legacy field."""

    if "role" not in value:
        return TeamRole.COMPETITOR
    return parse_team_role(value["role"], location + ".role")
