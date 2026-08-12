# Add and publish the Java Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Java Language Environment and immutable Catalog Release
with behavior equivalent to Python and Go across both supported platforms.

## Acceptance criteria

- [x] Java selects the latest upstream-supported LTS release available when the
  work begins and pins exact Linux/AMD64 and Linux/ARM64 JDK build-toolchain and
  execution-runtime identities.
- [x] The Team Source schema, networkless compilation recipe, fixed entrypoint,
  wrapper, readiness contract, and dependency policy are complete and
  organizer-owned.
- [x] The Java wrapper exposes the common strategy contract and its Seed Adapter
  passes published 64-bit-seed golden vectors.
- [x] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [x] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [x] Java Bot Artifacts can participate in mixed-language Tournament plans and
  Matches without language-specific Tournament logic.
- [x] A new Catalog Release and offline bundle are independently verified and
  expose immutable Java compatibility and build-toolchain coordinates.
- [x] No test or publication step fetches, imports, or inspects the Java Team
  Template repository.

## Answer

Added the production Java 25 Language Environment using Temurin 25.0.3+9, the
latest official container build available for the latest upstream-designated
LTS line at preparation time. The catalog pins distinct JDK build-toolchain and
JRE execution-runtime identities for Linux/AMD64 and Linux/ARM64 and owns a
closed Java SE standard-library Team Source schema, networkless `javac` recipe,
fixed entrypoint, readiness contract, wrapper, and `SplittableRandom` Seed
Adapter with published 64-bit golden vectors.

The complete conformance suite passed Linux/AMD64 Advisory Validation and native
Linux/ARM64 Final Validation, including build diagnostics, readiness, protocol,
determinism, isolation, resources, lifecycle, and practice Matches. Java and
Python Bot Artifacts also completed a mixed-language Match and created a
mixed-language Tournament Manifest through generic Runner paths. Catalog Release
`catalog-v4` and its offline bundle were independently verified with the Team
Template repository absent; the complete Python 3.9 suite passed 428 tests with
7 expected opt-in integration skips.
