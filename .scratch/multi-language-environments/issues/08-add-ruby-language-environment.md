# Add and publish the Ruby Language Environment

Status: ready-for-agent

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Ruby Language Environment and immutable Catalog Release
with behavior equivalent to the other required languages across both supported
platforms.

## Acceptance criteria

- [ ] Ruby selects the latest upstream-supported stable release available when
  the work begins and pins exact Linux/AMD64 and Linux/ARM64 build-toolchain and
  execution-runtime identities.
- [ ] The Ruby runtime and every approved dependency are available to the
  networkless build without resolving a mutable package source.
- [ ] The Team Source schema, build recipe, fixed entrypoint, wrapper, readiness
  contract, and dependency policy are complete and organizer-owned.
- [ ] The Ruby wrapper exposes the common strategy contract and its Seed Adapter
  passes published 64-bit-seed golden vectors without using ambient randomness.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] Ruby Bot Artifacts can participate in mixed-language Tournament plans and
  Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable Ruby compatibility and build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the Ruby Team
  Template repository.
