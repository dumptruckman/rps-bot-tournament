# Prove Runner catalog independence

Status: resolved

Priority: 2

Blocked by: 02, 03

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Provide the release-grade proof that the Runner-owned catalog is complete and
that official organizer workflows have no hidden dependency on Team Templates
or their repository.

## Acceptance criteria

- [x] A clean checkout publishes and verifies the catalog release using only
  Runner-owned files and pinned external runtime identities.
- [x] Offline preparation, source validation, Bot Artifact building, Final
  Validation, Tournament planning/execution, rehearsal, and presentation pass
  without the companion repository present.
- [x] Repository and workflow scans prove there is no checkout, import, path, or
  network dependency on the Team Template repository.
- [x] The catalog release contains no Team Template file or Team Template digest.
- [x] Internal practice fixtures remain reproducible and do not appear in the
  participant-facing interface.
- [x] The retained evidence exposes the exact catalog identity required by the
  companion repository's cross-repository cutover proof.

## Comments

Completion unblocks `rps-bot-templates` catalog-consumer ticket 04.

## Answer

`freeze-tournament-catalog prove` now creates and verifies one annotated Catalog
Release from an isolated clean checkout, reproduces the exact commit from its
offline bundle, and runs the official preparation-through-presentation suites
from a fresh checkout materialized from that bundle. The retained
`runner-catalog-independence-v1` JSON embeds the complete release manifest and a
copy-ready `compatibility_coordinates` object for the companion cutover.

The proof scans active Runner code, catalog and GitHub workflows, browser code,
tests, scripts, dependency metadata, and submodule metadata for companion
checkout, import, path, or network references. It requires the catalog tree to
contain only the catalog plus its declared closed set of organizer-owned asset
paths, rejects participant-facing starter paths and Template digest fields, and
verifies that the offline bundle reproduces the exact packaged internal fixture
identity without exposing that fixture as a participant command.

Catalog Release CI runs the proof on Python 3.9 and retains the exact bundle and
JSON evidence together for 90 days. The full Python suite passes with 406 tests
and three prepared-Docker opt-in skips; the Playwright presentation suite passes
all seven scenarios.
