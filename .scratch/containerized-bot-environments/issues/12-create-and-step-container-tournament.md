# Create and step a container-native Tournament

Status: resolved

Blocked by: 11

## What to build

Use the general JSON plan to create a sealed Tournament whose Bot Artifact and
execution identities name exactly what the container executor will run. Advance
one scheduler-selected Match through the public Tournament command and publish
the normal Competition Record, Operational Telemetry, and Scoreboard Projection.

This is a clean first-use manifest transition. Compatibility with unused
pre-container Tournament artifacts is not required, but all accepted Tournament
rules and deterministic inputs must remain intact.

## Acceptance criteria

- [x] Tournament creation validates the complete plan, artifact-store index, selected images, target platform, validation results, catalog, profile, resources, roster, and existing Tournament invariants before sealing.
- [x] Every roster entry seals the exact image, runtime, source, language, wrapper, recipe, entrypoint, catalog, suite, platform, profile, and final-validation identities required by the PRD.
- [x] Wrong-platform, unvalidated, missing, corrupt, stale-profile, stale-catalog, mutable-tag-only, or digest-mismatched artifacts prevent creation.
- [x] Profile values and global resources may be selected before creation, require matching artifact validation, and become immutable after sealing.
- [x] The general public Tournament command can create a four-through-thirty-two-Team Tournament without relying on the bundled demo roster.
- [x] Advancing one Match launches one fresh container per Bot Position through the same executor and Match Runner used by the single-Match command.
- [x] The completed Match produces the existing normalized competitive record, separate Operational Telemetry, and rebuilt Scoreboard Projection without Docker details entering canonical state.
- [x] Direct host-process execution cannot create or advance an official container-profile Tournament.
- [x] Existing scheduling, seeds, Series scoring, standings, retry policy, and Competition Record authority remain unchanged.

## Answer

Added the public `rps-tournament plan` workflow. It validates the complete draft
plan against the frozen catalog, selected execution profile and resources,
organizer-final validation reports, integrity-checked durable artifact store,
and exact ARM64 images before sealing a general four-through-thirty-two-Team
Tournament Manifest. Every canonical Bot Artifact identity required for replay
is retained, while mutable cache references remain operational only.

The command creates or reopens the Tournament and advances exactly one
scheduler-selected Match through `ContainerMatchExecutor` and the existing Match
Runner. Competition Records, Operational Telemetry, and the Scoreboard
Projection continue through their established authorities. Official container
Tournaments reject host executors at creation, open, and advance boundaries.
