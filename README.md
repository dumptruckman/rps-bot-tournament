# Rock–Paper–Scissors Bot Tournament
*A language-agnostic programming competition for internal engineering teams*

This repository is the organizer-owned Tournament Runner and the sole authority
for the Language Environment Catalog. It does not contain a participant-facing
Team Template. Teams begin authoring Team Source from the
[RPS Bot Templates repository](https://github.com/dumptruckman/rps-bot-templates),
the only documented source for Team starter material and Team guidance.

A Template Release may claim compatibility with one exact Runner Catalog
Release. The Runner never fetches, imports, or tests the companion repository.
See [Catalog compatibility](docs/CATALOG_COMPATIBILITY.md) and
[ADR 0005](docs/adr/0005-runner-owns-language-environment-catalog.md).

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
├── scoreboard/
│
└── tests/
```

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
The runner supports Python 3.9 or newer and has no third-party runtime
dependencies:

```text
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Verify that the installed package contains its complete offline presentation:

```text
rps-tournament verify-presentation-assets
```

Then run a match:

```text
rps-run \
  --bot-a "path/to/explicit-command-a" \
  --bot-b "path/to/explicit-command-b" \
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

The first invocation seals a new Tournament from packaged, organizer-owned
certification fixtures and commits one real 300-Turn Match. These fixtures are
internal Runner assets, not Team Source or Team Templates. The command does not
read strategy files from the source checkout or the companion repository. Run
the same command again to verify and resume the sealed Tournament, skip
committed Matches, and execute the next unresolved canonical Match.

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

The release gate is the separate real-path `rps-rehearse` command. It builds and
authoritatively validates sixteen local ARM64 Bot Artifacts, proves their shared
archive restore, executes the 369-Match worst-case Tournament with four
concurrent Matches, and verifies reconstructed state and the Scoreboard
Projection. See [docs/REHEARSAL.md](docs/REHEARSAL.md).

### Validate and freeze Team source

Use the frozen Language Environment catalog to validate an already-present Team
source directory before any container build receives it:

```text
rps-validate-source \
  --catalog language_environments/catalog-v1/catalog.json \
  --environment python \
  --source path/to/team-source \
  --bundle path/to/new-frozen-bundle
```

Python source must provide `strategy.py` with the `choose_move` contract. It may
include accessory Python modules and `.csv`, `.json`, or `.txt` resources under
`resources/`. The command rejects infrastructure files, symlinks, special files,
unsupported paths, and descriptor size/count breaches. It never replaces an
existing bundle. On success it prints the deterministic source digest and writes
the same identity record to `source-bundle.json`; copied source is read-only.
The versioned Python source schema requires one unconditional, undecorated
module-level `choose_move` definition whose signature accepts the wrapper's four
positional arguments; source validation never executes Team code.
Catalog loading also verifies the content digest of every organizer-owned asset,
including the wrapper, build recipe, entrypoint, runtime/platform definition,
readiness contract, workflow, dependency policy, and conformance definition.

### Build a Bot Artifact candidate

After organizer preparation has placed the pinned platform runtime in the active
Docker-compatible engine, build exactly one platform-specific candidate from the
frozen bundle:

```text
rps-build-artifact \
  --catalog language_environments/catalog-v1/catalog.json \
  --bundle path/to/new-frozen-bundle \
  --platform linux/arm64 \
  --candidate path/to/new-artifact-candidate
```

The builder honors the active Docker context, verifies the selected build
toolchain and execution runtime by their platform-specific digests, and builds
without networking. Team source and the
organizer-owned recipe and wrapper enter Docker through separate contexts. The
new candidate directory retains read-only source, bounded build diagnostics, and
`artifact-candidate.json`. That record identifies the exact produced image and
all frozen build inputs. It is a suite candidate, not an official Bot Artifact,
until conformance certification succeeds.

### Certify a Bot Artifact

All validation authorities invoke the same versioned command with explicit mode,
platform, and execution-profile inputs:

```text
rps-certify-artifact \
  --catalog language_environments/catalog-v1/catalog.json \
  --candidate path/to/new-artifact-candidate \
  --mode participant-local \
  --platform linux/amd64 \
  --profile docker-execution-v1 \
  --output path/to/new-certified-artifact
```

The other modes are `github-advisory` (Linux/AMD64 only) and
`organizer-final` (Linux/ARM64 only). Participant-local and GitHub results are
explicitly advisory; they can never stand in for the canonical organizer-final
ARM64 Bot Artifact.

Certification verifies the frozen catalog and source/build record, exact local
image identity, entrypoint, readiness, lifecycle, protocol transcripts,
same-seed behavior, timing and stream limits, the isolation/resource profile,
and complete 300-Turn container Matches. Fixed-move, random, copycat, and
protocol-test practice Bot Artifacts are built through the same selected Language
Environment and container path. Their protocol conformance can fail the suite,
but their score and winner never do. Successful output contains immutable
`bot-artifact-manifest.json` and `validation-report.json` files with every
source, image, runtime, wrapper, recipe, entrypoint, catalog, suite, platform,
profile, and core-tool identity. A host-process development check is useful but
is always reported as insufficient evidence for official validation.

These catalog-owned practice artifacts are organizer certification fixtures.
They are not starter strategies, Team Source examples, or Team Templates.

### Batch official sources into a Tournament plan

Create an explicit local JSON mapping for four through thirty-two Teams. Each
entry has the following shape; source acquisition and cutoff selection happen
before this command:

```json
{
  "team_id": "red-rockets",
  "display_name": "Red Rockets",
  "role": "competitor",
  "source_directory": "/local/selected/red-rockets"
}
```

`role` may be `competitor` or `challenger` and defaults to `competitor` when
omitted. Challenger Teams play and score normally throughout the complete
qualifying round robin and appear in standings, but the Runner excludes them
when selecting and seeding the playoff field.

Then build, organizer-final validate, and preserve the selected ARM64 Bot
Artifacts with an explicit operational concurrency limit:

```text
rps-batch-plan \
  --teams path/to/team-sources.json \
  --catalog language_environments/catalog-v1/catalog.json \
  --environment python \
  --output path/to/new-batch-output \
  --tournament-seed 8675309 \
  --execution-mode continuous \
  --jobs 4
```

The new output contains immutable per-Team frozen inputs, one shared
`artifact-store`, an independent `batch-report.json`, and—only when every Team
succeeds—a draft `tournament-plan.json`. Team processing runs concurrently up
to `--jobs`, while reports and the plan remain ordered by Team ID. Continuous
Mode defaults to four-Match planned parallelism; `--parallelism` changes that
editable pre-sealing value.

For a supervised compatibility-only repair, add a `repair` object containing a
replacement `source_directory` and organizer `explanation`. The output retains
the original frozen source, replacement source, complete deterministic diff,
both source digests, explanation, and successful final validation identity.
Remote fetching, GitHub authentication, branches, cutoff enforcement, and
mutable Docker references are deliberately outside this command and the
canonical plan.

Review the draft, set its execution mode and global resource values, and then
seal and advance one scheduler-selected Match through the container executor:

```text
rps-tournament plan \
  --plan path/to/new-batch-output/tournament-plan.json \
  --catalog language_environments/catalog-v1/catalog.json \
  --directory results/summer-cup-2026 \
  --tournament-id summer-cup-2026
```

The adjacent `artifact-store` is used by default; pass `--artifact-store` when
it is retained elsewhere. Before sealing, the command verifies the complete
plan, catalog, profile/resources, validation identities, retained bytes, image
digests, and native ARM64 platform. It loads missing selected images only from
the verified archive. `--create-only` seals without stepping.

After creation, the sealed Tournament Manifest replaces the draft plan as the
authority. Repeating the command may omit `--plan` when `--artifact-store` is
explicit. Opening verifies the sealed catalog, profile, platform, validation,
and artifact-store identities, restores missing images only from the verified
archive, and advances the next canonical Match. Container and artifact-loading
diagnostics remain Operational Telemetry and never enter Competition Records or
the Scoreboard Projection.

For a plan whose sealed execution mode is `continuous`, run every remaining
canonical Match through Tournament Champion declaration (or the canonical
no-champion outcome) with the sealed worker limit:

```text
rps-tournament plan \
  --plan path/to/new-batch-output/tournament-plan.json \
  --catalog language_environments/catalog-v1/catalog.json \
  --directory results/summer-cup-2026 \
  --tournament-id summer-cup-2026 \
  --continuous
```

Use `--start` for an explicit initial start, `--request-pause` from another
process to pause after the active canonical prefix, and `--resume` after a pause
or operator intervention. `--switch-mode step|continuous` is accepted only at
a verified Match boundary. Reopening may omit `--plan` when `--artifact-store`
names the retained store explicitly.

To run every remaining qualifying Match and then pause after publishing the
unlocked playoff bracket, use `--all-qualification`. No playoff Match starts
until a later operator command advances or resumes the Tournament.

### Ratify a native platform and the execution profile

Run the complete build, certification, and measured Python profile probe on a
native organizer host:

```text
scripts/ratify-native-platform.sh linux/arm64 path/to/evidence
```

The command refuses a Docker server whose native architecture does not match the
requested platform; emulation is not accepted. GitHub runs the same lane as
`github-advisory` on native Linux/AMD64, while the organizer runs
`organizer-final` on native Linux/ARM64. See
[`docs/EXECUTION_PROFILE.md`](docs/EXECUTION_PROFILE.md) for the published
ceilings, evidence, platform-specific runtime identities, and four-Match initial
parallelism.

### Diagnose container-host readiness

Use `rps-doctor` to inspect the active Docker-compatible context, native
platform, engine controls, frozen catalog, prepared images, durable Bot Artifact
store, disk, CPU capacity, execution profile, and optional rehearsal evidence.
The command is read-only and accepts OrbStack without requiring Docker Desktop.
See [`docs/HOST_READINESS.md`](docs/HOST_READINESS.md) for its immutable-image
inputs, stable JSON report, and complete Docker command allowlist.

### Prepare an organizer machine for offline operation

Run the explicit fast preparation workflow before the Tournament, while registry
access is still available if a pinned runtime is not already cached:

```text
rps-prepare \
  --catalog language_environments/catalog-v1/catalog.json \
  --environment python \
  --platform linux/arm64 \
  --profile docker-execution-v1 \
  --artifact-store path/to/prepared-artifact-store \
  --report path/to/preparation-report.json \
  --parallelism 4 \
  --expected-context orbstack \
  --allow-pull
```

Preparation performs a networkless representative rebuild, retains practice
Bot Artifacts, exercises readiness and the published isolation profile, creates
and restores a verified local archive, and runs doctor against those exact
inputs. It does not install Docker, change engine settings, prune caches, or
replace either output. Omit `--allow-pull` to require every pinned runtime to be
present already. See [`docs/OFFLINE_PREPARATION.md`](docs/OFFLINE_PREPARATION.md)
for report fields, failure dispositions, and the separate full rehearsal.

For the audience display, start a separate read-only process with
`rps-tournament present --directory TOURNAMENT_DIRECTORY`. The Tournament Runner
and presentation can be stopped and restarted independently. See
[`docs/PRESENTATION.md`](docs/PRESENTATION.md) for supported browsers, launch and
recovery instructions, and the release smoke-check matrix.

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

- identical API
- deterministic RNG
- local runner
- unit tests

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
