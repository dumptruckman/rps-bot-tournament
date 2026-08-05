# Tournament Runner

Status: ready-for-agent

Implementation status: in progress

## Implementation Progress

Last updated: 2026-08-05

The implemented foundation is covered by 141 passing tests under the repository's
Python 3.9 virtual environment. Earlier work is recorded in commits `2703c20`,
`7f1a17a`, `4e1b307`, and `876071f`; the current frontier adds the sealed rules
contract, authoritative state fold, and transition from the Qualifying Phase to
the Playoff Phase.

### Complete

- [x] Validate the supported roster, Team identity, immutable Bot Artifact
  identity, Tournament Seed, and configurable execution limits before creation.
- [x] Seal and verify a deeply immutable, checksummed Tournament Manifest.
- [x] Derive versioned Fixture, Match, bot-visible, schedule, Bot Position, and
  Tie-break values with HMAC-SHA-256 and independent golden vectors.
- [x] Generate deterministic even- and odd-roster round-robin Fixture Batches,
  stable Fixture identities, byes, and canonical ordering for four through
  thirty-two Teams.
- [x] Implement best-of-three Series scoring, qualifying standings and all seven
  tie-breakers, reduced playoff brackets, and Disqualification advancement rules
  as pure domain behavior.
- [x] Give each Bot Artifact its own position-independent bot-visible seed while
  preserving the existing single-Match CLI contract.
- [x] Carry the complete sealed resource and security-limit contract to the Match
  execution boundary and enforce configurable response-output limits locally.
- [x] Normalize Match results by Team identity and separate competitive facts
  from Operational Telemetry.
- [x] Store canonical Competition Records with deterministic serialization,
  sequence numbers, hashes, atomic writes, and deeply immutable loaded values.
- [x] Treat a terminal Competition Record as the Match commit boundary and retain
  completed moves, Rounds, normalized faults, Double Forfeit facts, seeds, Bot
  Positions, and Bot Artifact identities.
- [x] Run one scheduler-selected qualifying Match per Step Mode action, including
  Series early completion and Scoreboard Projection updates.
- [x] Persist Match Attempt starts, retry Infrastructure Failures through the
  automatic three-attempt allowance, preserve absolute attempt ordinals across
  interruption, and pause for operator intervention.
- [x] Resume under an exclusive run lock, verify compatibility and Bot Artifact
  digests, skip committed Matches, and rebuild a missing or corrupt Scoreboard
  Projection.
- [x] Expose an installable four-Team demo CLI that derives real bundled Bot
  Artifact identities, creates or resumes a durable Tournament, advances one
  Match or all qualification, and reports inspectable artifacts without implying
  playoff or Tournament Champion completion.
- [x] Seal every scoring, tie-break, Disqualification, and playoff rule explicitly
  in the Tournament Manifest and reject a validly resealed incompatible ruleset.
- [x] Reconstruct qualifying Series, standings, and the next canonical Match
  through one authoritative state fold that rejects semantically impossible
  Competition Record histories, including contradictory outcomes, play facts,
  faults, seeds, Bot Positions, and Bot Artifact identities.
- [x] Commit and project the deterministic seeded playoff bracket when the
  Qualifying Phase completes, including idempotent recovery when the final
  qualifying Match commits before the phase-transition record.

### Partially complete

- [ ] Execute the Playoff Phase. Series, bracket, reduced-playoff, advancement,
  and Disqualification rules exist as tested domain behavior, and the Tournament
  Runner now commits the standard seeded bracket transition; canonical Bracket
  Lock, playoff Match execution, advancement, final, and champion remain.
- [ ] Apply qualification and playoff Disqualifications through the Tournament
  Runner. Standing and bracket transformations exist, but administrative ruling
  records and scheduler integration do not.
- [ ] Complete the Scoreboard Projection. Qualifying scheduling, Match progress,
  standings, retries, and recovery are projected; playoff, Administrative Series
  Win, Security Violation, and Tournament Champion views remain.
- [ ] Complete operator execution controls. Step Mode and infrastructure pause
  behavior exist; explicit start, requested pause, resume-after-ruling, abort,
  mode switching, and record-restoration commands remain.
- [ ] Verify maximum capacity end to end. Schedule generation covers the
  thirty-two-Team roster, but the full 1,497-Match/449,100-Round Tournament and
  its non-binding performance objectives have not been benchmarked.

### Remaining

- [ ] Implement Continuous Mode, configured parallel Match execution, canonical
  commit ordering under concurrency, and boundary-only mode switching.
- [ ] Implement suspected Security Violation capture, organizer confirmation or
  rejection, evidence linkage, and the resulting Tournament-level pause or
  Disqualification workflow.
- [ ] Implement administrative ruling records with organizer identity, closed
  reason codes, and optional notes.
- [ ] Implement Tournament abort and Tournament Champion declaration through the
  Tournament Runner.
- [ ] Implement hash-verified Competition Record restoration from backup.
- [ ] Add the published capacity/preflight benchmark suite.

### Acceptance criteria status

| Status | Acceptance criteria | Notes |
| --- | --- | --- |
| Complete | 1–16, 23–28 | Implemented and covered at the creation, domain, Match, storage, Step Mode, and recovery seams. |
| Partial | 17–18, 21–22, 29–30, 34 | Core rules or one execution mode exist; runner integration, projection coverage, or capacity verification remains. |
| Not started | 19–20, 31–33, 35 | Security workflow, Continuous Mode controls, administrative controls/abort, and capacity benchmarks remain. |

## Problem Statement

