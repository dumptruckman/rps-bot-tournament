# Add and publish the C# Language Environment

Status: ready-for-agent

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production C# Language Environment and immutable Catalog Release with
behavior equivalent to the other supported languages across both platforms.

## Acceptance criteria

- [ ] The environment selects the latest upstream-supported .NET LTS available
  when work begins and pins exact Linux/AMD64 and Linux/ARM64 SDK build-toolchain
  and execution-runtime identities.
- [ ] The SDK and every required build input are available to the networkless
  build without resolving NuGet or another mutable dependency source.
- [ ] The Team Source schema, compilation recipe, fixed entrypoint, wrapper,
  readiness contract, and dependency policy are complete and organizer-owned.
- [ ] The C# wrapper exposes the common strategy contract and its Seed Adapter
  passes published 64-bit-seed golden vectors.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] C# Bot Artifacts can participate in mixed-language Tournament plans and
  Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable C# compatibility and build-toolchain coordinates.
- [ ] No test or publication step fetches, imports, or inspects the C# Team
  Template repository.
