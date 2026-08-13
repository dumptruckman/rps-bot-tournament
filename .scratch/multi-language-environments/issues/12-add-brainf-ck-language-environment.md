# Add and publish the Brainf-ck Language Environment

Status: ready-for-agent

Blocked by: 03

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Deliver a production Brainf-ck Language Environment and immutable Catalog
Release with behavior equivalent to the other required languages across both
supported platforms.

## Acceptance criteria

- [ ] The environment documents one stable Brainf-ck dialect and selects a
  maintained implementation available when work begins, pinning its exact
  Linux/AMD64 and Linux/ARM64 identities; a catalog-owned implementation is
  versioned and identified as an immutable catalog asset instead.
- [ ] The Brainf-ck implementation and every required build or execution input
  are available networklessly without resolving a mutable dependency source.
- [ ] The Team Source schema, validation or build recipe, fixed entrypoint,
  wrapper, readiness contract, dialect, tape and cell semantics, and dependency
  policy are complete and organizer-owned.
- [ ] The Brainf-ck strategy contract defines the exact encoding of opponent
  history and the 64-bit Bot-visible Seed, the valid move output, and
  deterministic behavior without ambient randomness; published golden vectors
  cover the Seed Adapter and encoding.
- [ ] Validation and execution enforce source-size, tape, step, output, and time
  bounds so malformed or nonterminating programs fail with actionable
  categories.
- [ ] Equivalent practice and diagnostic fixtures pass or fail with actionable
  categories through the shared conformance suite.
- [ ] Linux/AMD64 Advisory Validation and Linux/ARM64 Final Validation pass the
  complete build, protocol, readiness, determinism, isolation, resource,
  lifecycle, and practice-Match contract.
- [ ] Brainf-ck Bot Artifacts can participate in mixed-language Tournament plans
  and Matches without language-specific Tournament logic.
- [ ] A new Catalog Release and offline bundle are independently verified and
  expose immutable Brainf-ck compatibility and implementation coordinates.
- [ ] No test or publication step fetches, imports, or inspects the Brainf-ck
  Team Template repository.
