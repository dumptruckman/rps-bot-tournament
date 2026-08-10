# Define the first Tournament presentation slice

Status: resolved

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

- [x] The design names the intended users, event-day workflow, supported local
  runtime, and the smallest independently useful first release.
- [x] Every displayed competitive fact is mapped to the Scoreboard Projection
  or canonical Competition Records; the presentation layer does not calculate
  standings, choose the next Match, or mutate Tournament state.
- [x] The live-update mechanism handles atomic projection replacement,
  interruption, resumption, phase transitions, pending operator review,
  completion, and abort without requiring the Tournament Runner to serve UI
  traffic.
- [x] The replay design uses committed Match facts, distinguishes Turns from
  completed Rounds, represents protocol faults and Double Forfeits, and does not
  expose Operational Telemetry or raw Security Violation evidence.
- [x] The design settles the implementation boundary, asset and dependency
  strategy, browser support, launch command, failure behavior, and verification
  approach for the first release.
- [x] Follow-up implementation work is split into agent-sized vertical slices
  with explicit blocking edges and acceptance criteria.

## Comments

The Tournament Runner's Scoreboard Projection remains the live presentation
input, while Competition Records remain the replay authority. Presentation is a
consumer of those artifacts, never a new source of competitive truth.

## Answer

The decision-ready design is published as
[`docs/PRESENTATION.md`](../../../docs/PRESENTATION.md). It defines a separate
loopback presentation process, an allowlisted Scoreboard Projection adapter, and
verified committed-record replay without moving competitive authority into the
presentation layer.

The approved implementation work is published under
[`tournament-presentation`](../../tournament-presentation/PRD.md) as four
agent-sized vertical slices. The live standings foundation is the initial
frontier; Fixture and Playoff presentation and committed-Round replay can proceed
independently after it, followed by integrated event-day hardening.
