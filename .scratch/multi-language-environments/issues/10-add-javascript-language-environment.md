# Add and publish the JavaScript Language Environment

Status: ready-for-agent

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production JavaScript Language Environment and immutable Catalog
Release with behavior equivalent to the other required languages across both
supported platforms.

## Acceptance criteria

- [ ] JavaScript selects the latest upstream-supported Node.js LTS available
  when the work begins and pins exact Linux/AMD64 and Linux/ARM64
  build-toolchain and execution-runtime identities.
- [ ] Node.js and every approved dependency are available to the networkless
  build without resolving a package registry or mutable dependency source.
- [ ] The Team Source schema, build recipe, fixed entrypoint, wrapper, readiness
  contract, and dependency policy are complete and organizer-owned.
- [ ] The JavaScript wrapper exposes the common strategy contract and its Seed
  Adapter passes published 64-bit-seed golden vectors without using ambient
  JavaScript randomness.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] JavaScript Bot Artifacts can participate in mixed-language Tournament
  plans and Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable JavaScript compatibility and build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the JavaScript
  Team Template repository.
