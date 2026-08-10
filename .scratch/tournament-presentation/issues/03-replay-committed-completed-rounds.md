# Replay committed completed Rounds

Status: resolved

Priority: 2

Blocked by: 01

## Parent

[Tournament Presentation](../PRD.md)

## What to build

Let an organizer or audience member select a completed Match and step through
its committed completed Rounds without re-executing either Bot Artifact. Replay
uses one verified `match_terminal` Competition Record and returns an explicitly
allowlisted browser representation.

## Acceptance criteria

- [x] Replay is available only when a Match appears completed in the current
  Scoreboard Projection and has exactly one verified terminal Competition
  Record with the requested Match ID.
- [x] Record loading verifies canonical envelopes, sequence, hashes, and JSON
  through the existing storage seam; replay never opens a Match Attempt or
  launches a Bot Artifact.
- [x] Each replay frame preserves the recorded completed Round order and shows a
  one-based Round label, the record's explicit zero-based Turn, both recorded
  moves, and the recorded Round winner or draw.
- [x] A protocol fault is presented as a terminal event on its recorded Turn
  after the final completed Round, using only the normalized fault kind and Turn.
- [x] A Double Forfeit shows both normalized faults on their shared Turn,
  declares no Match winner, and remains distinct from a draw while retaining
  all earlier completed Rounds.
- [x] Replay responses exclude raw move-history strings, seeds, Bot Positions,
  artifact digests, Security Violation suspects and evidence, operator details,
  and all Operational Telemetry.
- [x] Missing, uncommitted, ambiguous, or unverifiable Match records produce an
  unavailable replay without clearing or corrupting the live view.
- [x] Contract, HTTP, and browser tests cover an ordinary Match, protocol
  forfeit, Double Forfeit, keyboard replay controls, and unavailable replay.

## Comments

A Turn is a protocol request and response attempt. Only a Turn with two valid
moves creates a completed Round; the replay must keep those concepts distinct.

## Answer

Implemented a versioned, allowlisted replay contract and read-only replay HTTP
endpoint backed by the verified Competition Record loader. Added an accessible
browser replay panel with one-based Round labels, explicit zero-based Turns,
terminal protocol-fault events, distinct Double Forfeit handling, keyboard
navigation, stale-request protection, and unavailable-state isolation. Added
contract, HTTP, storage-integrity, sensitive-field exclusion, and browser
coverage for the acceptance scenarios.
