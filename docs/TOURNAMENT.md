# Tournament Design

**Status:** Draft

This document defines how a set of accepted bot artifacts becomes a reproducible
Rock–Paper–Scissors tournament, including its schedule, results, standings, and
replays. It complements the bot communication rules in
[`protocol/PROTOCOL.md`](../protocol/PROTOCOL.md).

## Purpose

The tournament should let organizers run the complete competition from a fixed
roster and configuration without making participants understand scheduling,
scoring, or execution infrastructure.

Given the same accepted bot artifacts and tournament configuration, the
tournament should reproduce the same fixtures, bot-visible seeds, moves,
outcomes, and final standings.

## Existing Foundation

The local match runner already:

- Starts two bot processes for one match.
- Sends both bots the version 1 line protocol.
- Enforces per-move and total response-time limits.
- Records moves, round outcomes, faults, scores, stderr, and timing.
- Produces one JSON result for the match.
- Supplies the protocol version, scheduled rounds, and deterministic seed to
  both bots.

The tournament layer does not yet exist. It will be responsible for arranging
matches, invoking the match runner, retaining results, and deriving standings.

## Design Boundary

This document covers:

- Tournament format and phases.
- Roster identity and eligibility at tournament start.
- Fixture generation and ordering.
- Seed derivation and bot-visible randomness.
- Match and fixture scoring.
- Forfeits, double forfeits, and infrastructure failures.
- Ranking and tie-breaking.
- Tournament result and replay artifacts.
- Progress reporting, interruption, and resumption.

Submission upload, source validation, language-specific builds, container
hardening, and the scoreboard user interface are separate concerns. This design
must define the contracts those components consume or produce where they meet
the tournament layer.

## Decisions

### 1. Competition Format

The official tournament has two phases:

1. A complete round-robin qualifying phase in which every accepted bot competes
   against every other accepted bot.
2. A four-bot, single-elimination playoff seeded from the qualifying standings.

The playoff semifinals pair seed 1 against seed 4 and seed 2 against seed 3.
The semifinal winners advance to the final, and the final winner is the
tournament champion.

Whether a qualifying pairing or playoff fixture contains one match or a series
of matches remains open.

### 2. Competitor Identity

The Team is the competitive identity. Standings rank Teams, and the Team whose
entry wins the playoff final is the Tournament Champion.

Each Team enters exactly one immutable Bot Artifact in a Tournament. Tournament
records identify both the Team and the exact Bot Artifact so that organizer- and
participant-facing results remain understandable while executions remain
reproducible.

A Team cannot replace its Bot Artifact after the Tournament begins.

### 3. Contest Terminology

A Turn is one protocol request and response attempt, identified by a zero-based
turn number. A Turn can end in a protocol fault before a Round is completed.

A Round is two valid moves and the resulting Rock–Paper–Scissors outcome.

A Match is one independently executed and scored head-to-head contest between
two Bot Artifacts. It is scheduled for a fixed number of Turns, starts fresh bot
processes, and ends normally or by forfeit.

A Fixture is a scheduled contest between two Teams within a Tournament phase.
A Fixture contains one Match unless its rules require a Series.

A Series is a Fixture resolved across multiple Matches. Every Fixture in this
Tournament uses a Series.

### 4. Fixture Structure

Every qualifying and playoff Fixture is a best-of-three Series. Each Match:

- Is scheduled for 300 Turns.
- Starts fresh bot processes.
- Uses its own deterministically derived seed.

A Fixture requires at most three Matches. It may finish after two Matches when
one Team wins both. Otherwise, the third Match is played.

The Series structure exists to exercise Bot Artifacts across independent seeds
and initial process states. It does not excuse resource leaks, crashes, or other
Bot Artifact faults.

### 5. Series Scoring and Draws

A Match win awards one Series Point to its winner. A drawn Match awards one-half
Series Point to each Team.

