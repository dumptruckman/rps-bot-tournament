# Deepen sealed Tournament artifact validation

Status: ready-for-agent

Blocked by: 13

## What to build

Refine the Tournament creation and resumption path so retained Bot Artifact
verification and sealed execution inputs each have one focused module boundary.
Draft-plan validation and sealed-manifest opening must share the same retained
artifact-store, Bot Artifact Manifest, and final-validation verification logic
without weakening their distinct authorities.

Represent the platform-by-artifact mapping and startup/shutdown timeouts as one
constrained execution-input value instead of repeatedly unpacking and passing
the three values independently through plan validation, sealed validation,
resolver construction, and executor construction.

Preserve the public commands, JSON formats, sealed Tournament identity,
run-lock authority, archive-only restoration behavior, Infrastructure Failure
policy, Operational Telemetry separation, and deterministic Competition Records.

## Acceptance criteria

- [ ] Draft Tournament-plan validation and sealed Tournament opening call one shared retained Bot Artifact verifier for the artifact-store index, retained manifest, canonical identity, platform, and organizer-final validation report.
- [ ] The shared verifier keeps draft-plan selection checks separate from sealed-manifest authority checks and cannot make either path accept inputs the other path alone would reject.
- [ ] Platform resolution and startup/shutdown timeouts form one immutable execution-input value with validation at its construction boundary.
- [ ] Tournament creation and reopening pass that execution-input value intact to artifact resolver and container executor construction without parallel primitive parameters.
- [ ] Reopening continues to derive the execution boundary from the same verified Tournament Manifest instance held under the Tournament run lock.
- [ ] Every selected image is still verified at opening and each unresolved Match Attempt boundary, with restoration only from the verified archive.
- [ ] Artifact resolution and restoration observations remain Operational Telemetry and never enter Competition Records or the Scoreboard Projection.
- [ ] Existing missing, corrupt, wrong-platform, digest-mismatch, stale-catalog, stale-profile, stale-validation, interruption, retry, and deterministic-replay behavior remains covered through public seams.
- [ ] The public `rps-tournament plan` command and its post-creation plan-optional resumption behavior remain unchanged.
- [ ] The complete repository test suite remains green.
