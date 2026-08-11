# Remove Team Template coupling from the Runner

Status: resolved

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

- [x] Participant-facing starter strategies, template instructions, and template
  repository layouts are absent from the Runner package and documentation.
- [x] Any public demo command that depends on participant-style bot files is
  removed or redesigned around clearly internal, packaged practice fixtures.
- [x] Conformance practice artifacts remain catalog-owned and are explicitly
  described as certification fixtures rather than Team Templates.
- [x] Installed-package behavior does not depend on source-tree-only bot files.
- [x] Match, Tournament, preparation, rehearsal, and presentation tests remain
  independently runnable without the companion repository.
- [x] The companion repository is the only documented source for a Team to begin
  authoring Team Source.

## Comments

This ticket does not move conformance or organizer-owned wrapper code out of the
Runner.

## Answer

The source-tree `bots/` starters and participant-facing template instructions
are removed. The organizer demo now runs two strategies through a packaged
`rps_runner.certification_fixture` program whose digest and manifest identity
are sealed with the demo Tournament. Match tests use test-local protocol
fixtures instead of Runner-root Team-like source files.

The README identifies catalog practice artifacts as organizer certification
fixtures and points Team authors only to `rps-bot-templates`. Protocol language
now describes the catalog-owned wrapper and Team Source schema without treating
the Runner as a template source.

An isolated `pip install --target` test invokes the installed `rps-tournament`
console command from outside the checkout and completes a real 300-Turn Match
without the companion repository or source-tree strategy fixtures. The full
Python suite also covers Match, Tournament, preparation, rehearsal, and
presentation without the companion repository.