After the required Matches are complete, the Team with more Series Points wins
the Series. A tied qualifying Series is recorded as a draw. If a playoff Series
is tied, the higher-seeded Team advances. The playoff rule guarantees a bounded,
deterministic outcome and rewards qualifying performance.

### 6. Bot Positions

Bot Position `a` or `b` is an internal Match execution label with no competitive
meaning and is not exposed to Bot Artifacts.

For each Series:

1. Match 1 assigns Bot Positions deterministically from the Fixture seed.
2. Match 2 swaps the Match 1 positions.
3. Match 3 assigns positions independently and deterministically from the
   Fixture seed.

The Match Runner must provide equivalent timing and resources to both Bot
Positions. Position rotation is defense in depth and does not replace that
fairness requirement.

### 7. Fixture Schedule

Before qualification begins, the Tournament orders Teams by canonical Team ID
and then deterministically shuffles them using the Tournament seed. The circle
method generates the complete round-robin schedule from that order.

Qualifying Fixtures are grouped into Fixture Batches. Each Team appears in at
most one Fixture per Batch. When the roster contains an odd number of Teams, one
Team has a bye in each Batch.

The complete qualifying schedule, including Fixture IDs and canonical result
ordering, is fixed before execution begins. Execution may be sequential or
parallel, but execution order and completion order cannot change the canonical
schedule or result ordering.

The two playoff semifinals follow completion of the Qualifying Phase. The final
follows completion of both semifinals.

### 8. Independent Bot Seeds

Each Bot Artifact receives its own deterministic seed for each Match. The
bot-visible seed is derived from the Match seed and canonical Team ID; it does
not depend on Bot Position.

Consequently:

- Opposing Bot Artifacts do not receive correlated random streams merely
  because they began from the same template.
- Swapping Bot Positions does not change a Team's random stream.
- Replaying the same Match configuration gives each Team the same seed.

Official language wrappers must expose deterministic seeded-random behavior.
Different languages are not required to produce identical random streams.

### 9. Language-Specific Seed Adapters

The Match Runner supplies each Bot Artifact's bot-visible seed as an unsigned
64-bit decimal string. The organizer-owned language wrapper parses that value
losslessly and deterministically adapts it to the language's random-number
generator.

A wrapper may use a language-native seeded generator when it can satisfy the
contract, or provide its own seeded generator when the language has no suitable
native implementation. When the native generator accepts a narrower seed, the
wrapper uses a documented, well-distributed deterministic mapping rather than an
unchecked cast.

Given the same bot-visible seed, wrapper version, runtime, and sequence of random
API calls, a Bot Artifact must receive the same random values. Different
language wrappers may produce different streams from the same bot-visible seed.
The wrapper and runtime are frozen as part of the immutable Bot Artifact.

## Questions to Resolve

Questions are ordered by dependency. Later decisions should build on earlier
answers.

1. What versioned algorithm derives Fixture, Match, and bot-visible seeds from
   the Tournament seed?
2. How does a Series outcome contribute to Tournament standings?
3. How are protocol forfeits, double forfeits, and infrastructure failures
   scored or retried?
4. Which tie-breakers apply, and in what order?
5. Besides identity and artifact digest, what roster data is canonical?
6. Which outputs are canonical deterministic records, and which are
    non-deterministic operational telemetry?
7. What information must be available to a live scoreboard, and when?
8. What are the interruption, checkpoint, and resume semantics?
9. What operator controls are allowed after a Tournament starts?
10. What scale and runtime must the official Tournament support?

## Open Consistency Issue

The project goal says repeated tournaments should be identical, while current
match results include measured response durations. Durations naturally vary
between executions. This design must separate deterministic competition records
from operational timing telemetry, or define reproducibility less strictly.

The protocol currently says that fresh processes start for every Match, but it
also uses Fixture and "playoff set" as apparent synonyms for Match. Once this
design is settled, `protocol/PROTOCOL.md` must be aligned with the canonical
terms above.
