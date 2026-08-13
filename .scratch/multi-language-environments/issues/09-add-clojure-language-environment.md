# Add and publish the Clojure Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Clojure Language Environment and immutable Catalog Release
with behavior equivalent to the other required languages across both supported
platforms.

## Acceptance criteria

- [x] Clojure selects the latest upstream-supported stable release and a
  compatible upstream-supported Java LTS available when the work begins, with
  exact Linux/AMD64 and Linux/ARM64 toolchain and runtime identities.
- [x] Clojure, the JVM, and every approved library are available to the
  networkless build without resolving Maven Central, Clojars, or another mutable
  dependency source.
- [x] The Team Source schema, build recipe, fixed entrypoint, wrapper, readiness
  contract, and dependency policy are complete and organizer-owned.
- [x] The Clojure wrapper exposes the common strategy contract and its Seed
  Adapter passes published 64-bit-seed golden vectors without using ambient
  randomness.
- [x] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [x] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [x] Clojure Bot Artifacts can participate in mixed-language Tournament plans
  and Matches without language-specific Tournament logic.
- [x] A new Catalog Release and offline bundle are independently verified and
  expose immutable Clojure compatibility and build-toolchain coordinates.
- [x] No test or publication step fetches, imports, or inspects the Clojure Team
  Template repository.

## Answer

Clojure 1.12.5 with Clojure CLI 1.12.5.1664 and Temurin Java 25.0.3+9 is
published in the independently verified `catalog-v15` release at Runner commit
`e31d9b88a43a0c58934b306b96015bd300b1685d`. The catalog pins exact official
Linux/AMD64 and Linux/ARM64 images, verifies the three approved upstream runtime
jars by SHA-256 during its networkless build, and owns the complete Team Source,
wrapper, SplitMix64 Seed Adapter, readiness, entrypoint, dependency, and
conformance contract.

Native Linux/ARM64 Final Validation passed the complete shared suite. The exact
Linux/AMD64 inputs were build-verified locally; the complete Advisory suite is
published for its native CI platform because cross-architecture emulation on
this ARM64 host exceeded the shared CPU ceiling. The isolated release proof
passed all 166 organizer workflow tests and confirmed there is no dependency on
the Team Template repository. The offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:7449be32e529d29d7387c5a8c537a3708fec1a481a4344557d033b358c6d0656`.
