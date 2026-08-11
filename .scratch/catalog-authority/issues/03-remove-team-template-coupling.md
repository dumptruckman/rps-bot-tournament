# Remove Team Template coupling from the Runner

Status: ready-for-agent

Priority: 2

Blocked by: 01

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Remove participant-facing starter/template material from the Runner while
preserving internal conformance fixtures and a dependable way to test Tournament
execution. A user should no longer mistake Runner-owned practice fixtures for a
Team Template.

## Acceptance criteria

- [ ] Participant-facing starter strategies, template instructions, and template
  repository layouts are absent from the Runner package and documentation.
- [ ] Any public demo command that depends on participant-style bot files is
  removed or redesigned around clearly internal, packaged practice fixtures.
- [ ] Conformance practice artifacts remain catalog-owned and are explicitly
  described as certification fixtures rather than Team Templates.
- [ ] Installed-package behavior does not depend on source-tree-only bot files.
- [ ] Match, Tournament, preparation, rehearsal, and presentation tests remain
  independently runnable without the companion repository.
- [ ] The companion repository is the only documented source for a Team to begin
  authoring Team Source.

## Comments

This ticket does not move conformance or organizer-owned wrapper code out of the
Runner.
