"""Structurally distinct exact and canonical Bot Artifact identities."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class CanonicalBotArtifactIdentity:
    values: Mapping[str, Any]

    def as_mapping(self) -> Mapping[str, Any]:
        return self.values


@dataclass(frozen=True)
class ExactValidatedBotArtifactManifest:
    values: Mapping[str, Any]

    @property
    def artifact_digest(self) -> str:
        return str(self.values["artifact_digest"])

    @property
    def platform(self) -> str:
        return str(self.values["platform"])

    @property
    def validation_identity(self) -> str:
        return str(self.values["validation_identity"])

    def as_mapping(self) -> Mapping[str, Any]:
        return self.values

    def canonical_identity(self) -> CanonicalBotArtifactIdentity:
        canonical = json.loads(json.dumps(self.values))
        canonical.pop("retention", None)
        image = canonical.get("image")
        if isinstance(image, dict):
            image.pop("local_image_id", None)
        return CanonicalBotArtifactIdentity(canonical)
