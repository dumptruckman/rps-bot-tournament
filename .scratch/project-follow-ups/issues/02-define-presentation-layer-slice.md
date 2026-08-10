# Define the first Tournament presentation slice

Status: ready-for-agent

Priority: 2

Blocked by: None

## What to build

Produce a decision-ready design for the first local, read-only Tournament
presentation slice. The design must turn the runner-owned Scoreboard Projection
and canonical Competition Records into an organizer- and audience-facing live
view without moving scoring, scheduling, rulings, or competitive authority into
the presentation layer.

Define a narrow first delivery that makes current standings, Tournament phase,
Fixture and Match progress, playoff bracket, completed Match history, and the
Tournament Champion understandable. Include a replay path that presents the
recorded completed Rounds for a selected Match without re-executing either Bot
Artifact.

## Acceptance criteria

- [ ] The design names the intended users, event-day workflow, supported local
  runtime, and the smallest independently useful first release.
- [ ] Every displayed competitive fact is mapped to the Scoreboard Projection
  or canonical Competition Records; the presentation layer does not calculate
  standings, choose the next Match, or mutate Tournament state.
- [ ] The live-update mechanism handles atomic projection replacement,
  interruption, resumption, phase transitions, pending operator review,
  completion, and abort without requiring the Tournament Runner to serve UI
  traffic.
- [ ] The replay design uses committed Match facts, distinguishes Turns from
  completed Rounds, represents protocol faults and Double Forfeits, and does not
  expose Operational Telemetry or raw Security Violation evidence.
- [ ] The design settles the implementation boundary, asset and dependency
  strategy, browser support, launch command, failure behavior, and verification
  approach for the first release.
- [ ] Follow-up implementation work is split into agent-sized vertical slices
  with explicit blocking edges and acceptance criteria.

## Comments

The Tournament Runner's Scoreboard Projection remains the live presentation
input, while Competition Records remain the replay authority. Presentation is a
consumer of those artifacts, never a new source of competitive truth.
