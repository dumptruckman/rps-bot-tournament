# Create and step a container-native Tournament

Status: ready-for-agent

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

- [ ] Tournament creation validates the complete plan, artifact-store index, selected images, target platform, validation results, catalog, profile, resources, roster, and existing Tournament invariants before sealing.
- [ ] Every roster entry seals the exact image, runtime, source, language, wrapper, recipe, entrypoint, catalog, suite, platform, profile, and final-validation identities required by the PRD.
- [ ] Wrong-platform, unvalidated, missing, corrupt, stale-profile, stale-catalog, mutable-tag-only, or digest-mismatched artifacts prevent creation.
- [ ] Profile values and global resources may be selected before creation, require matching artifact validation, and become immutable after sealing.
- [ ] The general public Tournament command can create a four-through-thirty-two-Team Tournament without relying on the bundled demo roster.
- [ ] Advancing one Match launches one fresh container per Bot Position through the same executor and Match Runner used by the single-Match command.
- [ ] The completed Match produces the existing normalized competitive record, separate Operational Telemetry, and rebuilt Scoreboard Projection without Docker details entering canonical state.
- [ ] Direct host-process execution cannot create or advance an official container-profile Tournament.
- [ ] Existing scheduling, seeds, Series scoring, standings, retry policy, and Competition Record authority remain unchanged.

