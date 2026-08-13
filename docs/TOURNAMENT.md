# Tournament Design

**Status:** Accepted

This document defines how a set of accepted Bot Artifacts becomes a reproducible
Rock–Paper–Scissors tournament, including its schedule, results, standings, and
replays. It complements the bot communication rules in
[`PROTOCOL.md`](./PROTOCOL.md).

## Purpose

The tournament should let organizers run the complete competition from a fixed
roster and configuration without making participants understand scheduling,
scoring, or execution infrastructure.

The Tournament Manifest deterministically defines scheduling and seeds. Immutable
Competition Records preserve the competitive facts that actually occurred and
are the authoritative source for replay; re-execution is verification, not a
replacement for those records.

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

1. A complete round-robin qualifying phase in which every accepted Team competes
   against every other accepted Team.
2. Normally, a four-Team single-elimination playoff seeded from the highest-ranked
   eligible Competitor Teams in the qualifying standings. Challenger Teams never
   enter the playoff field. The bracket adapts if fewer eligible Competitor Teams
   remain.

The playoff semifinals pair seed 1 against seed 4 and seed 2 against seed 3.
The semifinal winners advance to the final, and its winner becomes Tournament
Champion. A sole eligible Team becomes Tournament Champion under the reduced
playoff rule.

### 2. Competitor Identity

The Team is the competitive identity. Standings rank Teams, and Tournament rules
select one eligible Team as Tournament Champion.

Each Team enters exactly one immutable Bot Artifact in a Tournament. Tournament
records identify both the Team and the exact Bot Artifact so that organizer- and
participant-facing results remain understandable while executions remain
reproducible.

Each Team also has one immutable Team Role. A `competitor` is eligible for
playoff selection unless disqualified. A `challenger` participates in the same
complete qualifying round robin, contributes to every Series and standing
calculation normally, and appears in qualifying standings, but is excluded when
the playoff field is selected. Missing roles in legacy Tournament inputs are
interpreted as `competitor`.

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
  because their Team Source uses the same Language Environment.
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

### 10. Seed Derivation

The organizer supplies one unsigned 64-bit Tournament Seed. The Tournament
records that value and `seed_derivation_version: 1`.

Version 1 derives child seeds with HMAC-SHA-256. The parent seed is encoded as
eight unsigned big-endian bytes and used as the HMAC key. The message contains
length-prefixed UTF-8 components for the fixed domain `rps-tournament/seed/v1`,
the child seed type, and its canonical identifier. The first eight digest bytes,
interpreted as an unsigned big-endian integer, are the derived seed.

The hierarchy is:

1. Derive each Fixture Seed from the Tournament Seed and canonical Fixture ID.
2. Derive each Match Seed from its Fixture Seed and one-based Match ordinal.
3. Derive each bot-visible seed from its Match Seed and canonical Team ID.

Schedule shuffling and Bot Position assignment use separate domain labels with
the same derivation primitive. All derived seeds are recorded as unsigned decimal
values in their corresponding deterministic result records.

### 11. Qualifying Standings

Qualifying standings award Standing Points from the outcome of each Series:

- A Series win awards three Standing Points to the winner.
- A Series draw awards one Standing Point to each Team.
- A Series loss awards no Standing Points.

Match outcomes and Series Points resolve a Series but do not directly award
Standing Points. Every qualifying Fixture therefore has equal weight regardless
of whether its Series takes two or three Matches.

### 12. Protocol-Fault Forfeits

When one Bot Artifact commits a protocol fault, it forfeits only the current
Match. The opponent receives the Match win and one Series Point; the faulting
Team receives none.

The fault ends the Match immediately. The result retains only Rounds that were
actually completed and does not synthesize wins for unplayed Rounds. The Series
continues with fresh processes unless the Match result has already decided it.
Repeated faults therefore lose the Series through ordinary Match forfeits.

Security violations, double faults, and infrastructure failures follow separate
rules.

### 13. Double Forfeits

When both Bot Artifacts fault during the same Turn, the Match ends as a Double
Forfeit. Neither Team receives a Match win or Series Points. Unlike a drawn
Match, a Double Forfeit does not reward either Team.

The Match consumes its ordinal in the best-of-three Series, and the Series
continues if another Match remains. Any resulting tied Series follows the normal
qualifying or playoff tie rule.

### 14. Security Violations

Suspected prohibited network access, host access, container escape, or similar
interference immediately stops the offending process and pauses Tournament
execution. The Tournament preserves the available evidence for organizer
review.

If the organizer confirms a Security Violation, the Team is disqualified from
the entire Tournament. If the behavior is not confirmed as attributable to the
Bot Artifact, it is handled as an infrastructure failure instead of a
competitive fault.

### 15. Disqualification During Qualification

When a Team is disqualified during the Qualifying Phase, every other eligible
Team receives an Administrative Series Win and three Standing Points for its
Fixture against the disqualified Team. Future Fixtures involving the
disqualified Team are not executed.

