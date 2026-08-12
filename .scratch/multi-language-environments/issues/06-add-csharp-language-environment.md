# Add and publish the C# Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production C# Language Environment and immutable Catalog Release with
behavior equivalent to the other supported languages across both platforms.

## Acceptance criteria

- [x] The environment selects the latest upstream-supported .NET LTS available
  when work begins and pins exact Linux/AMD64 and Linux/ARM64 SDK build-toolchain
  and execution-runtime identities.
- [x] The SDK and every required build input are available to the networkless
  build without resolving NuGet or another mutable dependency source.
- [x] The Team Source schema, compilation recipe, fixed entrypoint, wrapper,
  readiness contract, and dependency policy are complete and organizer-owned.
- [x] The C# wrapper exposes the common strategy contract and its Seed Adapter
  passes published 64-bit-seed golden vectors.
- [x] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [x] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [x] C# Bot Artifacts can participate in mixed-language Tournament plans and
  Matches without language-specific Tournament logic.
- [x] A new Catalog Release and offline bundle are independently verified and
  expose immutable C# compatibility and build-toolchain coordinates.
- [x] No test or publication step fetches, imports, or inspects the C# Team
  Template repository.

## Answer

Added the production C# Language Environment on .NET 10 LTS, pinned to SDK
10.0.302 and runtime 10.0.10 with exact Linux/AMD64 and Linux/ARM64 image
manifests. The organizer-owned compiler recipe invokes Roslyn against the
SDK-local reference pack without NuGet restoration, and publishes a fixed
framework-dependent runtime entrypoint.

The environment owns the closed Team Source schema, C# strategy validator,
wrapper, SplitMix64 Seed Adapter and published 64-bit golden vectors, readiness
contract, practice artifacts, and complete diagnostic suite. Native ARM64 Final
Validation and emulated AMD64 Advisory Validation passed, including a
mixed-language C#/Python Match. Catalog release and independence-proof coverage
now include every C# asset and both immutable toolchain coordinates without a
reverse dependency on the Team Template repository.
