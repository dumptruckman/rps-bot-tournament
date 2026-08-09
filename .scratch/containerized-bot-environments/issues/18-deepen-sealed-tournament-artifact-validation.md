# Deepen sealed Tournament artifact validation

Status: resolved

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

- [x] Draft Tournament-plan validation and sealed Tournament opening call one shared retained Bot Artifact verifier for the artifact-store index, retained manifest, canonical identity, platform, and organizer-final validation report.
- [x] The shared verifier keeps draft-plan selection checks separate from sealed-manifest authority checks and cannot make either path accept inputs the other path alone would reject.
- [x] Platform resolution and startup/shutdown timeouts form one immutable execution-input value with validation at its construction boundary.
- [x] Tournament creation and reopening pass that execution-input value intact to artifact resolver and container executor construction without parallel primitive parameters.
- [x] Reopening continues to derive the execution boundary from the same verified Tournament Manifest instance held under the Tournament run lock.
- [x] Every selected image is still verified at opening and each unresolved Match Attempt boundary, with restoration only from the verified archive.
- [x] Artifact resolution and restoration observations remain Operational Telemetry and never enter Competition Records or the Scoreboard Projection.
- [x] Existing missing, corrupt, wrong-platform, digest-mismatch, stale-catalog, stale-profile, stale-validation, interruption, retry, and deterministic-replay behavior remains covered through public seams.
- [x] The public `rps-tournament plan` command and its post-creation plan-optional resumption behavior remain unchanged.
- [x] The complete repository test suite remains green.

## Answer

Draft Tournament-plan validation and sealed Tournament opening now share one
retained Bot Artifact verifier for store integrity, canonical identity,
platform, retained manifest, and organizer-final validation authority. Their
distinct plan-selection and sealed-manifest checks remain outside that shared
boundary.

Platform selection and container lifecycle timeouts now travel as one frozen,
construction-validated `TournamentExecutionInputs` value through creation and
reopening resolver/executor construction. Reopening still derives it from the
verified Tournament Manifest under the Tournament run lock, while per-boundary
archive resolution and its Operational Telemetry behavior remain unchanged.

The complete 358-test repository suite passes with three Docker-gated tests
skipped.
