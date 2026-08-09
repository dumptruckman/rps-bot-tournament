"""Supervised compatibility-repair input and retained provenance."""

from __future__ import annotations

from dataclasses import dataclass, replace
import difflib
import hashlib
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class CompatibilityRepairProvenance:
    """Complete retained evidence for one supervised compatibility repair."""

    original_source_digest: str
    replacement_source_digest: str
    diff: str
    diff_digest: str
    final_validation_identity: str

    def as_mapping(self) -> Mapping[str, Any]:
        return {
            "original_source_digest": self.original_source_digest,
            "replacement_source_digest": self.replacement_source_digest,
            "diff": self.diff,
            "diff_digest": self.diff_digest,
            "final_validation_identity": self.final_validation_identity,
        }


@dataclass(frozen=True)
class CompatibilityRepair:
    """A repair request that becomes evidence only with complete provenance."""

    source_directory: Path
    explanation: str
    provenance: Optional[CompatibilityRepairProvenance] = None

    def __post_init__(self) -> None:
        if not self.explanation.strip():
            raise ValueError("compatibility repair explanation must not be empty")

    def retain(
        self,
        original_bundle: Path,
        replacement_bundle: Path,
        original_source_digest: str,
        replacement_source_digest: str,
        final_validation_identity: str,
    ) -> "CompatibilityRepair":
        diff = _complete_source_diff(original_bundle, replacement_bundle)
        provenance = CompatibilityRepairProvenance(
            original_source_digest=original_source_digest,
            replacement_source_digest=replacement_source_digest,
            diff=diff,
            diff_digest=_digest_text(diff),
            final_validation_identity=final_validation_identity,
        )
        return replace(self, provenance=provenance)

    def retained_evidence(self) -> Mapping[str, Any]:
        if self.provenance is None:
            raise ValueError("compatibility repair provenance is incomplete")
        return {"explanation": self.explanation, **self.provenance.as_mapping()}


def _source_files(bundle: Path) -> Mapping[str, bytes]:
    source = bundle / "source"
    files: dict[str, bytes] = {}
    for path in sorted(source.rglob("*")):
        if path.is_file():
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    return files


def _complete_source_diff(original: Path, replacement: Path) -> str:
    before = _source_files(original)
    after = _source_files(replacement)
    output: list[str] = []
    for name in sorted(set(before) | set(after)):
        old = before.get(name)
        new = after.get(name)
        if old == new:
            continue
        if old is None and new == b"":
            output.extend(
                ("--- /dev/null\n", "+++ b/" + name + "\n", "@@ empty file added @@\n")
            )
            continue
        if old == b"" and new is None:
            output.extend(
                (
                    "--- a/" + name + "\n",
                    "+++ /dev/null\n",
                    "@@ empty file deleted @@\n",
                )
            )
            continue
        old_content = old or b""
        new_content = new or b""
        try:
            old_lines = old_content.decode("utf-8").splitlines(keepends=True)
            new_lines = new_content.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            output.extend(
                (
                    "--- a/" + name + "\n",
                    "+++ b/" + name + "\n",
                    "@@ binary content @@\n",
                    "-sha256:" + hashlib.sha256(old_content).hexdigest() + "\n",
                    "+sha256:" + hashlib.sha256(new_content).hexdigest() + "\n",
                    "-hex:" + old_content.hex() + "\n",
                    "+hex:" + new_content.hex() + "\n",
                )
            )
            continue
        output.extend(
            difflib.unified_diff(
                old_lines, new_lines, fromfile="a/" + name, tofile="b/" + name
            )
        )
    return "".join(output)


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
