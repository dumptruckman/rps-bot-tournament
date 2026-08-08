# Certify Python Bot Artifacts through one conformance suite

Status: ready-for-agent

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

- [ ] One public suite entry point supports participant-local, GitHub advisory, and organizer-final modes through explicit inputs rather than separate implementations.
- [ ] The suite covers source validation, networkless build, image identity, readiness, clean shutdown, representative protocol transcripts, repeated same-seed behavior, timing and stream limits, resource enforcement, isolation, diagnostics, and a complete smoke Match.
- [ ] Bundled fixed-move, random, copycat, and protocol-test practice Bot Artifacts are built and run through the same Language Environment and container execution path.
- [ ] Practice Match score or winner never gates validation; only build, launch, protocol, determinism, isolation, resource, and lifecycle conformance can fail it.
- [ ] A successful result produces a complete Bot Artifact Manifest and validation report tied to source, image, runtime, wrapper, recipe, entrypoint, catalog, suite, platform, profile, and core-tool identities.
- [ ] GitHub/AMD64 results are explicitly advisory and cannot be accepted as the canonical ARM64 Tournament artifact.
- [ ] Organizer-final validation rejects a wrong-platform, missing, mutable-tag-only, digest-mismatched, stale-catalog, or wrong-profile candidate.
- [ ] Syntax/build, import-time, nondeterministic, protocol-fault, slow-response, memory, process, filesystem, and premature-output fixtures produce actionable diagnostics.
- [ ] Host-process development success is clearly reported as insufficient evidence for official validation.

