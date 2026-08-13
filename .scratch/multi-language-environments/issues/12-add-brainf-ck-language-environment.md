# Add and publish the Brainf-ck Language Environment

Status: resolved

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Brainf-ck Language Environment and immutable Catalog
Release with behavior equivalent to the other required languages across both
supported platforms.

## Acceptance criteria

- [x] The environment documents one stable Brainf-ck dialect and selects a
  maintained implementation available when work begins, pinning its exact
  Linux/AMD64 and Linux/ARM64 identities; a catalog-owned implementation is
  versioned and identified as an immutable catalog asset instead.
- [x] The Brainf-ck implementation and every required build or execution input
  are available networklessly without resolving a mutable dependency source.
- [x] The Team Source schema, validation or build recipe, fixed entrypoint,
  wrapper, readiness contract, dialect, tape and cell semantics, and dependency
  policy are complete and organizer-owned.
- [x] The Brainf-ck strategy contract defines the exact encoding of opponent
  history and the 64-bit Bot-visible Seed, the valid move output, and
  deterministic behavior without ambient randomness; published golden vectors
  cover the Seed Adapter and encoding.
- [x] Validation and execution enforce source-size, tape, step, output, and time
  bounds so malformed or nonterminating programs fail with actionable
  categories.
- [x] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [x] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [x] Brainf-ck Bot Artifacts can participate in mixed-language Tournament plans
  and Matches without language-specific Tournament logic.
- [x] A new Catalog Release and offline bundle are independently verified and
  expose immutable Brainf-ck compatibility and implementation coordinates.
- [x] No test or publication step fetches, imports, or inspects the Brainf-ck
  Team Template repository.

## Answer

Added the production `brainf-ck-rps-v1` Language Environment with a versioned,
catalog-owned interpreter and Python 3.14.6 execution runtime. The Catalog pins
exact Python images for Linux/AMD64 and Linux/ARM64 and copies every build input
from immutable Catalog assets, with no build-time network or package resolution.

The dialect uses a fixed zero-initialized 30,000-cell tape, wrapping unsigned
8-bit cells, balanced standard loops, and a non-wrapping pointer. The
organizer-owned wrapper encodes the complete unsigned 64-bit Bot-visible Seed,
Turn, and both histories; publishes golden vectors; rejects ambient randomness;
and enforces source, tape, step, output, and time bounds. The shared conformance
suite covers fixed, seeded, copycat, and protocol practice Bot Artifacts plus
actionable syntax, readiness, protocol, tape, step, filesystem, process, and
premature-output diagnostics.

Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation passed the
complete build and conformance contract. The ARM64 proof also sealed a four-Team
mixed Brainf-ck/Python Tournament plan and the mixed-language Match completed
without faults.

Published `catalog-v19` at Runner commit
`d1ccc03975c14ca6ac539896587e8fa9402d3307`. Its Catalog identity is
`rps-language-environment-catalog-v1@sha256:5cf3fc6de60bbf5da3256fd3987440fe098f99dfcff9450787b1683338d29f69`,
its Brainf-ck conformance identity is
`brainf-ck-artifact-conformance-v1@sha256:4458ace4b58846542152c1eb334ded52ac102f85f57ad3514db4f32913ad3ecb`,
its catalog-owned interpreter identity is
`catalog-brainf-ck-interpreter-v1@sha256:86d8652f905b9836171b74ebd0be063df740b457d5d343f27af35312cb9d0432`,
and its independently verified offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:f72095b97678a18cfd4ca668e9bac1e24bcad0e3c9c8697a3da3bb829f6c5f68`.
No Runner dependency surface references the Team Template repository.
