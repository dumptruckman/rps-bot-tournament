# Add and publish the JavaScript Language Environment

Status: resolved

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

## Answer

Added the production JavaScript Language Environment on Node.js 24.19.0, the
latest release on the newest upstream-supported LTS line when selected. The
catalog pins exact official Linux/AMD64 and Linux/ARM64 Node image identities,
keeps Team Source standard-library-only, validates a closed `strategy.js`
boundary, and builds networklessly to the fixed organizer-owned entrypoint.

The organizer wrapper owns protocol I/O and readiness and exposes the common
`chooseMove` contract with a SplitMix64 Seed Adapter. Its published 64-bit
golden vectors execute through Node without ambient JavaScript randomness. The
complete diagnostic and practice fixture set passed Linux/AMD64 Advisory
Validation and Linux/ARM64 Final Validation. JavaScript and Python Bot
Artifacts also completed mixed-language Matches, and the ARM64 proof sealed
and executed a mixed-language Tournament plan.

Published and independently verified `catalog-v16` at Runner commit
`87296899a88f1e1a091fc08454be45a7354a73cb`. Its Catalog identity is
`rps-language-environment-catalog-v1@sha256:c70dac15b4c0220cb9315a92db7e3be696fd44a1f944a30a6f6c771864ebfb97`
and its offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:ec7db7d442a24a9bcc193ec42db1130e35bef8b2df255d5ce4828431f3ccb8b9`.
The independent proof ran 175 organizer workflow tests with 10 expected
Docker-integration skips from an isolated checkout where the companion Team
Template repository was absent. The complete Python 3.9 suite passed 476 tests
with 13 expected integration skips before publication.
