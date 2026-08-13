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
organizer-owned wrapper adapts the unsigned 64-bit Bot-visible Seed through a
documented deterministic 64-bit LCG stream, then encodes its move, the complete
Seed, Turn, and both histories. Published vectors cover both the stream and a
complete encoded record byte-for-byte. The wrapper rejects ambient randomness
and enforces source, tape, step, output, and time bounds. The shared conformance
suite covers fixed, seeded, copycat, and protocol practice Bot Artifacts plus
actionable syntax, readiness, protocol, tape, step, filesystem, process, and
premature-output diagnostics.

Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation passed the
complete build and conformance contract. The ARM64 proof also sealed a four-Team
mixed Brainf-ck/Python Tournament plan and the mixed-language Match completed
without faults.

Published the review-corrected `catalog-v20` at Runner commit
`c7d96f969275812b0ec4a13408bd4e4f7ee65579`. Its Catalog identity is
`rps-language-environment-catalog-v1@sha256:0f6af8f7c31924180c37c4d0cf2c142b171ee3c7786ef86f7aec826a1b6180be`,
its Brainf-ck conformance identity is
`brainf-ck-artifact-conformance-v1@sha256:5a46b3e6010736ddc36e91d198d40a551c1f593d0408d684bd268155b8aa0074`,
its catalog-owned interpreter identity is
`catalog-brainf-ck-interpreter-v1@sha256:86d8652f905b9836171b74ebd0be063df740b457d5d343f27af35312cb9d0432`,
and its independently verified offline bundle identity is
`rps-runner-offline-bundle-v1@sha256:b13435326549098feb0a3691e2d6f1b38e0f69e34ec16ead61ab930a18c37e69`.
No Runner dependency surface references the Team Template repository.
