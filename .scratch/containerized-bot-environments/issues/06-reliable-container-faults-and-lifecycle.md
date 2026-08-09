# Make container faults and lifecycle handling reliable

Status: resolved

Blocked by: 05

## What to build

Complete the container executor's outcome classification, telemetry, and
lifecycle behavior under failure. Published, attributable Bot Artifact breaches
must feed the existing competitive fault behavior, while Docker and host
failures must feed the existing Infrastructure Failure policy. Prevention stays
primary; a suspected Security Violation is returned only for clear attributable
evidence.

Cleanup must be bounded and precise so a terminal fault, daemon problem, or
interrupted Match Attempt cannot leave unrelated Docker state at risk.

## Acceptance criteria

- [x] Invalid protocol, response timeout, unexpected Bot Artifact exit, premature output, stream overflow, OOM, PID exhaustion, open-file exhaustion, and writable-filesystem exhaustion receive the documented attributable Bot Artifact fault classification.
- [x] Image loading, daemon availability, create/start/attach/inspect failure, host exhaustion, and other non-attributable execution failures produce Infrastructure Failures.
- [x] Only clear runtime evidence attributable to one or both Bot Artifacts can produce a suspected Security Violation and opaque evidence link.
- [x] Container IDs, names, Docker commands, engine and host details, timestamps, startup and cleanup durations, stderr, resource observations, exit metadata, OOM state, and raw errors remain Operational Telemetry only.
- [x] Readiness control data never appears in Bot Artifact stderr telemetry or consumes the Bot Artifact stderr allowance.
- [x] Terminal completion or fault closes input, requests graceful termination, force-kills survivors after the grace period, reaps helper processes, and removes both Match containers.
- [x] Runner-owned labels and canonical Match Attempt identity allow stale containers to be identified and cleaned without broad pruning or touching unrelated containers.
- [x] Cleanup failure is retained diagnostically and cannot silently change a competitive outcome.
- [x] The container executor passes the existing Match-executor contract for competitive normalization, telemetry separation, Infrastructure Failure, and security suspicion.

## Answer

The container executor now classifies protocol, timing, stream, exit, OOM, and
trusted runtime-reported resource breaches as competitive Bot Artifact faults,
while daemon, Docker operation, host, ambiguous runtime, and inspection failures
remain Infrastructure Failures. Suspected Security Violations require the
organizer-reserved attributable runtime evidence signal and expose only an
opaque evidence link outside Operational Telemetry.

Every Match Attempt uses deterministic runner-owned names and exact ownership,
Match Attempt, and Bot Position labels. Startup cleans only stale containers
matching both runner and canonical attempt identity. Terminal paths close input,
gracefully stop both containers, kill survivors after a bound, reap helpers,
capture final status, and individually remove both containers. All cleanup
failures are retained without replacing an established competitive outcome.

Operational Telemetry now retains pre-session and per-container Docker commands,
raw errors, IDs, names, labels, engine/host facts, timestamps and durations,
readiness observations, bounded Bot Artifact stderr, exit/OOM metadata, and
resource observations. Public executor tests cover competitive normalization,
resource and security attribution, Infrastructure Failures, telemetry separation,
precise stale cleanup, and graceful/forced lifecycle behavior.
