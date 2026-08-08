# Diagnose container-host readiness without mutation

Status: ready-for-agent

Blocked by: 05, 08

## What to build

Give the organizer a read-only doctor command that explains whether the active
Docker-compatible environment is ready for the frozen catalog, artifact store,
and execution profile. It must work with the active Docker context, including
OrbStack, and must distinguish missing prerequisites from destructive or
automatic remediation.

## Acceptance criteria

- [ ] The doctor command reports Docker connectivity, active context, server platform and architecture, and required engine feature support.
- [ ] It checks catalog integrity, platform-specific base-image presence, organizer-layer and practice-artifact presence, and Bot Artifact store readability.
- [ ] It reports available disk, configured CPU visibility, profile enforcement prerequisites, and whether the requested Match parallelism is obviously impossible.
- [ ] It identifies whether prior rehearsal evidence matches the current machine, catalog, profile, platform, and parallelism.
- [ ] Diagnostics distinguish unavailable Docker, wrong context, wrong platform, missing pinned images, insufficient disk, unsupported controls, and corrupt local metadata.
- [ ] The command performs no pulls, builds, image loads, container starts, settings changes, cache pruning, deletions, or other Docker/host mutations.
- [ ] Output is stable and machine-readable enough for organizer automation while retaining concise human remediation guidance.
- [ ] A Docker-compatible active context is accepted without requiring Docker Desktop specifically.

