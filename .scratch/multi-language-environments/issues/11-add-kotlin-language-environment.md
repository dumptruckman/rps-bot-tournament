# Add and publish the Kotlin Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Kotlin Language Environment and immutable Catalog Release
with behavior equivalent to the other required languages across both supported
platforms.

## Acceptance criteria

- [ ] Kotlin selects the latest upstream-supported stable compiler and a
  compatible upstream-supported Java LTS available when the work begins, with
  exact Linux/AMD64 and Linux/ARM64 build-toolchain and execution-runtime
  identities.
- [ ] The Kotlin compiler, JVM, and every approved library are available to the
  networkless build without resolving Maven Central or another mutable
  dependency source.
- [ ] The Team Source schema, compilation recipe, fixed entrypoint, wrapper,
  readiness contract, and dependency policy are complete and organizer-owned.
- [ ] The Kotlin wrapper exposes the common strategy contract and its Seed
  Adapter passes published 64-bit-seed golden vectors without using ambient
  randomness.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] Kotlin Bot Artifacts can participate in mixed-language Tournament plans
  and Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable Kotlin compatibility and build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the Kotlin Team
  Template repository.

## Answer

Added the production Kotlin Language Environment with Kotlin 2.4.10 and Java
25 LTS (Temurin 25.0.3+9). The Catalog pins exact Linux/AMD64 and Linux/ARM64
build-toolchain and execution-runtime images and vendors JetBrains' official
Kotlin compiler distribution by SHA-256, so builds require no Maven or other
mutable dependency source.

The organizer-owned `Strategy.kt` contract, wrapper, Seed Adapter, readiness
marker, fixed JAR entrypoint, source schema, dependency policy, practice
artifacts, and diagnostic fixtures are complete. Published 64-bit seed vectors
execute through Kotlin 2.4.10 without ambient randomness. Complete
Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation passed,
including isolation/resource/lifecycle checks, mixed-language Matches, and an
ARM64 mixed-language Tournament plan.

Published and independently verified `catalog-v18` at Runner commit
`0ce3603722b04be9a617563a1f36f52c8cb7f465`. Its Catalog identity is
`rps-language-environment-catalog-v1@sha256:47ce9003164c1fe9dfb4f1fd7c711e2fd11d45f041de1f5cb37fd7fad06f8c2d`,
its Kotlin conformance identity is
`kotlin-artifact-conformance-v1@sha256:f530c8e3e6719a48a0305afd7b33981c38e8a0cbf2d2aae305f1ca4606034af8`,
and its offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:035977c663d8c2e9613e26a75252799a802ab50e94d8a5c41cdb4c6cdfd34331`.
The complete Python 3.9 suite passed 482 tests with 14 expected opt-in skips.
Both review axes passed after addressing the initial publication, seed-vector,
and ARM64 proof findings; no Runner workflow depends on the Team Template
repository.
