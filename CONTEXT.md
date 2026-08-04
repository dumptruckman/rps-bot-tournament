# RPS Tournament

This context describes a programming competition in which accepted autonomous
bots play Rock–Paper–Scissors to determine a champion.

## Language

**Tournament**:
The complete competition for one accepted roster, comprising qualification and
playoffs and ending with one champion.
_Avoid_: Event, competition run

**Qualifying Phase**:
The complete round-robin phase in which every accepted bot competes against
every other accepted bot to determine playoff seeding.
_Avoid_: Regular season, preliminaries, qualifiers

**Playoff Phase**:
The four-bot single-elimination phase seeded from qualifying standings. Seed 1
plays seed 4, and seed 2 plays seed 3.
_Avoid_: Finals, knockout stage, bracket phase

**Tournament Champion**:
The Team whose Bot Artifact wins the playoff final.
_Avoid_: Qualifying winner, standings leader

**Team**:
The competitive identity that owns one Tournament entry, appears in standings,
and may become Tournament Champion.
_Avoid_: Bot, participant, player, entrant

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
