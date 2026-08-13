# Add and publish the Ruby Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Ruby Language Environment and immutable Catalog Release
with behavior equivalent to the other required languages across both supported
platforms.

## Acceptance criteria

- [x] Ruby selects the latest upstream-supported stable release available when
  the work begins and pins exact Linux/AMD64 and Linux/ARM64 build-toolchain and
  execution-runtime identities.
- [x] The Ruby runtime and every approved dependency are available to the
  networkless build without resolving a mutable package source.
- [x] The Team Source schema, build recipe, fixed entrypoint, wrapper, readiness
  contract, and dependency policy are complete and organizer-owned.
- [x] The Ruby wrapper exposes the common strategy contract and its Seed Adapter
  passes published 64-bit-seed golden vectors without using ambient randomness.
- [x] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [x] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [x] Ruby Bot Artifacts can participate in mixed-language Tournament plans and
  Matches without language-specific Tournament logic.
- [x] A new Catalog Release and offline bundle are independently verified and
  expose immutable Ruby compatibility and build-toolchain coordinates.
- [x] No test or publication step fetches, imports, or inspects the Ruby Team
  Template repository.

## Answer

Ruby 4.0.6 is published in the independently verified `catalog-v14` release at
Runner commit `0b7f84a1aa3bf60efa5a5e0026d68b7b7337cb20`. The catalog pins exact
official Linux/AMD64 and Linux/ARM64 image manifests and owns the complete
standard-library-only, networkless source, wrapper, Seed Adapter, readiness,
entrypoint, dependency, and conformance contract.

The focused suite passed Advisory Validation on Linux/AMD64 and Final
Validation on Linux/ARM64. The isolated release proof passed all 156 organizer
workflow tests and confirmed the Runner has no dependency on the Team Template
repository. The offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:4ac566c60f7dbdbba162809a4a411eda97031192f668d508ea76edee722009cb`.