Organizers can currently execute and inspect one local Match, but they cannot run
the complete Tournament defined by an accepted roster and configuration. The
repository has no Tournament-level scheduler, Series scoring, qualifying
standings, Playoff Phase, deterministic seed hierarchy, immutable Competition
Records, recovery workflow, operator controls, or Scoreboard Projection.

Without that layer, organizers would have to arrange Fixtures, calculate results,
apply Disqualifications, and recover interrupted execution manually. Those manual
steps could change competitive outcomes, make a Tournament irreproducible, or
turn Operational Telemetry into an accidental source of truth.

The implementation must turn the settled Tournament and protocol designs into a
single deterministic Tournament Runner. It must preserve the Team as the
competitive identity, the Bot Artifact as the immutable executable identity, and
Competition Records as the authoritative account of what occurred.

## Solution

Provide a Tournament Runner that creates a sealed Tournament from an accepted
canonical roster and immutable configuration, generates the complete canonical
qualifying schedule, derives all deterministic ordering and seeds, executes each
Fixture as a best-of-three Series through the Match Runner, derives standings and
the adaptive playoff bracket, and declares at most one Tournament Champion.

The runner will commit competitive facts as ordered, hashed, immutable
Competition Records; retain variable execution observations separately as
Operational Telemetry; and atomically publish a read-only Scoreboard Projection.
It will expose bounded operator controls for starting, pausing, resuming,
aborting, stepping, handling suspected Security Violations, and recovering from
Infrastructure Failures without permitting competitive inputs or completed
outcomes to be edited.

The same sealed Tournament Manifest and valid Competition Record sequence must
always reconstruct the same Tournament state. Re-execution may verify a Bot
Artifact, but it must never replace a committed Match.

## User Stories

1. As an organizer, I want to create a Tournament from one accepted roster and
   configuration, so that all competitive inputs are fixed before execution.
2. As an organizer, I want the roster limited to four through thirty-two Teams,
   so that the Tournament uses the supported format and capacity envelope.
3. As an organizer, I want each Team identified by an immutable canonical Team
   ID and Team Display Name, so that deterministic identities and presentation
   labels remain distinct.
4. As an organizer, I want each Team associated with exactly one immutable Bot
   Artifact, so that a Team cannot change its executable during the Tournament.
5. As an auditor, I want every canonical roster entry to retain the Bot Artifact
   digest, language, wrapper version, runtime digest, and validated entrypoint,
   so that each execution can be reproduced and attributed.
6. As an organizer, I want mutable artifact locations and contact metadata kept
   outside the canonical roster, so that operational changes do not alter the
   Tournament identity.
7. As an auditor, I want Tournament creation to seal a checksummed Tournament
   Manifest, so that later input mutation is detectable.
8. As an organizer, I want the Tournament Manifest to record schema, protocol,
   seed-derivation, configuration, roster, and schedule versions, so that replay
   compatibility is explicit.
9. As a Team, I want every accepted Team to meet every other accepted Team once
   in the Qualifying Phase, so that qualification is a complete round robin.
10. As an organizer, I want Team IDs canonically ordered and deterministically
    shuffled from the Tournament Seed before scheduling, so that schedule
    generation is fair and reproducible.
11. As an operator, I want qualifying Fixtures grouped into ordered Fixture
    Batches with at most one appearance per Team per batch, so that the canonical
    schedule supports safe sequential or parallel execution.
12. As a Team on an odd-sized roster, I want the circle-method schedule to assign
    byes without omitting any pairing, so that qualification remains complete.
13. As an auditor, I want all qualifying Fixture IDs and canonical result order
    fixed before execution, so that runtime completion order cannot affect the
    record order or standings.
14. As a Team, I want every qualifying and playoff Fixture to use a best-of-three
    Series, so that strategies are exercised across fresh processes and seeds.
15. As a Team, I want each Match scheduled for 300 Turns and started with fresh
    bot processes, so that state never carries between Matches.
16. As an operator, I want a Series to stop after two Match wins and otherwise
    play its third Match, so that no unnecessary Match is executed.
17. As a Team, I want a Match win to award one Series Point and a drawn Match to
    award one-half Series Point to each Team, so that Series outcomes follow the
    accepted scoring rules.
18. As a Team, I want a tied qualifying Series recorded as a draw, so that both
    Teams receive the accepted qualifying result.
19. As a playoff Team, I want a tied playoff Series awarded to its higher seed,
    so that every playoff Fixture has a bounded deterministic outcome.
20. As a Team, I want Bot Positions to be internal execution roles without
    competitive meaning or bot-visible disclosure, so that they cannot influence
    strategy or presentation.
21. As a Team, I want Match 2 positions to swap Match 1 positions and Match 3
    positions to be derived independently, so that position rotation is
    deterministic defense in depth.
22. As a Team, I want Match timing and resources equivalent for both Bot
    Positions, so that internal process labels do not create a competitive
    advantage.
23. As a Team, I want my own bot-visible seed for every Match, derived from the
    Match Seed and my canonical Team ID rather than Bot Position, so that my
    random stream is reproducible and position-independent.
24. As an organizer, I want the Tournament Seed, Fixture Seeds, Match Seeds,
    bot-visible seeds, schedule ordering values, position values, and Tie-break
    Keys derived through versioned domain-separated HMAC-SHA-256, so that no
    runtime-specific hash or PRNG affects competitive behavior.
25. As an auditor, I want every derived seed stored as an unsigned decimal
    64-bit value in its corresponding deterministic record, so that derivations
    can be independently verified.
26. As a Team using an official language wrapper, I want the wrapper's versioned
    Seed Adapter to map the full 64-bit bot-visible seed deterministically, so
    that replay remains stable within my language and runtime.
