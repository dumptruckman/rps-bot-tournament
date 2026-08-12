# Add and publish the TypeScript Language Environment

Status: resolved

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

## Answer

Added the production TypeScript Language Environment using Node.js 24.19.0 LTS
and the exactly pinned TypeScript 6.0.3 compiler. The compiler package is a
catalog-owned, checksummed offline build input; both Node platform images are
pinned to immutable Linux/AMD64 and Linux/ARM64 manifests. The environment owns
the closed Team Source schema, networkless recipe, fixed entrypoint, readiness
contract, wrapper, SplitMix64 Seed Adapter and published 64-bit golden vectors,
plus the complete shared practice and diagnostic fixture set.

The complete conformance contract passed Linux/AMD64 Advisory Validation and
native Linux/ARM64 Final Validation. ARM64 also built, certified, retained, and
sealed TypeScript and Python Bot Artifacts into one mixed-language Tournament
plan, and a mixed-language Match completed without faults. Catalog publication
tests cover every immutable TypeScript asset, runtime, compiler, conformance,
and offline-bundle coordinate without accessing the Team Template repository.
