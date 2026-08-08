# Build an immutable Python Bot Artifact candidate

Status: ready-for-agent

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

- [ ] The public builder accepts a validated frozen source bundle and an explicit target platform, then builds exactly one platform-specific image.
- [ ] Team source and organizer-owned Language Environment inputs enter the build through separate controlled boundaries.
- [ ] Builds run without networking, secrets, privileged mode, participant build scripts, or undeclared dependency installation.
- [ ] The selected platform-specific base runtime is referenced and verified by immutable digest rather than mutable tag.
- [ ] Successful output records the source digest, image manifest digest, runtime digest, language, catalog, wrapper, recipe, entrypoint, platform, core-tool, and suite-candidate identities.
- [ ] The builder freezes the accepted source and retains bounded build diagnostics without treating local paths or cache names as canonical identity.
- [ ] Wrong-platform output, unexpected image identity, build timeout, output overflow, and Docker failures produce actionable non-competitive build failures.
- [ ] Repeating the build is not assumed to reproduce identical image bytes; the exact produced image is retained as the candidate authority.
- [ ] The implementation uses the standard Docker CLI contract and honors the active Docker context, including Docker-compatible engines such as OrbStack.

