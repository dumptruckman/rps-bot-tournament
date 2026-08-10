# Present Fixtures, history, and Playoff outcomes

Status: resolved

Priority: 2

Blocked by: 01

## Parent

[Tournament Presentation](../PRD.md)

## What to build

Extend the live page into an independently useful audience display that makes
Qualifying Phase Fixtures, Match-boundary progress, completed Match history,
the Playoff Phase bracket, pending organizer review, terminal outcomes, and the
Tournament Champion understandable using only facts already supplied by the
Scoreboard Projection.

## Acceptance criteria

- [x] Qualifying Fixtures preserve projection order and visibly distinguish
  scheduled, active, in-progress, complete, skipped, and administratively
  resolved states without choosing or announcing the next Match.
- [x] Match history preserves projected phase, Fixture, and Match order and
  displays only each supplied Match ID, outcome, and winner; Double Forfeit is
  never presented as a draw.
- [x] The Playoff Phase bracket preserves supplied seed and Fixture order,
  displays Bracket Lock and bracket-position replacement facts, and never seeds,
  advances, or resolves a Team in presentation code.
- [x] A standings leader is never labeled Tournament Champion; the Champion is
  displayed only from the projection's non-null `champion` field.
- [x] Pending operator review, completion without a Champion, and operator abort
  use safe audience copy while retaining prior committed facts and excluding
  suspected Team identities, evidence, organizer identity, and free-text notes.
- [x] Live Match progress is limited to scheduled, active, and committed
  Match-boundary state; no uncommitted Round score or Turn animation is inferred.
- [x] Automated browser tests cover Match start and commit, phase transition,
  pending review, bracket display, completion with and without a Champion, and
  abort.

## Comments

This issue is blocked only by the live presentation path. Replay can be
implemented independently after the same foundation.

## Answer

Extended the versioned browser contract and responsive live page with ordered
Qualifying Fixtures, Match-boundary progress, completed Match history, the
supplied Playoff bracket and replacements, safe review and terminal messaging,
and Champion presentation sourced only from the projection. Added pinned
Playwright coverage for the required live transitions and terminal outcomes.
