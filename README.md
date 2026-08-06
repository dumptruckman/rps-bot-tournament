# Rock–Paper–Scissors Bot Tournament
*A language-agnostic programming competition for internal engineering teams*

---

# Project Purpose

This project provides the infrastructure for a two-hour internal engineering event in which teams compete by writing autonomous Rock–Paper–Scissors bots.

Participants should spend their time designing strategies—not learning tournament infrastructure or Docker.

The platform should feel similar to programming competitions such as Advent of Code, Google Code Jam, or Battlecode, where competitors implement a well-defined interface and the organizers provide everything else.

---

# Primary Goals

## For Participants

Participants should be able to:

- Pick one of several supported programming languages.
- Implement a single strategy function.
- Test locally against practice bots.
- Submit source code.
- Receive immediate validation feedback.
- Compete in a deterministic tournament.

They should **not** need to:

- Write Dockerfiles.
- Understand tournament scheduling.
- Manage stdin/stdout directly.
- Install complicated tooling.
- Configure networking.
- Build containers.

---

## For Organizers

The system should:

- Build submissions reproducibly.
- Execute untrusted code safely.
- Produce deterministic tournaments.
- Generate replays.
- Display live standings.
- Be simple to operate during an event.

---

# High-Level Architecture

```
              Team Source
                   │
                   ▼
         Submission Validator
                   │
                   ▼
       Language-specific Builder
                   │
                   ▼
          Immutable Bot Artifact
                   │
                   ▼
             Tournament Runner
                   │
         ┌─────────┴─────────┐
         ▼                   ▼
    Match Results       Replay Files
         │                   │
         └─────────┬─────────┘
                   ▼
             Live Scoreboard
```

The architecture intentionally separates:

- submission
- compilation
- execution
- scoring
- presentation

Each stage should be independently testable.

---

# Design Principles

## Simplicity

Everything visible to participants should be extremely simple.

The participant experience should feel like:

> "Implement one function."

Everything else is organizer-owned.

---

## Language Neutrality

Every supported language should expose the exact same API.

No language should have an inherent advantage because of infrastructure.

---

## Determinism

Running a tournament from the same immutable inputs with conforming Bot
Artifacts should produce identical competitive results.

This requires:

- deterministic RNG
- fixed seeds
- identical Docker images
- immutable artifacts
- reproducible scheduling

---

## Fairness

Every participant should run under identical limits.

No custom containers.

No network.

No hidden configuration.

No privileged execution.

---

## Security

Treat every submission as potentially malicious.

Never trust:

- filenames
- stdout
- source code
- build scripts
- archive contents

Containers exist because participants are executing arbitrary code.

---

# Repository Structure

A proposed repository layout:

```
/
├── docs/
│   ├── PROTOCOL.md
│   ├── TOURNAMENT.md
│   ├── SECURITY.md
│   ├── SUBMISSION.md
│   └── ARCHITECTURE.md
│
├── runner/
│   ├── match_engine/
│   ├── scheduler/
│   ├── scoring/
│   ├── replay/
│   └── docker/
│
├── validator/
│
├── builders/
│   ├── python/
│   ├── go/
│   ├── java/
│   ├── typescript/
│   ├── csharp/
│   └── rust/
│
├── templates/
│
├── practice_bots/
│
├── hidden_bots/
│
├── scoreboard/
│
└── tests/
```

---

# Participant API

Participants should implement exactly one strategy.

Conceptually:

```text
chooseMove(
    turn,
    myHistory,
    opponentHistory,
    rng
)
```

Returns:

```
R
```

or

```
P
```

or

```
S
```

The language wrapper is organizer-owned.

Participants should never need to parse stdin.

---

# Match Protocol

The runner communicates using a language-neutral stdin/stdout protocol.

Input:

```
turn_number
my_history
opponent_history
```

Output:

```
R
```

Histories contain only completed rounds.

No future information is exposed.

---

# Tournament Format

Current preferred format:

1. Round robin among all human teams.
2. Every team also plays hidden benchmark bots.
3. League standings determine the top four.
4. Semifinals.
5. Championship.

Suggested match length:

- 300 rounds

Playoffs:

- best of multiple seeded matches

---

# Local Match Engine

Create an isolated virtual environment and install the local command into it.
The project has no third-party runtime dependencies:

```text
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Then run a match:

```text
rps-run \
  --bot-a "python bots/random_bot.py" \
  --bot-b "python bots/copycat_bot.py" \
  --rounds 300 \
  --seed 12345 \
  --output results/demo.json
```

The result file contains the match status, winner, score, move histories,
round-by-round replay data with monotonic response timings, bot faults, and
bounded stderr captured from each bot. A normal win, loss, draw, or protocol
forfeit exits successfully.
Infrastructure failures, such as a bot command that cannot be started or a
result file that cannot be written, return a nonzero exit code.

The timing defaults follow the protocol draft: 250 ms for the first move,
50 ms for later moves, and a total response budget of 2 seconds per bot.
They can be changed locally with `--first-move-timeout-ms`,
`--move-timeout-ms`, and `--total-timeout-ms`.

## Tournament Runner demo

Run one scheduler-selected canonical Match in a deterministic four-Team demo
Tournament:

```text
rps-tournament demo --directory results/demo-tournament --seed 12345
```

The first invocation seals a new Tournament from the bundled `random_bot.py` and
`copycat_bot.py` Bot Artifacts and commits one real 300-Turn Match. Run the same
command again to verify and resume the sealed Tournament, skip committed Matches,
and execute the next unresolved canonical Match.

To advance through the Playoff Phase and Tournament Champion declaration, run:

```text
rps-tournament demo \
  --directory results/demo-tournament \
  --seed 12345 \
  --all