27. As a Team, I want different official languages permitted to produce
    different deterministic random streams, so that wrappers can use appropriate
    language-native or organizer-supplied generators.
28. As a Bot Artifact, I want each Turn request and response to follow protocol
    version 1 exactly, so that the Tournament Runner remains compatible with the
    existing Match Runner and official wrappers.
29. As a Bot Artifact, I want only the protocol version, scheduled Turns, and my
    bot-visible seed exposed through documented environment variables, so that
    opponent identity, seed, ranking, and language remain hidden.
30. As a Team, I want a single-bot protocol fault to forfeit only the current
    Match, so that the next Match in the Series starts normally with fresh
    processes.
31. As a Team that did not fault, I want a protocol-fault forfeit to award me the
    Match win and one Series Point without synthetic Rounds, so that competitive
    statistics reflect only play that occurred.
32. As an organizer, I want two faults during the same Turn recorded as a Double
    Forfeit with no winner or Series Points, so that neither Team is rewarded.
33. As an organizer, I want a Double Forfeit to consume its Match ordinal and
    allow the Series to continue when another Match remains, so that the bounded
    Series rules are preserved.
34. As an operator, I want suspected prohibited host, network, container, or
    cross-Match interference to stop the process and pause the Tournament, so
    that evidence can be reviewed before a competitive ruling.
35. As an organizer, I want confirmed prohibited behavior recorded as a Security
    Violation and the Team disqualified from the entire Tournament, so that the
    ruling is applied consistently.
36. As an organizer, I want unconfirmed behavior not attributable to the Bot
    Artifact handled as an Infrastructure Failure, so that a Team is not
    penalized for Tournament infrastructure.
37. As an eligible Team during qualification, I want an Administrative Series
    Win and three Standing Points for my Fixture against a disqualified Team, so
    that all eligible Teams are treated consistently.
38. As an auditor, I want played Match records involving a later-disqualified
    Team preserved as historical evidence but excluded from qualifying Match,
    Round, timing, and fault tie-break statistics, so that Disqualification does
    not rewrite history or distort rankings.
39. As an operator, I want future Fixtures involving a Team disqualified during
    qualification skipped, so that its Bot Artifact is not executed again.
40. As an eligible Team, I want the playoff field recalculated from the highest
    ranked eligible Teams until Bracket Lock, so that pre-playoff
    Disqualifications do not leave an avoidable empty position.
41. As a playoff Team, I want Bracket Lock to occur when the first playoff Match
    starts, so that no later Team enters and the bracket is not reseeded.
42. As a playoff opponent of a disqualified Team, I want an Administrative
    Series Win and advancement, so that no synthetic Match is required.
43. As a Team most recently eliminated by a later-disqualified playoff Team, I
    want reinstatement when that Team's next Series has not begun, so that the
    locked bracket position is filled under the accepted rule.
44. As a remaining finalist, I want to become Tournament Champion if my opponent
    is disqualified after the final begins, so that the Tournament can conclude
    without replay or reseeding.
45. As a Team, I want qualifying standings to award three Standing Points for a
    Series win, one for a Series draw, and zero for a loss, so that every Fixture
    has equal qualifying weight.
46. As a Team, I want standings ordered by Standing Points, Series wins,
    applicable two-Team head-to-head result, Match differential, Round
    differential, protocol-fault forfeits, and Tie-break Key in that order, so
    that every seed is deterministic.
47. As an auditor, I want an Administrative Series Win excluded from Match,
    Round, and fault statistics, so that only its Standing Points affect
    standings.
48. As an auditor, I want a forfeited Match counted as a Match win and loss for
    Match differential without synthetic Rounds, so that tie-break fields follow
    the accepted definitions.
49. As a qualifying Team, I want head-to-head used only when exactly two Teams
    remain tied at that criterion, so that multi-Team ties are not resolved by an
    inapplicable comparison.
50. As an organizer, I want the standard playoff to seed 1 versus 4 and seed 2
    versus 3, with winners meeting in the final, so that the accepted bracket is
    used.
51. As an eligible Team, I want reduced playoffs to handle three, two, one, or no
    eligible Teams according to the accepted rules, so that Disqualification
    never requires an improvised bracket.
52. As an organizer, I want a sole eligible Team declared Tournament Champion
    and no eligible Teams to abort without a champion, so that every eligibility
    state has a defined result.
53. As an operator, I want an Infrastructure Failure to create no competitive
    outcome and automatically retry the same canonical Match at most twice, so
    that transient runner failures do not penalize a Team.
54. As an auditor, I want every Match Attempt for a canonical Match to use the
    same Bot Artifacts, seeds, Bot Positions, limits, and configuration, so that
    retries cannot change the contest.
55. As an operator, I want the Tournament to pause after three failed Match
    Attempts and resume the same Match after repair, so that infrastructure
    failure cannot be converted into an arbitrary competitive result.
56. As an auditor, I want canonical competitive facts separated from timings,
    stderr, host details, resource measurements, raw errors, and failed Match
    Attempts, so that Competition Records remain byte-identical when competitive
    facts are identical.
57. As an organizer, I want normalized timing-limit faults in Competition
    Records while measured durations remain Operational Telemetry, so that
    competitive rulings and diagnostics are both retained in the correct place.
58. As an auditor, I want Competition Records canonically serialized, sequenced,
    hashed, and atomically written, so that corruption, reordering, and partial
    writes are detectable.
59. As an operator, I want a terminal Competition Record to be the sole commit
    boundary for a Match, so that completed Matches are never rerun.
