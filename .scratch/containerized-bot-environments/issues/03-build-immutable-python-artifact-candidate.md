# Build an immutable Python Bot Artifact candidate

Status: resolved

Blocked by: 02

## What to build

Turn one validated Python source bundle into a single-platform container image
using only organizer-owned Language Environment inputs. The public builder must
work through the active Docker-compatible context, inject the wrapper and build
recipe from the frozen catalog, and return the exact image and build identities
needed for later conformance and Tournament use.

The resulting image is a candidate until the shared conformance suite certifies
it. A Team-built image, mutable tag, or participant-provided Dockerfile must
never become official execution authority.

## Acceptance criteria

- [x] The public builder accepts a validated frozen source bundle and an explicit target platform, then builds exactly one platform-specific image.
- [x] Team source and organizer-owned Language Environment inputs enter the build through separate controlled boundaries.
- [x] Builds run without networking, secrets, privileged mode, participant build scripts, or undeclared dependency installation.
- [x] The selected platform-specific base runtime is referenced and verified by immutable digest rather than mutable tag.
- [x] Successful output records the source digest, image manifest digest, runtime digest, language, catalog, wrapper, recipe, entrypoint, platform, core-tool, and suite-candidate identities.
- [x] The builder freezes the accepted source and retains bounded build diagnostics without treating local paths or cache names as canonical identity.
- [x] Wrong-platform output, unexpected image identity, build timeout, output overflow, and Docker failures produce actionable non-competitive build failures.
- [x] Repeating the build is not assumed to reproduce identical image bytes; the exact produced image is retained as the candidate authority.
- [x] The implementation uses the standard Docker CLI contract and honors the active Docker context, including Docker-compatible engines such as OrbStack.

## Answer

Added `rps-build-artifact`, which accepts a catalog-bound frozen source bundle
and one explicit Linux platform. The builder revalidates the bundle, captures
both Team and organizer-owned inputs by verified bytes, stages them through
separate Docker build contexts, verifies the locally prepared platform runtime
by immutable digest, and invokes the active Docker CLI with networking and pulls
disabled. No participant Dockerfile, build script, dependency installation,
secret, or privileged input enters the build.

Successful builds produce a non-overwritable, read-only candidate containing the
frozen source, bounded diagnostics, and an `artifact-candidate.json` identity
record. That record retains the exact manifest digest and immutable local image
ID along with source, runtime, language-environment, catalog, wrapper, recipe,
entrypoint, platform, core-tool, suite-candidate, and build identities. Mutable
local tags are explicitly operational and excluded from canonical build
identity. Failures are non-competitive, bounded, and actionable for invalid
bundles/platforms, runtime verification, Docker errors, timeouts, output
overflow, wrong-platform output, entrypoint drift, and image-ID mismatch.

The Docker CLI contract suite covers the public behavior, and an opt-in real
Linux/AMD64 integration test exercises the same public command after organizer
preparation has loaded the pinned runtime.
