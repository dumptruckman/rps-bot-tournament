# Execute a ready container through the Match boundary

Status: resolved

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

- [x] One fresh container is created for each Bot Position and both containers are created, started, attached, and awaited concurrently.
- [x] Each wrapper emits the reserved versioned readiness marker only after its Team strategy is loaded and it is ready for Turn 0.
- [x] The executor handles a readiness marker split across stream chunks and removes control data from Team stderr and its byte allowance.
- [x] Competitive response timing begins only after both wrappers are ready and the Match Runner sends Turn 0.
- [x] The container sessions participate in the same protocol, timing, move validation, Round construction, and scoring path as host-process sessions.
- [x] A deterministic Python Match produces an equivalent normalized competitive outcome in container and host development modes while allowing telemetry to differ.
- [x] Missing readiness, early stdout, early exit, and container startup failure are surfaced through the agreed fault or Infrastructure Failure boundary.
- [x] Both containers are stopped and removed after the Match completes or a terminal fault occurs.
- [x] Container startup, attachment, shutdown, and cleanup use operational timeouts distinct from competitive response budgets.

## Answer

Added a Docker CLI-backed Bot Artifact session and `ContainerMatchExecutor` behind the
existing Match-execution boundary. Match session lifecycle phases now run both
Bot Positions concurrently; wrapper readiness is parsed from stderr without
charging the Bot Artifact's stderr allowance, and bounded Docker lifecycle is kept
outside competitive Turn budgets. Executor-level tests cover parity, split
markers, early faults, Infrastructure Failures, and cleanup, including an
opt-in real-Docker test that builds and runs two Python artifact candidates.

Verified the complete builder-to-Match path against the local ARM64 Docker-
compatible engine with `RPS_RUN_DOCKER_INTEGRATION=1` and
`RPS_DOCKER_PLATFORM=linux/arm64`; the real container and host outcomes matched.