60. As an operator, I want an interrupted uncommitted Match Attempt restarted
    from Turn 0 with identical inputs and counted against its retry budget, so
    that process state is never resumed ambiguously.
61. As an operator, I want resume to verify the Tournament Manifest, Competition
    Record sequence and hashes, and Bot Artifact digests under an exclusive run
    lock, so that execution cannot continue from corrupt or mutated state.
62. As an operator, I want corrupt canonical records to pause for restoration
    from a hash-verified backup rather than trigger re-execution, so that the
    authoritative record is preserved.
63. As an operator, I want Tournament state rebuilt by folding the sealed
    Tournament Manifest and ordered Competition Records, so that mutable process
    snapshots never become a second source of truth.
64. As an operator, I want any Tournament State Snapshot treated as an optional,
    rebuildable cache tied to a record sequence, so that deleting or corrupting
    it cannot change competitive state.
65. As a scoreboard consumer, I want one versioned Scoreboard Projection updated
    atomically from runner-owned state, so that presentation never observes a
    partial update or calculates competitive facts itself.
66. As a spectator, I want the projection to show status, phase, Teams,
    qualifying standings and visible tie-breaks, Fixtures, Series scores, Match
    summaries, forfeits, Administrative Series Wins, bracket, and champion, so
    that the complete current Tournament is visible.
67. As a Team, I want launch commands, artifact locations, stderr, resource
    diagnostics, and Security Violation evidence excluded from the Scoreboard
    Projection, so that sensitive operational details are not published.
68. As an operator, I want the Scoreboard Projection refreshed after schedule
    creation, Match start and completion, Series completion, administrative
    rulings, and phase transitions, so that it tracks committed runner state.
69. As an operator, I want to start, pause at the next Match boundary, resume,
    abort without a champion, rule on suspected Security Violations, resume
    after infrastructure repair, restore verified records, and play the next
    Match, so that live operation is controlled without changing competition
    rules.
70. As an auditor, I want every administrative ruling to record organizer
    identity, a reason code, and an optional note, so that manual actions are
    attributable and reviewable.
71. As a Team, I want operators unable to change the seed, roster, Bot Artifacts,
    schedule, limits, scoring, playoff seeding, or committed records after
    creation, so that operator controls cannot alter the competition.
72. As an operator using Step Mode, I want each action to run exactly the
    scheduler-selected next canonical Match, including its infrastructure
    retries, and then pause after state and projection updates, so that I can
    advance safely without manual Match selection.
73. As an operator using Continuous Mode, I want the canonical schedule to
    advance automatically with optional configured parallelism, so that the
    Tournament can meet its event-time objective without changing result order.
74. As an operator, I want mode changes allowed only at Match boundaries, so that
    switching execution style cannot interrupt or alter a Match.
75. As an organizer, I want the maximum-size conforming Tournament benchmarked
    against a twenty-minute Continuous Mode objective and a three-second Step
    Mode Match objective, so that regressions are visible without changing any
    competitive result or fault rule.

## Implementation Decisions

### Authority and boundaries

- The accepted Tournament design, protocol version 1 contract, domain glossary,
  and four accepted ADRs are normative. The implementation must not substitute
  older format or scoring descriptions from general project documentation.
- The Tournament Runner owns Tournament creation, deterministic derivation,
  canonical scheduling, Series and standing calculations, playoff advancement,
  Competition Records, recovery, operator state, and the Scoreboard Projection.
- The existing Match Runner remains the execution authority for one Match and
  protocol version 1. The Tournament Runner invokes it through a Match-execution
  boundary; Tournament logic does not duplicate Turn parsing, timing, process
  lifecycle, move validation, Round scoring, or protocol-fault detection.
- Submission intake, source validation, language builds, immutable runtime
  construction, container hardening, and scoreboard presentation remain outside
  the Tournament Runner. Their immutable inputs and read-only outputs cross the
  explicit contracts described below.
- The Team is the competitive identity. Bot Position is only an execution role,
  and the Bot Artifact is the immutable executable associated with one Team.

### Tournament creation and immutable inputs

- Tournament creation accepts one unsigned 64-bit Tournament Seed, a roster of
  four through thirty-two Teams, the published Match timing and resource limits,
  execution-mode configuration, and version identifiers required for replay.
- A Team ID must be unique within the Tournament and match
  `[a-z0-9][a-z0-9-]{0,62}`. Team IDs and Team Display Names become immutable at
  creation.
- Every Team references exactly one Bot Artifact Manifest. Required immutable
  fields are the SHA-256 artifact digest, stable language identifier, exact
  organizer-owned wrapper version, immutable runtime digest, and a validated
  argument-array entrypoint. An arbitrary shell command string is not canonical.
- A local artifact resolver may translate the immutable Bot Artifact identity
  to a local launch mechanism. That resolver and mutable location are operational
  concerns and must not enter canonical records.
- Creation validates all inputs, computes the complete qualifying schedule and
  all pre-qualification Tie-break Keys, then seals one immutable checksummed
  Tournament Manifest. Execution cannot begin until the seal is durable.
- The Manifest includes the complete canonical roster and schedule, published
  limits and scoring configuration, protocol version, record schema version,
  seed-derivation version, and any compatibility versions needed to reproduce
  deterministic behavior.

### Deterministic seed and ordering contract

- Seed derivation version 1 uses HMAC-SHA-256. The unsigned 64-bit parent seed is
  encoded as eight big-endian bytes and used as the HMAC key. The message uses
  the canonical length-prefixed UTF-8 encoding for the fixed domain
  `rps-tournament/seed/v1`, the child-seed type, and its canonical identifier.
  The first eight digest bytes, interpreted as an unsigned big-endian integer,
  are the child seed.