```

Continuous Mode can execute independent Matches concurrently while retaining
canonical Competition Record order. The worker limit is sealed at creation and
defaults to one:

```text
rps-tournament demo \
  --directory results/continuous-demo \
  --seed 12345 \
  --continuous \
  --parallelism 2
```

The command prints the current mode, sealed Continuous Mode parallelism,
standings, bracket, Tournament Champion, and these inspectable artifacts:

- Sealed Tournament Manifest: `<directory>/manifest.json`
- Competition Records and their index: `<directory>/records/` and
  `<directory>/records.index.json`
- Operational Telemetry: `<directory>/telemetry/`
- Scoreboard Projection: `<directory>/scoreboard.json`

## Capacity preflight

The opt-in capacity suite runs without live Bot Artifact processes and reports
the non-binding Continuous and Step Mode objectives. See
[docs/CAPACITY_BENCHMARKS.md](docs/CAPACITY_BENCHMARKS.md) for prerequisites,
exact commands, workloads, preserved artifacts, and result interpretation.

## Python starter bot

The starter bot keeps participant code focused on one strategy function:

```python
def choose_move(turn, my_history, opponent_history, rng):
    return rng.choice(("R", "P", "S"))
```

The organizer-owned Python wrapper supplies a deterministic `rng`, translates
the stdin/stdout protocol, and flushes each response. The complete runnable
example is in `bots/random_bot.py`.

---

# Submission Format

Participants submit source code only.

No Dockerfiles.

No build scripts.

No external dependencies.

A submission contains:

```
bot.yaml
src/
ABOUT.md
```

The organizer controls:

- compiler
- wrapper
- build process
- runtime

---

# Docker Philosophy

Participants never interact with Docker directly.

The platform owns:

- base images
- compilation
- runtime
- limits
- networking
- filesystem

Containers exist only to safely execute untrusted code.

---

# Runtime Restrictions

Every bot executes with strict limits.

Current targets:

- no network
- read-only filesystem
- non-root user
- CPU limit
- memory limit
- PID limit
- output limit
- timeout
- deterministic environment variables

Bots should never be able to communicate with one another or the host.

---

# Supported Languages

Initially:

- Python
- Go
- Java
- TypeScript
- C#
- Rust (optional)

Every language receives:

- starter project
- identical API
- deterministic RNG
- local runner
- unit tests

---

# Practice Bots

Visible practice bots should teach participants how strategies work.

Examples:

- Always Rock
- Cycle
- Random
- Mirror
- Frequency Counter

Practice bots should intentionally differ from tournament bots.

---

# Hidden Tournament Bots

Hidden bots exist to encourage robust strategies.

Possible ideas:

- Markov predictor
- Transition predictor
- Pattern matcher
- Ensemble
- Adaptive strategy

Hidden bots should be frozen before the event.

Their implementations are revealed after judging.

---

# Scoring

Preferred scoring:

Each round:

- Win = +1
- Draw = 0
- Loss = -1

Each match:

- 3 league points for match win
- 1 point for draw

Tie breakers:

1. Head-to-head
2. Round differential (capped)
3. Performance vs hidden bots
4. Replay match

---

# Replay System

Every match should produce a replay artifact containing:

- participants
- seed
- move history
- timings
- winner
- metadata

A replay should be sufficient to completely reconstruct the match.

---

# Live Scoreboard

The scoreboard should display:

- standings
- current matches
- playoff bracket
- match history
- round differential
- hidden bot performance (after reveal)

Nice-to-have:

- live replay
- move timeline
- statistics
- win rates

---

# Validation Pipeline

Every submission passes through:

1. Archive validation
2. Manifest validation
3. Build
4. Protocol validation
5. Practice matches
6. Determinism check
7. Resource limit tests

Only successful builds become tournament artifacts.

---

# Non-Goals

This project is **not** intended to support:

- distributed tournaments
- persistent bot state between opponents
- arbitrary Dockerfiles
- internet access
- package managers
- plugins
- arbitrary languages
- real-time networking

Keeping the platform simple is more important than supporting every possible feature.

---

# Event Timeline

Suggested schedule:

- 8 min introduction
- 45 min coding
- 7 min submission freeze
- 15 min league
- 10 min strategy presentations
- 15 min playoffs
- 15 min replay discussion
- awards

---

# Awards

Champion

Best Strategy

Most Original Bot

Simplest Effective Bot

Best Explanation

Hidden Bot Slayer

---

# Development Priorities

## Phase 1 (MVP)

- Protocol specification
- Match engine
- Docker runner
- Python template
- Validation
- Round robin tournament

Goal:

A complete tournament can run locally from the command line.

---

## Phase 2

- Multiple languages
- Replay generation
- Better diagnostics
- Hidden bots
- Deterministic seeds
- Artifact storage

Goal:

Ready for internal testing.

---

## Phase 3

- Live scoreboard
- Bracket UI
- Statistics
- Awards support
- Replay viewer
- Event polish

Goal:

Production-ready event.

---

# Guiding Principle

Whenever making implementation decisions, optimize for the participant experience.

Participants should feel like they are solving an interesting AI/programming problem—not wrestling with infrastructure.

If a feature increases organizer complexity but makes the participant experience significantly simpler, prefer the simpler participant experience.
