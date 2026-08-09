# Run containerized Continuous Mode without drift

Status: claimed

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

- [ ] Continuous Mode executes independent Matches concurrently up to the sealed worker limit while never scheduling the same Team in overlapping Matches.
- [ ] Each active Match owns two fresh containers and all containers are terminated and removed at completion, terminal fault, pause boundary, or worker failure.
- [ ] Reversed worker completion is buffered behind the canonical committable prefix exactly as in the existing Tournament Runner.
- [ ] Pause requests, mode changes, Infrastructure Failures, suspected Security Violations, operator intervention, and interruption preserve their existing Tournament semantics.
- [ ] Resumption uses the exact archived Bot Artifacts, profile, limits, and absolute Match Attempt ordinals.
- [ ] Stale runner-owned containers from interrupted attempts are identified and cleaned without pruning unrelated Docker state.
- [ ] Container timing, IDs, startup order, cleanup order, and resource observations may change telemetry but not Competition Records, standings, bracket, Champion, or Scoreboard Projection.
- [ ] Repeated sealed Tournament runs with varied worker timing produce byte-identical canonical records and equivalent reconstructed state.
- [ ] The public Continuous Mode command can complete a general plan-created Tournament through Tournament Champion declaration or the existing canonical no-champion outcome.