- Fixture Seeds derive from the Tournament Seed and canonical Fixture ID; Match
  Seeds derive from the Fixture Seed and one-based Match ordinal; bot-visible
  seeds derive from the Match Seed and canonical Team ID.
- Schedule shuffle values, Bot Position assignments, and Tie-break Keys use
  separate domain labels through the same versioned primitive. No language
  runtime hash, default PRNG, process state, wall clock, completion order, or Bot
  Position may influence a seed or canonical order.
- Every derived 64-bit value is represented canonically as an unsigned decimal
  value in the deterministic record associated with it.
- Version 1 must have published golden derivation vectors covering boundary seed
  values, non-ASCII-safe UTF-8 framing, every derivation level, schedule labels,
  position labels, and Tie-break Keys. Changing the derivation or framing is a
  versioned compatibility break.
- The Match-execution request carries the Match Seed for identity and separate
  bot-visible seeds for the two Teams. The adapter supplies each process its own
  bot-visible seed as `RPS_SEED`; it never exposes the opponent's seed or Team
  identity.

### Canonical schedule and scheduler

- Schedule generation first sorts by canonical Team ID, applies the deterministic
  Tournament-seeded shuffle, and then uses the circle method to produce the
  complete round robin.
- The resulting schedule is partitioned into ordered Fixture Batches. Each Team
  appears at most once in a batch, and an odd roster produces exactly one bye in
  each applicable batch.
- Canonical Fixture identity and result order are fixed in the sealed Manifest.
  Sequential or parallel execution may change wall-clock start and completion
  order only; canonical commit and projection ordering remain schedule-driven.
- The scheduler exposes only the next unresolved canonical Match or the set of
  currently runnable canonical Matches allowed by Continuous Mode parallelism.
  Operator input cannot choose, reorder, or synthesize a Match.
- Both qualifying and playoff Fixtures are best-of-three Series. Each Match has
  300 scheduled Turns and a fresh pair of bot processes. A third Match is omitted
  once one Team has won the first two Matches.
- Match 1 Bot Positions derive deterministically from the Fixture Seed. Match 2
  swaps those positions. Match 3 derives positions independently from the
  Fixture Seed. Team-relative results are normalized before Series scoring.

### Match execution and outcome normalization

- The Match-execution boundary accepts canonical Tournament, Fixture, Series,
  Match, Team, Bot Artifact, seed, position, protocol, limit, and retry context.
  It returns a normalized competitive outcome separately from Operational
  Telemetry.
- Protocol version 1 remains line-based and UTF-8. Each zero-based Turn sends the
  turn number, own completed move history, and opponent completed move history;
  an empty history is `-`. A valid response is exactly one newline-terminated,
  flushed `R`, `P`, or `S`.
- Processes receive only `RPS_PROTOCOL_VERSION=1`, `RPS_ROUNDS=300`, their own
  unsigned decimal `RPS_SEED`, and non-contractual infrastructure environment
  that Bot Artifacts are forbidden to depend on.
- Requests are sent to both processes before waiting for either response.
  Configured first-move, later-move, total response-time, stderr, stdout, CPU,
  memory, process, filesystem, and security limits apply equivalently to both Bot
  Positions.
- One protocol fault ends the Match and awards the opponent a Match win and one
  Series Point. Only completed Rounds are retained. Both faults attributed to the
  same Turn create a Double Forfeit with no Match winner or Series Points.
- A suspected Security Violation is not normalized as an ordinary protocol
  forfeit. It stops the implicated process, captures available evidence in
  Operational Telemetry, and returns control to the paused Tournament for an
  organizer ruling.
- A failure not attributable to either Bot Artifact is an Infrastructure
  Failure. It produces no terminal competitive Match outcome and consumes a
  Match Attempt, not a Match ordinal.

### Series, standings, and playoffs

- A Match win is one Series Point; a drawn Match is one-half per Team; a Double
  Forfeit is zero per Team. A Series ends after two Matches when one Team has two
  wins, or after its third Match otherwise.
- More Series Points wins the Series. Equal Series Points produce a qualifying
  Series draw; in playoffs, the higher qualifying seed advances.
- Qualifying Series outcomes award three Standing Points for a win, one for a
  draw, and zero for a loss. Match and Series Points do not directly enter
  standings.
- Standings compare, in order: Standing Points; qualifying Series wins;
  head-to-head Series result only when exactly two Teams remain tied; qualifying
  Match wins minus Match losses; completed qualifying Round wins minus Round
  losses; fewest protocol-fault Match forfeits; and lowest pre-derived Tie-break
  Key.
- Protocol-forfeited Matches count as a Match win and loss for Match differential
  but add no unplayed Rounds. Administrative Series Wins add three Standing
  Points and a Series win but add no Match, Round, timing, or fault statistics.
- With four or more eligible Teams, the four highest-ranked eligible Teams enter
  playoffs and seeds 1/4 and 2/3 meet in semifinals. With three eligible Teams,
  seed 1 advances to the final and seeds 2/3 play a semifinal. With two, the
  final is played directly. One eligible Team is champion; none aborts without a
  champion.
- Bracket Lock is the start of the first playoff Match. Before it, eligibility
  changes recompute the playoff field and bracket. After it, no Team enters from
  qualification and the bracket is never reseeded.

### Disqualification and administrative rulings

- A suspected Security Violation pauses execution until an organizer confirms or
  rejects attribution. Confirmation disqualifies the Team from the entire
  Tournament; rejection converts the incident to an Infrastructure Failure.
