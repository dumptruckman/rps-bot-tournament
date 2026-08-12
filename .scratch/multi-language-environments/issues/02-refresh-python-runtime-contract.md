# Refresh and publish the Python Language Environment

Status: resolved

Blocked by: 01

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Apply the shared runtime and build-toolchain policy to Python, prove the existing
production environment through the generalized Runner, and publish an immutable
Catalog Release that the reorganized Python Team Template can consume.

## Acceptance criteria

- [x] Python selects the latest upstream-supported stable release available when
  the work begins, because Python does not designate a general LTS release, and
  records the selection rationale.
- [x] Exact Linux/AMD64 and Linux/ARM64 image digests are pinned; no active input
  resolves a mutable tag, release channel, or `latest` value.
- [x] The catalog publishes immutable Python build-toolchain coordinates suitable
  for a companion template's Docker check without transferring ownership of the
  official build recipe or wrapper.
- [x] The Python environment remains standard-library-only and its networkless
  build consumes only frozen Team Source and catalog-owned inputs.
- [x] Source validation, wrapper behavior, Seed Adapter determinism, readiness,
  entrypoint, diagnostics, resource enforcement, and practice-Match conformance
  pass through the generalized path on Linux/AMD64 and Linux/ARM64.
- [x] Existing Tournament records remain reproducible under their sealed older
  identities; the refresh creates new identities rather than mutating a prior
  Catalog Release.
- [x] A new Catalog Release and offline bundle are created and independently
  verified without access to the Team Template repository.
- [x] Release notes expose the exact compatibility coordinates needed by a
corresponding Python Template Release.

## Answer

Refreshed the production Python Language Environment to Python 3.14.6, the
latest upstream-supported stable release available on 2026-08-11. The catalog
now pins exact official-image manifests for Linux/AMD64 and Linux/ARM64 and
publishes explicit immutable build-toolchain and execution-runtime coordinates
while preserving the standard-library-only, networkless build contract.

The generalized Runner path passed complete real Docker conformance on both
platforms, including canonical native ARM64 ratification. Catalog publication
now validates the Python selection policy and produces copy-ready release notes
alongside the offline bundle and independence evidence. Catalog Release
`catalog-v2` was created from the implementation commit and independently
verified without the Team Template repository.
