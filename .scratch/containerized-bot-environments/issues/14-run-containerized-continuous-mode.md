# Run containerized Continuous Mode without drift

Status: resolved

Blocked by: 13

## What to build

Run the complete container-backed Tournament path under existing Continuous Mode
parallelism and operational controls. Container startup and worker completion
order may vary, but canonical scheduling, shared-Team exclusion, commit order,
standings, playoff behavior, and Tournament outcome must remain deterministic.

Pause, Infrastructure Failure, suspected Security Violation, process
interruption, and resumption must stop at the existing boundaries and leave no
unowned or reusable Team container state.

## Acceptance criteria

- [x] Continuous Mode executes independent Matches concurrently up to the sealed worker limit while never scheduling the same Team in overlapping Matches.
- [x] Each active Match owns two fresh containers and all containers are terminated and removed at completion, terminal fault, pause boundary, or worker failure.
- [x] Reversed worker completion is buffered behind the canonical committable prefix exactly as in the existing Tournament Runner.
- [x] Pause requests, mode changes, Infrastructure Failures, suspected Security Violations, operator intervention, and interruption preserve their existing Tournament semantics.
- [x] Resumption uses the exact archived Bot Artifacts, profile, limits, and absolute Match Attempt ordinals.
- [x] Stale runner-owned containers from interrupted attempts are identified and cleaned without pruning unrelated Docker state.
- [x] Container timing, IDs, startup order, cleanup order, and resource observations may change telemetry but not Competition Records, standings, bracket, Champion, or Scoreboard Projection.
- [x] Repeated sealed Tournament runs with varied worker timing produce byte-identical canonical records and equivalent reconstructed state.
- [x] The public Continuous Mode command can complete a general plan-created Tournament through Tournament Champion declaration or the existing canonical no-champion outcome.

## Answer

The official `rps-tournament plan` command now exposes Continuous Mode start,
pause, resume, and boundary-only mode switching while retaining the sealed worker
limit and the Tournament Runner's canonical scheduling and commit frontier. A
general plan-created Tournament can run through Tournament Champion declaration;
pause and operator-intervention resumption continue from the archived execution
boundary with absolute Match Attempt ordinals.

Every container now carries separate canonical Match and Match Attempt ownership
labels. Before a Match Attempt starts, cleanup selects only runner-owned
containers for that Match, so containers left by any interrupted earlier ordinal
are removed without inspecting sibling workers or pruning unrelated Docker state.
Public-path tests prove Team-disjoint concurrency, reversed completion buffering,
byte-identical repeated Competition Records, equivalent reconstructed state, and
fresh two-container creation/removal through the real container executor boundary.