- During qualification, every eligible opponent receives an Administrative
  Series Win and three Standing Points for its Fixture against the disqualified
  Team. Future Fixtures are skipped. Existing Match records stay immutable but
  their Match, Round, timing, and fault data are excluded from qualifying
  tie-break aggregates.
- Before Bracket Lock, a disqualified Team is removed before selecting and
  seeding the eligible playoff field. After Bracket Lock, its current Series
  opponent receives an Administrative Series Win; if it had advanced and its next
  Series has not begun, the Team it most recently eliminated is reinstated into
  that bracket position; after the final starts, the remaining finalist becomes
  Tournament Champion.
- Administrative actions use closed reason codes and record the organizer
  identity plus an optional note. They may apply only the outcomes enumerated by
  the accepted rules.

### Competition Records and Operational Telemetry

- Competition Records are the sole authoritative, deterministic account of
  Tournament configuration, schedule, competitive activity, rulings, standings,
  bracket, and champion. Re-execution is verification and cannot replace them.
- The canonical record schema covers Tournament, Fixture, Series, Match, Team,
  Bot Artifact, seed, Bot Position, completed move and Round outcome, normalized
  fault, forfeit, Administrative Series Win, eligibility, standings, bracket,
  phase, and Tournament Champion facts.
- Records use a versioned canonical serialization that produces byte-identical
  bytes for identical competitive facts. Each is assigned a canonical sequence
  number and content hash and is committed atomically.
- A terminal Match record is the commit boundary. Its presence means the Match
  is complete and cannot be rerun. Absence means an interrupted Match Attempt is
  an Infrastructure Failure and restarts at Turn 0 with identical inputs.
- Operational Telemetry is linked by canonical Tournament, Fixture, Match, and
  Match Attempt identifiers but stored separately. It owns timestamps, measured
  durations, stderr, resource use, host/container/process details, raw errors,
  Security Violation evidence, and failed Match Attempts.
- A timing-limit violation is a normalized canonical fault. The measurement and
  diagnostic evidence that support it remain Operational Telemetry.

### Recovery and state reconstruction

- Resume accepts an existing Tournament store, not a replacement configuration,
  and acquires an exclusive run lock before verification or execution.
- Resume verifies the Manifest checksum, schema and compatibility versions,
  ordered record sequence and hashes, and all Bot Artifact digests. Corrupt or
  missing canonical data pauses execution for restoration; it is never repaired
  by rerunning a committed Match.
- Tournament state is a deterministic fold of the sealed Manifest and valid
  ordered Competition Records. The first implementation may rebuild on every
  resume.
- A Tournament State Snapshot is optional. If implemented, it identifies the
  exact Competition Record sequence it covers, contains no bot process state,
  and is discarded and rebuilt when missing, corrupt, or inconsistent.
- An interrupted Match Attempt counts toward the same canonical Match's
  three-attempt automatic retry allowance. After three failed attempts the
  Tournament pauses; operator resumption retries that same Match with unchanged
  inputs and cannot substitute an outcome.

### Scoreboard Projection and operator surface

- The Scoreboard Projection is a versioned, atomically replaced, read-only view
  derived by the Tournament Runner. It does not calculate standings, tie-breaks,
  advancement, or champion.
- It includes Tournament status and phase; Team IDs and display names; standings
  with every visible tie-break field; scheduled, active, and completed Fixtures;
  current Series scores and Match summaries; protocol forfeits;
  Administrative Series Wins; playoff bracket; and Tournament Champion.
- It excludes launch details, mutable artifact locations, stderr, resource
  diagnostics, raw infrastructure errors, and Security Violation evidence.
- Projection refresh points are schedule creation, Match start, terminal Match
  commit, Series completion, administrative ruling, and phase transition. It is
  always rebuildable from recovered Tournament state.
- Operator commands are start, request pause at the next Match boundary, resume,
  abort without champion, confirm or reject a suspected Security Violation,
  resume the same Match after infrastructure repair, restore a hash-verified
  Competition Record backup, and execute the next canonical Match.
- Step Mode runs one scheduler-selected canonical Match per action, including
  automatic infrastructure retries, commits its terminal record, updates derived
  state and projection, then pauses. Only one Match may be active.
- Continuous Mode advances the canonical schedule automatically and may use
  configured parallel execution. Mode changes occur only at Match boundaries and
  never alter canonical ordering or results.
- No operator command may mutate the seed, roster, Bot Artifacts, schedule,
  limits, scoring, seeding, or a committed Competition Record; award an arbitrary
  outcome; rerun a committed Match; or select and reorder Fixtures.

### Capacity contract

- The implementation must safely generate and represent the maximum schedule of
  496 qualifying Fixtures plus three standard playoff Fixtures, at most 1,497
  best-of-three Matches, and 449,100 scheduled Rounds.
- On a host that passes the published preflight benchmark, twenty minutes for a
  maximum-size conforming Continuous Mode Tournament and three seconds for one
  conforming Step Mode Match are non-binding engineering objectives only.
  Exceeding them cannot pause execution, create a fault, or change a record.

## Testing Decisions

- Tests assert externally visible Tournament behavior: sealed inputs, canonical
  schedule and records, Match-execution requests, Scoreboard Projection,
  standings, advancement, recovery, and operator outcomes. They must not assert
  private helper structure or internal call order except where canonical order is
  itself part of the contract.
- The highest primary seam is a complete Tournament Runner operation against a
  temporary Tournament store with a controllable Match-execution adapter. Tests
  provide a roster and deterministic sequence of normalized Match outcomes, then
  inspect the Manifest, Competition Records, reconstructed state, projection,
  requested Matches, and final champion. This one seam covers most scheduling,
  scoring, recovery, and control behavior without spawning hundreds of bot
  processes.
