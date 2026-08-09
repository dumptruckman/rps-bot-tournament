# Diagnose container-host readiness without mutation

Status: resolved

Blocked by: 05, 08

## What to build

Give the organizer a read-only doctor command that explains whether the active
Docker-compatible environment is ready for the frozen catalog, artifact store,
and execution profile. It must work with the active Docker context, including
OrbStack, and must distinguish missing prerequisites from destructive or
automatic remediation.

## Acceptance criteria

- [x] The doctor command reports Docker connectivity, active context, server platform and architecture, and required engine feature support.
- [x] It checks catalog integrity, platform-specific base-image presence, organizer-layer and practice-artifact presence, and Bot Artifact store readability.
- [x] It reports available disk, configured CPU visibility, profile enforcement prerequisites, and whether the requested Match parallelism is obviously impossible.
- [x] It identifies whether prior rehearsal evidence matches the current machine, catalog, profile, platform, and parallelism.
- [x] Diagnostics distinguish unavailable Docker, wrong context, wrong platform, missing pinned images, insufficient disk, unsupported controls, and corrupt local metadata.
- [x] The command performs no pulls, builds, image loads, container starts, settings changes, cache pruning, deletions, or other Docker/host mutations.
- [x] Output is stable and machine-readable enough for organizer automation while retaining concise human remediation guidance.
- [x] A Docker-compatible active context is accepted without requiring Docker Desktop specifically.

## Answer

Added the read-only `rps-doctor` command and versioned
`container-host-readiness-v1` JSON report. It inspects the active Docker context,
server identity and native platform, modern or legacy cgroup controls, seccomp,
memory and PID enforcement, catalog assets and pinned base runtimes, explicitly
identified organizer layers and practice Bot Artifacts, the integrity-checked
Bot Artifact store, host-store disk availability, Docker-visible CPUs, execution
profile identity, and requested Match parallelism.

Optional `rps-rehearsal-report-v1` evidence is compared against exact machine,
engine, context, catalog, profile, platform, parallelism, and passed-status
bindings. Diagnostics use stable codes with human remediation while keeping
missing, corrupt, stale, wrong-context, wrong-platform, capacity, and unsupported
control conditions distinct.

The Docker allowlist is limited to context, version, info, and image inspection;
the command contains no preparation or remediation operations. Focused tests
prove the allowlist, failure taxonomy, immutable prepared-image requirements,
rehearsal matching, and OrbStack's cgroup-v2 behavior. The complete 316-test
repository suite passes with the existing three Docker-dependent skips.
