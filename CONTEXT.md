# RPS Tournament

This context describes a programming competition in which Teams enter autonomous
Bot Artifacts that play Rock–Paper–Scissors.

## Language

**Tournament**:
The complete competition for one accepted roster, comprising qualification and
playoffs and, unless no eligible Team remains, one Tournament Champion.
_Avoid_: Event, competition run

**Qualifying Phase**:
The complete round-robin phase in which every accepted Team competes against
every other accepted Team to determine playoff seeding.
_Avoid_: Regular season, preliminaries, qualifiers

**Playoff Phase**:
The single-elimination phase seeded from qualifying standings. It normally uses
four Teams but adapts when disqualifications leave fewer eligible Teams.
_Avoid_: Finals, knockout stage, bracket phase

**Tournament Champion**:
The playoff-eligible Competitor Team declared the winner of the Playoff Phase,
including a sole eligible Competitor Team or a finalist advanced by
Disqualification.
_Avoid_: Qualifying winner, standings leader

**Team**:
The competitive identity that owns one Tournament entry and appears in
qualifying standings. Its immutable Team Role determines whether it may enter
the Playoff Phase and become Tournament Champion.
_Avoid_: Bot, participant, player, entrant

**Team Role**:
The immutable `competitor` or `challenger` classification assigned before the
Tournament is sealed. A missing role in a legacy Tournament means `competitor`.
_Avoid_: Eligibility status, Disqualification status

**Competitor Team**:
A Team that competes throughout qualification and is eligible for playoff
selection unless disqualified.
_Avoid_: Participant Team, regular Team

**Challenger Team**:
An organizer-selected Team that competes and is scored normally throughout the
Qualifying Phase but is never eligible for the Playoff Phase or Tournament
Champion.
_Avoid_: Benchmark bot, exhibition Bot Artifact, disqualified Team

**Bot Artifact**:
The immutable executable entry submitted by a Team for one Tournament. Its exact
identity is retained in Tournament records for reproducibility.
_Avoid_: Bot, submission, source code, team

**Turn**:
One numbered protocol request and response attempt within a Match. A Turn can
end in a protocol fault before producing a Round.
_Avoid_: Round, play

**Round**:
Two valid moves made during a Turn and their resulting Rock–Paper–Scissors
outcome.
_Avoid_: Turn, game

**Match**:
One independently executed and scored head-to-head contest between two Bot
Artifacts, using fresh processes and a fixed number of scheduled Turns.
_Avoid_: Fixture, Series, game, playoff set

**Fixture**:
A scheduled contest between two Teams within a Tournament phase. It contains
one Match unless its rules require a Series.
_Avoid_: Match, pairing, game

**Series**:
A Fixture resolved across multiple Matches.
_Avoid_: Match, playoff set

**Series Point**:
The unit used to resolve a Series: one for a Match win and one-half for a Match
draw. Series Points do not contribute directly to qualifying standings.
_Avoid_: Standing Point, Match Point, Tournament Point

**Standing Point**:
The unit used to rank Teams after qualification: three for a Series win, one for
a Series draw, and none for a Series loss.
_Avoid_: Series Point, Match Point, Tournament Point

**Double Forfeit**:
The Match outcome when both Bot Artifacts fault during the same Turn. Neither
Team wins the Match or receives Series Points.
_Avoid_: Draw, tied Match, double fault

**Security Violation**:
Confirmed prohibited behavior by a Bot Artifact that attempts to access or
interfere with systems outside its permitted Match environment.
_Avoid_: Protocol fault, infrastructure failure, suspicious behavior

**Disqualification**:
The removal of a Team from the entire Tournament after a confirmed Security
Violation.
_Avoid_: Match forfeit, Series loss, withdrawal

**Administrative Series Win**:
A Series win assigned by Tournament rules rather than Match play. It affects
standings or playoff advancement without creating Match or Round statistics.
_Avoid_: Forfeit win, walkover, synthetic Match

**Bracket Lock**:
The start of the first playoff Match, after which no Team can enter the Playoff
Phase from qualification and the bracket is not reseeded.
_Avoid_: Roster lock, playoff start, bracket freeze

**Infrastructure Failure**:
A failed Match Attempt caused by Tournament infrastructure rather than either
Bot Artifact. It has no competitive outcome.
_Avoid_: Protocol fault, Security Violation, Match forfeit

**Match Attempt**:
One execution attempt of a canonical Match. Infrastructure Failures can cause
multiple Match Attempts without creating additional competitive Matches.
_Avoid_: Match, retry Match, replay

**Tie-break Key**:
A deterministic per-Team value derived before qualification and used only when
all competitive qualifying tie-breakers remain equal.
_Avoid_: Team ID order, random draw, playoff seed