- The Match-execution adapter is contract-tested against the real Match Runner to
  prove that Team-relative seeds and Bot Positions are translated correctly and
  that normal completion, draw, protocol forfeit, Double Forfeit, suspected
  Security Violation, and Infrastructure Failure are normalized without mixing
  telemetry into competitive facts.
- Existing end-to-end CLI tests and adversarial fixture bots are the prior art for
  protocol behavior. Extend that style only where the Tournament-to-Match
  boundary changes the environment contract, especially separate bot-visible
  seeds and canonical-versus-telemetry output.
- Pure deterministic contracts receive golden tests: HMAC derivation vectors,
  canonical shuffle and circle-method schedules for even and odd rosters, Bot
  Position rotation, Tie-break Keys, canonical serialization bytes and hashes,
  and stable reconstruction from the same Manifest and records.
- Schedule tests cover the minimum and maximum rosters, every unordered Team pair
  exactly once, at most one Team appearance per Fixture Batch, correct byes, and
  unchanged canonical ordering under different simulated completion orders.
- Series tests cover two-Match wins, all three-Match paths, Match draws, qualifying
  Series draws, playoff ties advancing the higher seed, single forfeits, Double
  Forfeits, and omission of an unnecessary third Match.
- Standing tests isolate every tie-break criterion and include multi-Team ties,
  the exactly-two-Team head-to-head gate, protocol forfeits without synthetic
  Rounds, Administrative Series Wins without lower-level statistics, and the
  deterministic final Tie-break Key.
- Playoff tests cover standard seeding and all reduced eligible-Team counts,
  including sole champion and no-champion abort. Disqualification tests cover
  qualification, pre-lock reselection, in-Series advancement, reinstatement after
  prior advancement, and disqualification after the final begins.
- Infrastructure tests prove that failed Match Attempts do not consume Match
  ordinals or create competitive outcomes, all three automatic attempts reuse
  identical inputs, the third failure pauses, and later operator resumption still
  addresses the same canonical Match.
- Recovery tests interrupt before and after terminal record commit, corrupt the
  Manifest, record sequence, hash, artifact digest, projection, telemetry, and
  optional snapshot independently, and verify the accepted pause, rebuild, or
  resume behavior. A committed Match must never be requested again.
- Record-separation tests execute competitively identical Matches with different
  timings, stderr, hosts, and failed attempts. Competition Record bytes must be
  identical while Operational Telemetry may differ.
- Operator tests prove pause-boundary behavior, single-Match Step Mode, automatic
  Continuous Mode progress, boundary-only mode switching, exclusive locking,
  audit fields on rulings, and rejection of every forbidden mutation or manual
  scheduling action.
- Projection tests inspect every required visible field and update point, reject
  sensitive operational fields, verify atomic replacement behavior, and confirm
  that deleting the projection followed by recovery regenerates the same view.
- Capacity tests generate the thirty-two-Team schedule and full worst-case Match
  count without requiring live bot execution. Separate benchmark tests measure
  the non-binding Continuous and Step Mode objectives without converting a slow
  benchmark into a Tournament fault.

## Acceptance Criteria

### Tournament creation

1. Creating a Tournament with fewer than four or more than thirty-two Teams,
   duplicate or malformed Team IDs, mutable or incomplete Bot Artifact identity,
   or an out-of-range Tournament Seed fails before a Manifest is sealed.
2. A valid creation seals one checksummed immutable Manifest containing the
   canonical roster, complete qualifying schedule, published limits and rules,
   Tournament Seed, precomputed Tie-break Keys, and all compatibility versions.
3. After sealing, attempts to change the seed, roster, display names, Bot
   Artifacts, schedule, limits, scoring, or versions are rejected.

### Schedule and seeds

4. For every supported roster size, the qualifying schedule contains each
   unordered pair exactly once, contains no self-pairing, and places each Team in
   at most one Fixture per Fixture Batch.
5. Recreating a Tournament from identical inputs produces identical schedule,
   Fixture IDs, derived ordering, seeds, position assignments, Tie-break Keys,
   Manifest bytes, and checksum.
6. Match 2 swaps Match 1 Bot Positions; Match 3 uses its independently derived
   assignment; no bot-visible seed changes when a Team's Bot Position changes.
7. Opposing Teams receive independently derived unsigned 64-bit decimal
   `RPS_SEED` values, and replaying identical Match inputs supplies the same value
   to each Team.
8. Seed-derivation version 1 passes the published golden vectors and rejects any
   silent algorithm or framing change under the same version.

### Match and Series execution

9. Every scheduled Match uses 300 Turns, fresh processes, one Match Seed, two
   Team-specific bot-visible seeds, deterministic Bot Positions, and the sealed
   protocol and resource configuration.
10. A Team winning the first two Matches ends the Series without requesting a
    third Match; all other unresolved Series consume the third Match.
11. Match wins, Match draws, qualifying Series draws, and playoff Series ties
    award the exact accepted Series Points and outcomes.
12. A one-Team protocol fault awards only the current Match and one Series Point
    to the opponent, commits only completed Rounds, and allows a fresh next Match
    when the Series remains unresolved.
13. Faults by both Bot Artifacts during the same Turn produce a Double Forfeit,
    no Series Points, no synthetic Rounds, and consumption of that Match ordinal.

### Standings and playoffs

14. Every qualifying Fixture awards exactly three/zero Standing Points for a
    Series win/loss or one/one for a Series draw, regardless of whether two or
    three Matches were played.