Completed Match results and replays remain unchanged as historical evidence.
Fixtures against the disqualified Team contribute no Match, Round, timing, or
fault statistics to tie-breakers; only the Administrative Series Win affects
standings.

### 16. Disqualification During Playoffs

Before the first playoff Match begins, a disqualified Team is removed, Challenger
Teams are excluded, up to the four highest-ranked eligible Competitor Teams are
selected, and the playoff bracket is seeded again under the eligible-Team rules.

Bracket Lock occurs when the first playoff Match begins. After Bracket Lock, no
Team enters the Playoff Phase from qualification and the bracket is not
reseeded:

- During a Series, the disqualified Team's opponent receives an Administrative
  Series Win and advances.
- If the disqualified Team previously advanced but its next Series has not
  begun, the Team it most recently eliminated is reinstated in its bracket
  position.
- Once the final begins, the remaining finalist becomes Tournament Champion if
  its opponent is disqualified.

All played Match records remain unchanged as historical evidence.

### 17. Infrastructure Failures

An Infrastructure Failure is a failed Match Attempt that is not attributable to
either Bot Artifact. It produces no competitive result.

The Tournament automatically retries the same canonical Match at most twice,
for three total Match Attempts. Every attempt uses identical Bot Artifacts,
seeds, Bot Positions, resource limits, and configuration. Failed attempts are
retained as operational telemetry and do not consume a Match ordinal in the
Series.

After three failed Match Attempts, the Tournament pauses for organizer
intervention. Resuming the Tournament retries the same Match; an organizer
cannot substitute or award a competitive result.

### 18. Qualifying Tie-Breakers

Qualifying standings apply the following criteria in order:

1. Most Standing Points.
2. Most qualifying Series wins.
3. Head-to-head Series result when exactly two Teams remain tied.
4. Best Match differential: qualifying Match wins minus Match losses.
5. Best Round differential from Rounds actually completed during qualification.
6. Fewest protocol-fault Match forfeits.
7. Lowest deterministic Tie-break Key derived from the Tournament Seed and
   canonical Team ID.

Administrative Series Wins contribute Standing Points but no Match, Round, or
fault statistics. A forfeited Match counts as a Match win and loss for Match
differential, but unplayed Rounds are never synthesized for Round differential.
The Tie-break Key uses a separate domain label with the versioned seed derivation
primitive and is recorded before qualification begins.

### 19. Team Identity

Each Team has an organizer-assigned canonical Team ID matching
`[a-z0-9][a-z0-9-]{0,62}`. Team IDs are unique within the Tournament and are
used for scheduling, seed derivation, record identity, and Tie-break Keys.

Each Team also has a human-facing display name for standings and presentation.
The display name may contain ordinary spacing and punctuation but cannot replace
the Team ID in deterministic identifiers. Neither Team ID nor display name can
change after the Tournament begins.

### 20. Canonical Roster

The organizer configures each Team's Team ID and display name and selects its
accepted Bot Artifact. The submission and build pipeline produces a Bot Artifact
Manifest containing:

- `artifact_digest`: SHA-256 identity of the immutable executable bundle,
  including the Team strategy and organizer-owned wrapper.
- `language_id`: stable identifier for the supported language.
- `wrapper_version`: exact organizer-owned wrapper version.
- `runtime_digest`: exact immutable runtime or container image.
- `entrypoint`: validated argument array used to launch the Bot Artifact, never
  an arbitrary shell command string.

The Tournament Runner validates the selected artifact and snapshots the Team ID,
display name, and manifest fields into its canonical roster. Builder-owned fields
are read-only to Teams and organizers.

Mutable artifact locations, contact information, and submission timestamps are
operational metadata and are not part of the canonical roster. The local MVP may
use a separate adapter from artifact identity to a local command without making
that command canonical.

### 21. Competition Records and Operational Telemetry

Canonical Competition Records contain competitive facts in deterministic form:

- Tournament configuration, seed, derivation version, roster, and schedule.
- Fixture, Series, Match, Team, artifact, seed, and Bot Position identities.
- Moves, completed Round outcomes, normalized faults, forfeits, and Series
  outcomes.
- Administrative decision codes, standings, playoff bracket, and Tournament
  Champion.

Under a fixed record schema and canonical serialization, the same competitive
facts produce byte-identical Competition Records. Re-execution validates Bot
Artifact determinism but never replaces committed records.

Operational Telemetry contains execution observations that may legitimately
vary:

- Wall-clock timestamps, response durations, and resource measurements.
- Host, container, process, and Match Attempt details.
- Captured stderr, raw error messages, and organizer diagnostics.

Competition Records and Operational Telemetry share canonical Tournament and
Match identifiers but are stored separately. A timing-limit violation is a
canonical normalized fault; the measured duration and diagnostic details remain
Operational Telemetry. Failed Match Attempts caused by Infrastructure Failures
also remain Operational Telemetry.

### 22. Live Scoreboard Projection

