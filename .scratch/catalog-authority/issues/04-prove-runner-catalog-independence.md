# Prove Runner catalog independence

Status: ready-for-agent

Priority: 2

Blocked by: 02, 03

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Provide the release-grade proof that the Runner-owned catalog is complete and
that official organizer workflows have no hidden dependency on Team Templates
or their repository.

## Acceptance criteria

- [ ] A clean checkout publishes and verifies the catalog release using only
  Runner-owned files and pinned external runtime identities.
- [ ] Offline preparation, source validation, Bot Artifact building, Final
  Validation, Tournament planning/execution, rehearsal, and presentation pass
  without the companion repository present.
- [ ] Repository and workflow scans prove there is no checkout, import, path, or
  network dependency on the Team Template repository.
- [ ] The catalog release contains no Team Template file or Team Template digest.
- [ ] Internal practice fixtures remain reproducible and do not appear in the
  participant-facing interface.
- [ ] The retained evidence exposes the exact catalog identity required by the
  companion repository's cross-repository cutover proof.

## Comments

Completion unblocks `rps-bot-templates` catalog-consumer ticket 04.
