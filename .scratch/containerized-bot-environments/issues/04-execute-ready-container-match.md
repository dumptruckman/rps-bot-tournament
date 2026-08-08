# Execute a ready container through the Match boundary

Status: ready-for-agent

Blocked by: 01, 03

## What to build

Run two builder-produced Python Bot Artifact candidates in fresh containers
through the existing Match-execution request and result boundary. Both
organizer-owned wrappers must load Team strategy and signal readiness before the
Match Runner sends Turn 0, keeping container and runtime startup outside all
competitive response budgets.

The slice should prove a complete containerized Match while keeping the existing
Match Runner authoritative and retaining host-process execution as explicit
insecure development behavior.

## Acceptance criteria

- [ ] One fresh container is created for each Bot Position and both containers are created, started, attached, and awaited concurrently.
- [ ] Each wrapper emits the reserved versioned readiness marker only after its Team strategy is loaded and it is ready for Turn 0.
- [ ] The executor handles a readiness marker split across stream chunks and removes control data from Team stderr and its byte allowance.
- [ ] Competitive response timing begins only after both wrappers are ready and the Match Runner sends Turn 0.
- [ ] The container sessions participate in the same protocol, timing, move validation, Round construction, and scoring path as host-process sessions.
- [ ] A deterministic Python Match produces an equivalent normalized competitive outcome in container and host development modes while allowing telemetry to differ.
- [ ] Missing readiness, early stdout, early exit, and container startup failure are surfaced through the agreed fault or Infrastructure Failure boundary.
- [ ] Both containers are stopped and removed after the Match completes or a terminal fault occurs.
- [ ] Container startup, attachment, shutdown, and cleanup use operational timeouts distinct from competitive response budgets.

