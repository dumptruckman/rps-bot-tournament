# Add and publish the TypeScript Language Environment

Status: ready-for-agent

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production TypeScript Language Environment and immutable Catalog
Release with behavior equivalent to the other supported languages across both
platforms.

## Acceptance criteria

- [ ] The environment selects the latest upstream-supported Node.js LTS and an
  exactly pinned compatible stable TypeScript compiler available when work
  begins, with immutable Linux/AMD64 and Linux/ARM64 identities.
- [ ] The TypeScript compiler and all required build inputs are available to the
  networkless build without resolving a package registry or mutable dependency.
- [ ] The Team Source schema, compilation recipe, fixed entrypoint, wrapper,
  readiness contract, and dependency policy are complete and organizer-owned.
- [ ] The TypeScript wrapper exposes the common strategy contract and its Seed
  Adapter passes published 64-bit-seed golden vectors without using ambient
  JavaScript randomness.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] TypeScript Bot Artifacts can participate in mixed-language Tournament plans
  and Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable TypeScript compatibility and build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the TypeScript
  Team Template repository.