The Tournament Runner atomically writes a versioned `scoreboard.json` Scoreboard
Projection. The scoreboard is a read-only presentation consumer and never
calculates scores, standings, tie-breaks, advancement, or the Tournament
Champion.

The Scoreboard Projection contains:

- Tournament status and current phase.
- Team IDs and display names.
- Qualifying standings and every visible tie-break field.
- Scheduled, active, and completed Fixtures.
- Current Series scores and Match summaries.
- Protocol forfeits and Administrative Series Wins.
- The playoff bracket and Tournament Champion.

The Tournament Runner updates the projection after schedule creation, Match
start and completion, Series completion, administrative rulings, and phase
transitions.

The projection excludes launch commands, artifact locations, stderr, resource
diagnostics, and Security Violation evidence.

### 23. Tournament Recovery and State Snapshots

Tournament creation seals an immutable, checksummed Tournament Manifest
containing the configuration, seed, canonical roster, schedule, and schema and
derivation versions. Resume accepts the Tournament directory rather than a new
set of configuration inputs and uses an exclusive run lock.

Competition Records are written atomically with canonical sequence numbers and
content hashes. A valid terminal Competition Record is the commit boundary for
a Match:

- If the terminal record exists, the Match is complete and is never rerun.
- If no valid terminal record exists, the interrupted Match Attempt is an
  Infrastructure Failure and the Match restarts from Turn 0 with identical
  inputs, counting against its retry budget.

A Tournament State Snapshot is an optional derived cache of state through a
specific Competition Record sequence. It is never a source of competitive truth
and contains no resumable bot process state. A missing or corrupt snapshot is
rebuilt by folding the Tournament Manifest and immutable Competition Records.
The first implementation may omit snapshots entirely and rebuild state on every
resume until measured performance justifies them.

Resume verifies the Manifest, Competition Record sequence and hashes, and Bot
Artifact digests before continuing the first unresolved Match. Corrupt canonical
records pause the Tournament for restoration; they are never replaced by
re-executing completed Matches. The Scoreboard Projection is always rebuildable
from recovered Tournament state.

### 24. Operator Controls

After Tournament creation, an operator may:

- Start the Tournament.
- Request a pause at the next Match boundary.
- Resume a paused Tournament.
- Abort the Tournament without declaring a Tournament Champion.
- Confirm or reject a suspected Security Violation.
- Resume the same Match after infrastructure repair.
- Restore a corrupt Competition Record from a hash-verified backup.
- Execute the next Match under operator control.

Every administrative ruling records the organizer identity, a reason code, and
an optional note. An operator cannot change the Tournament Seed, roster, Bot
Artifacts, schedule, resource limits, scoring rules, or playoff seeding; edit or
delete Competition Records; award arbitrary competitive results; rerun a
committed Match; or manually select and reorder Fixtures.

### 25. Step and Continuous Modes

In Step Mode, `Play Next Match` is available only while the Tournament is paused
at a Match boundary. It executes exactly the scheduler's next unresolved
canonical Match; the operator cannot select Teams or a Fixture.

Infrastructure retries for that canonical Match occur within the same step. Once
a terminal Match record is committed and the Tournament State Snapshot and
Scoreboard Projection are updated, the Tournament pauses again. If that Match
decides its Series, the scheduler skips the unnecessary third Match normally.

Step Mode permits only one active Match. Continuous Mode advances the canonical
schedule automatically and may use configured parallel execution. Operators may
switch modes only at Match boundaries, and switching modes does not alter the
schedule or competitive results.

### 26. Supported Roster Size

A Tournament begins with at least four and at most thirty-two accepted Teams.
Four is the minimum required for the standard Playoff Phase.

At the maximum roster size, qualification contains 496 Fixtures. Including the
three playoff Fixtures, best-of-three Series require at most 1,497 Matches and
449,100 scheduled Rounds.

### 27. Non-Binding Capacity Objectives

On an event host that passes the published preflight benchmark, the engineering
objective is for a maximum-size Tournament with conforming Bot Artifacts and no
Infrastructure Failures to complete within twenty minutes in Continuous Mode.
The Step Mode objective is for one conforming Match to commit and update the
Scoreboard Projection within three seconds.

These are planning, benchmark, and regression-detection objectives only.
Exceeding them never stops or pauses a Tournament, changes a competitive result,
or creates a fault. Only published per-bot protocol and resource limits are
mechanically enforced. Capacity objectives may change with reference hardware
without changing Tournament schema or rules.

### 28. Reduced Playoffs After Disqualification

Before Bracket Lock, the Playoff Phase adapts to the number of eligible
Competitor Teams after Challenger Teams and disqualified Teams are excluded:

- Four or more eligible Teams use the standard four-Team bracket.
- Three eligible Teams give seed 1 a bye to the final while seeds 2 and 3 play a
  semifinal Series.
- Two eligible Teams play the final Series directly.
- One eligible Team becomes Tournament Champion without a playoff Fixture.
- No eligible Teams cause the Tournament to abort without a Tournament Champion.

## Design Status

All Tournament-level questions identified during design have been resolved.