15. Ranking uses all seven accepted criteria in order and uses head-to-head only
    when exactly two Teams remain tied at that step.
16. Forfeited Matches affect Match differential and protocol-fault count but
    never synthesize Round differential; Administrative Series Wins affect
    Standing Points and Series wins only.
17. Four or more eligible Teams produce the 1-versus-4 and 2-versus-3 bracket;
    three produce a seed-1 bye and 2-versus-3 semifinal; two play a final; one is
    champion; none aborts without a champion.
18. A playoff Series always advances one Team, using higher qualifying seed only
    when its Series Points are tied.

### Disqualification and failures

19. A suspected Security Violation stops the implicated process, preserves
    evidence outside Competition Records, and pauses before another canonical
    Match starts.
20. Confirming the violation disqualifies the Team and applies the phase-specific
    accepted rules; rejecting attribution records an Infrastructure Failure and
    retries the same Match under the infrastructure policy.
21. Qualification Disqualification gives every eligible opponent one
    Administrative Series Win, skips future affected Fixtures, preserves played
    records, and excludes all affected lower-level tie-break statistics.
22. Before Bracket Lock, eligibility changes reselect and reseed the playoff
    field; after lock, no qualification Team newly enters and the accepted
    advancement or reinstatement rule applies without reseeding.
23. An Infrastructure Failure creates no competitive Match result and retries
    identical inputs twice; a third failed attempt pauses the Tournament without
    consuming the Match ordinal or substituting an outcome.

### Records, recovery, and projection

24. Competitively identical facts produce byte-identical Competition Records
    despite differences in timestamps, durations, stderr, host details, resource
    measurements, raw errors, or failed Match Attempts.
25. Every Competition Record is canonically ordered, sequenced, content-hashed,
    and atomically committed; a partial, missing, reordered, or corrupt record is
    detected on resume.
26. A valid terminal Match record prevents all future execution of that Match.
    Without one, an interrupted Match Attempt restarts from Turn 0 with identical
    inputs and consumes the correct retry allowance.
27. Resume uses the sealed Tournament store under an exclusive lock, verifies the
    Manifest, records, and artifact digests, and continues at the first unresolved
    canonical Match only.
28. Missing or corrupt derived state, projection, or optional snapshot is rebuilt
    from the Manifest and records; corrupt canonical records pause for verified
    restoration and never trigger re-execution of committed Matches.
29. Every required Scoreboard Projection field is runner-derived and updated at
    all accepted boundaries; no prohibited launch, artifact-location, stderr,
    diagnostic, or Security Violation evidence field is present.

### Operator controls and capacity

30. Pause takes effect at the next Match boundary; Step Mode executes exactly one
    scheduler-selected canonical Match and pauses after durable record and
    projection updates; Continuous Mode advances without manual selection.
31. Mode changes occur only at Match boundaries, and varying execution
    concurrency or completion timing does not change canonical result ordering or
    reconstructed state.
32. Every administrative ruling records organizer identity, a closed reason code,
    and an optional note, and every forbidden mutation or arbitrary-result command
    is rejected.
33. Aborting the Tournament produces no Tournament Champion unless one was
    already validly declared by the completed rules.
34. A thirty-two-Team Tournament generates 496 qualifying Fixtures and, with the
    three standard playoff Fixtures all reaching three Matches, no more than
    1,497 Matches and 449,100 scheduled Rounds.
35. Capacity benchmark overruns are reported operationally only and never create
    a competitive fault, pause, record mutation, or result change.

## Out of Scope

- Submission upload, participant account and contact management, source archive
  validation, strategy-source policy, and submission-time user experience.
- Language-specific build pipelines, creation of immutable runtimes or
  containers, and implementation of every organizer-owned wrapper or Seed
  Adapter. Their immutable manifest and deterministic seed contracts are in
  scope at the Tournament boundary.
- Container isolation and hardening mechanisms, host provisioning, network
  policy implementation, and security forensics tooling. Detection, pause,
  evidence linkage, and organizer rulings are in scope at the Tournament
  boundary.
- The visual scoreboard, replay viewer, bracket user interface, and presentation
  calculations. The runner-owned read-only Scoreboard Projection is in scope.
- Distributed Tournament execution, arbitrary operator-selected Match ordering,
  persistent Bot Artifact state between Matches, participant-provided
  containers, arbitrary languages, package installation, or networked bots.
- Changing protocol version 1, Tournament format, scoring, tie-break order,
  Disqualification rules, retry policy, record authority, or any other accepted
  design decision.
- Treating the non-binding capacity objectives as enforced timeouts or
  competitive rules.
- Tournament State Snapshots in the initial implementation; state reconstruction
  from the Manifest and Competition Records is sufficient until measured
  performance justifies the optional cache.

## Further Notes

- Normative sources are the accepted Tournament design, the protocol version 1
  document as an input to this accepted design, the root domain glossary, and
  ADRs 0001 through 0004.
- General README passages describing hidden benchmark bots, league-point scoring
  per Match, capped Round differential, replay tie-break Matches, or other earlier
  preferred formats are superseded for this work by the accepted Tournament
  design and are not implementation requirements.
- Language-specific random streams are intentionally allowed. Determinism is
  defined for the same Bot Artifact, wrapper version, runtime, bot-visible seed,
  and random API call sequence, not across different languages.
- Competition Records are authoritative replay artifacts. Re-execution can detect
  nondeterminism or validate an artifact but cannot revise recorded competitive
  history.
- This specification synthesizes settled decisions only. It does not authorize
  implementation or reopen the Tournament design.
