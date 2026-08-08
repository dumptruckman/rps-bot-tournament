# Make container faults and lifecycle handling reliable

Status: ready-for-agent

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

- [ ] Invalid protocol, response timeout, unexpected Team exit, premature output, stream overflow, OOM, PID exhaustion, open-file exhaustion, and writable-filesystem exhaustion receive the documented attributable Bot Artifact fault classification.
- [ ] Image loading, daemon availability, create/start/attach/inspect failure, host exhaustion, and other non-attributable execution failures produce Infrastructure Failures.
- [ ] Only clear runtime evidence attributable to one or both Bot Artifacts can produce a suspected Security Violation and opaque evidence link.
- [ ] Container IDs, names, Docker commands, engine and host details, timestamps, startup and cleanup durations, stderr, resource observations, exit metadata, OOM state, and raw errors remain Operational Telemetry only.
- [ ] Readiness control data never appears in Team stderr telemetry or consumes the Team stderr allowance.
- [ ] Terminal completion or fault closes input, requests graceful termination, force-kills survivors after the grace period, reaps helper processes, and removes both Match containers.
- [ ] Runner-owned labels and canonical Match Attempt identity allow stale containers to be identified and cleaned without broad pruning or touching unrelated containers.
- [ ] Cleanup failure is retained diagnostically and cannot silently change a competitive outcome.
- [ ] The container executor passes the existing Match-executor contract for competitive normalization, telemetry separation, Infrastructure Failure, and security suspicion.

