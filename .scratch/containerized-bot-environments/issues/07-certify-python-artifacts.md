# Certify Python Bot Artifacts through one conformance suite

Status: resolved

Blocked by: 06

## What to build

Publish one versioned conformance command that converts a valid Python source
candidate into an officially validated Bot Artifact. Participant-local checks,
GitHub/AMD64 advisory validation, and organizer/ARM64 final validation must call
the same suite and report platform-specific identities without duplicating
validation logic.

The suite measures compatibility, not strategy strength. Practice Match losses
must never reject an otherwise conforming Bot Artifact.

## Acceptance criteria

- [x] One public suite entry point supports participant-local, GitHub advisory, and organizer-final modes through explicit inputs rather than separate implementations.
- [x] The suite covers source validation, networkless build, image identity, readiness, clean shutdown, representative protocol transcripts, repeated same-seed behavior, timing and stream limits, resource enforcement, isolation, diagnostics, and a complete smoke Match.
- [x] Bundled fixed-move, random, copycat, and protocol-test practice Bot Artifacts are built and run through the same Language Environment and container execution path.
- [x] Practice Match score or winner never gates validation; only build, launch, protocol, determinism, isolation, resource, and lifecycle conformance can fail it.
- [x] A successful result produces a complete Bot Artifact Manifest and validation report tied to source, image, runtime, wrapper, recipe, entrypoint, catalog, suite, platform, profile, and core-tool identities.
- [x] GitHub/AMD64 results are explicitly advisory and cannot be accepted as the canonical ARM64 Tournament artifact.
- [x] Organizer-final validation rejects a wrong-platform, missing, mutable-tag-only, digest-mismatched, stale-catalog, or wrong-profile candidate.
- [x] Syntax/build, import-time, nondeterministic, protocol-fault, slow-response, memory, process, filesystem, and premature-output fixtures produce actionable diagnostics.
- [x] Host-process development success is clearly reported as insufficient evidence for official validation.

## Answer

Implemented `rps-certify-artifact` as the single versioned conformance entry
point. It validates frozen candidate/build identities, uses immutable image IDs,
builds and runs all bundled practice and diagnostic Bot Artifacts through the
Python Language Environment and hardened container executor, and emits immutable
Bot Artifact Manifest and validation-report files with explicit authority.
