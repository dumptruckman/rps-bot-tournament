"""Structurally distinct exact and canonical Bot Artifact identities."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping


@dataclass(frozen=True)
class CanonicalBotArtifactIdentity:
    identity_fields: Mapping[str, Any]

    def as_mapping(self) -> Mapping[str, Any]:
        return self.identity_fields


@dataclass(frozen=True)
class ExactValidatedBotArtifactManifest:
    manifest_fields: Mapping[str, Any]

    @property
    def artifact_digest(self) -> str:
        return str(self.manifest_fields["artifact_digest"])

    @property
    def platform(self) -> str:
        return str(self.manifest_fields["platform"])

    @property
    def validation_identity(self) -> str:
        return str(self.manifest_fields["validation_identity"])

    def as_mapping(self) -> Mapping[str, Any]:
        return self.manifest_fields

    def canonical_identity(self) -> CanonicalBotArtifactIdentity:
        canonical = json.loads(json.dumps(self.manifest_fields))
        canonical.pop("retention", None)
        image = canonical.get("image")
        if isinstance(image, dict):
            image.pop("local_image_id", None)
        return CanonicalBotArtifactIdentity(canonical)
