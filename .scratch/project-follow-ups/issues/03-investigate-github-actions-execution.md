# Investigate Tournament execution through GitHub Actions

Status: ready-for-agent

Priority: 3

Blocked by: None

## What to build

Produce a decision-ready design for optionally executing an already-built
Tournament through GitHub Actions after the proven local workflow, without
weakening Bot Artifact identity, container isolation, Competition Record
authority, deterministic recovery, or the Scoreboard Projection boundary.

Local execution remains the primary supported operation. This issue investigates
a migration path and does not authorize implementation of remote Tournament
execution.

## Acceptance criteria

- [ ] Compare hosted and self-hosted runner architecture, native container
  capability, capacity, duration, cost, persistence, and untrusted-code risks.
- [ ] Define how platform-specific Bot Artifacts, the Tournament Manifest,
  Competition Records, Operational Telemetry, the Scoreboard Projection, and
  verified restoration inputs enter and leave an ephemeral runner.
- [ ] Preserve the existing container execution profile, Match-execution
  boundary, canonical scheduling, commit ordering, pause conditions, and
  Infrastructure Failure policy.
- [ ] Explain whether the canonical ARM64 workflow can run natively, requires a
  self-hosted runner, or should remain local while a distinct platform-specific
  workflow is considered.
- [ ] Identify required implementation changes, security controls, unresolved
  risks, operational failure modes, and a staged migration or rejection path.
- [ ] Record an explicit recommendation while keeping GitHub Actions Tournament
  execution optional.
