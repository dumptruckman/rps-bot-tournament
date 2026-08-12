# Add and publish the Go Language Environment

Status: resolved

Blocked by: 02

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver Go as the first new production Language Environment and publish a
Catalog Release that can Final Validate Go Team Source into Tournament-ready Bot
Artifacts on both supported platforms.

## Acceptance criteria

- [ ] Go selects the latest upstream-supported stable release available when the
  work begins and pins exact Linux/AMD64 and Linux/ARM64 build-toolchain and
  execution-runtime identities.
- [ ] The Team Source schema accepts only the documented Go strategy and approved
  resources while rejecting infrastructure, dependency substitution, unsafe
  paths, links, and size-limit violations.
- [ ] A networkless organizer-owned recipe compiles frozen Team Source and emits
  an immutable Bot Artifact with the fixed catalog-owned entrypoint.
- [ ] The organizer wrapper exposes the common strategy contract, owns protocol
  I/O and readiness, and rejects invalid or premature output consistently.
- [ ] The Go Seed Adapter has published golden vectors and maps every bot-visible
  64-bit seed deterministically without relying on system randomness.
- [ ] Fixed, random, copycat, protocol, syntax/build, startup, nondeterministic,
  slow, memory, process, filesystem, and premature-output fixtures exercise the
  Go environment through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  same build, protocol, readiness, determinism, isolation, resource, lifecycle,
  and practice-Match contract.
- [ ] Python and Go Bot Artifacts can appear in one Tournament plan and execute a
  Match without language-specific Tournament scheduling or scoring behavior.
- [ ] The published Catalog Release and offline bundle are independently verified
  and expose immutable compatibility and Go build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the Go Team
  Template repository.

## Comments

This is the production tracer bullet. Feed any generally applicable discoveries
back into the catalog contract before starting the remaining language tickets.

## Answer

Added the production Go 1.26.5 Language Environment with immutable official
Linux/AMD64 and Linux/ARM64 image coordinates, a closed standard-library-only
Team Source schema, a networkless compiled build, organizer-owned wrapper and
PCG Seed Adapter, published seed vectors, and the complete shared conformance
fixture set. Catalog publication now validates Go's stable-release policy and
emits build-toolchain coordinates for every production Language Environment.

The exact catalog identity passed Linux/AMD64 Advisory Validation and native
Linux/ARM64 Final Validation, including readiness, protocol, determinism,
isolation, resources, lifecycle, and practice Matches. A Python Bot Artifact
and Go Bot Artifact also completed a mixed-language Match without faults. The
full Python 3.9 suite passed with 420 tests and 6 expected Docker-integration
skips before Catalog Release publication.
