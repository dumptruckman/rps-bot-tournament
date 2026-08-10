# Present Fixtures, history, and Playoff outcomes

Status: ready-for-agent

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

- [ ] Qualifying Fixtures preserve projection order and visibly distinguish
  scheduled, active, in-progress, complete, skipped, and administratively
  resolved states without choosing or announcing the next Match.
- [ ] Match history preserves projected phase, Fixture, and Match order and
  displays only each supplied Match ID, outcome, and winner; Double Forfeit is
  never presented as a draw.
- [ ] The Playoff Phase bracket preserves supplied seed and Fixture order,
  displays Bracket Lock and bracket-position replacement facts, and never seeds,
  advances, or resolves a Team in presentation code.
- [ ] A standings leader is never labeled Tournament Champion; the Champion is
  displayed only from the projection's non-null `champion` field.
- [ ] Pending operator review, completion without a Champion, and operator abort
  use safe audience copy while retaining prior committed facts and excluding
  suspected Team identities, evidence, organizer identity, and free-text notes.
- [ ] Live Match progress is limited to scheduled, active, and committed
  Match-boundary state; no uncommitted Round score or Turn animation is inferred.
- [ ] Automated browser tests cover Match start and commit, phase transition,
  pending review, bracket display, completion with and without a Champion, and
  abort.

## Comments

This issue is blocked only by the live presentation path. Replay can be
implemented independently after the same foundation.