**Team ID**:
The immutable organizer-assigned slug that identifies one Team within a
Tournament and participates in deterministic derivations.
_Avoid_: Display name, roster position, Bot Artifact ID

**Team Display Name**:
The human-facing Team label shown in standings and presentation.
_Avoid_: Team ID, Bot name

**Bot Artifact Manifest**:
The immutable builder-produced description of a Bot Artifact's identity,
language, organizer-owned wrapper, runtime, and launch contract.
_Avoid_: Tournament roster, submission form, organizer configuration

**Language Environment**:
A versioned, organizer-owned adapter package in the Language Environment Catalog
that defines the Team Source schema, wrapper, Seed Adapter, pinned runtimes,
networkless build recipe, readiness contract, entrypoint, and conformance
fixtures for one supported language.
_Avoid_: Team Template, participant repository, runtime image

**Team Template**:
A participant-facing starter project, maintained outside this repository, that
adapts one Language Environment for Team coding and claims compatibility with
one exact Catalog Release.
_Avoid_: Language Environment, catalog fixture, official wrapper

**Team Source**:
The participant-authored strategy files and approved resources presented at the
Runner's validated local source-directory boundary under one Language
Environment's Team Source schema.
_Avoid_: Team Template, Bot Artifact, organizer wrapper, source repository

**Template Release**:
An immutable publication of a Team Template that records its own identity and
an exact Catalog Release compatibility claim.
_Avoid_: Catalog Release, mutable branch, latest template

**Catalog Release**:
An immutable publication of the Runner-owned Language Environment Catalog and
its assets, identified by an exact Runner commit, package version, catalog path
and content identity, and offline bundle identity.
_Avoid_: Team Template release, catalog branch, latest catalog

**Advisory Validation**:
A compatibility check performed before organizer acceptance, such as Team-local
or CI validation, that provides feedback but cannot authorize a Bot Artifact for
a Tournament.
_Avoid_: Final Validation, official certification, roster acceptance

**Final Validation**:
The organizer-controlled, authoritative validation of selected Team Source
against the exact Catalog Release and official target platform; only its result
can authorize the resulting Bot Artifact for a Tournament roster.
_Avoid_: Advisory Validation, CI check, Team-built image

**Competition Record**:
The canonical deterministic account of Tournament configuration, competitive
activity, rulings, standings, and outcome.
_Avoid_: Operational Telemetry, log, report

**Operational Telemetry**:
Non-competitive execution observations retained for diagnosis and operations
that may differ when the same Tournament is reproduced.
_Avoid_: Competition Record, replay, standings

**Scoreboard Projection**:
The read-only current Tournament view used for live presentation. It reports
runner-owned results and standings without calculating them.
_Avoid_: Competition Record, source of truth, scoreboard database

**Tournament Manifest**:
The sealed immutable record of the inputs and versions that define one
Tournament before competitive execution begins.
_Avoid_: Bot Artifact Manifest, Tournament State Snapshot, configuration file

**Tournament State Snapshot**:
A rebuildable cache of Tournament state derived through a specific Competition
Record sequence.
_Avoid_: Checkpoint, Competition Record, process snapshot

**Step Mode**:
The operator-controlled execution mode in which one scheduler-selected canonical
Match completes per action before the Tournament pauses again.
_Avoid_: Manual scheduling, single-step Turn, debug mode

**Continuous Mode**:
The execution mode in which the Tournament advances its canonical schedule
without requiring an operator action for each Match.
_Avoid_: Automatic scheduling, parallel mode, batch mode

**Bot Position**:
The internal `a` or `b` execution role assigned to a Bot Artifact for one Match.
It has no competitive meaning and is not exposed to the Bot Artifact.
_Avoid_: Side, home, away, seed

**Fixture Batch**:
An ordered group of qualifying Fixtures in which each Team appears at most once.
Fixture Batches define canonical schedule order, not execution concurrency.
_Avoid_: Round, Matchday, execution batch

**Seed Adapter**:
The versioned part of an organizer-owned language wrapper that deterministically
maps a bot-visible 64-bit seed into that language's random-number generator.
_Avoid_: Seed derivation, system randomness

**Tournament Seed**:
The organizer-supplied root value from which all deterministic Tournament
ordering and child seeds are derived.
_Avoid_: Random seed, root RNG state

**Fixture Seed**:
The deterministic child of the Tournament Seed associated with one Fixture.
_Avoid_: Tournament Seed, Match Seed

**Match Seed**:
The deterministic child of a Fixture Seed associated with one Match.
_Avoid_: Fixture Seed, bot-visible seed

**Bot-visible Seed**:
The deterministic per-Team child of a Match Seed supplied to a Bot Artifact's
Seed Adapter.
_Avoid_: Match Seed, shared seed
