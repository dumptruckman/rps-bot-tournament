# Refresh and publish the Python Language Environment

Status: ready-for-agent

Blocked by: 01

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Apply the shared runtime and build-toolchain policy to Python, prove the existing
production environment through the generalized Runner, and publish an immutable
Catalog Release that the reorganized Python Team Template can consume.

## Acceptance criteria

- [ ] Python selects the latest upstream-supported stable release available when
  the work begins, because Python does not designate a general LTS release, and
  records the selection rationale.
- [ ] Exact Linux/AMD64 and Linux/ARM64 image digests are pinned; no active input
  resolves a mutable tag, release channel, or `latest` value.
- [ ] The catalog publishes immutable Python build-toolchain coordinates suitable
  for a companion template's Docker check without transferring ownership of the
  official build recipe or wrapper.
- [ ] The Python environment remains standard-library-only and its networkless
  build consumes only frozen Team Source and catalog-owned inputs.
- [ ] Source validation, wrapper behavior, Seed Adapter determinism, readiness,
  entrypoint, diagnostics, resource enforcement, and practice-Match conformance
  pass through the generalized path on Linux/AMD64 and Linux/ARM64.
- [ ] Existing Tournament records remain reproducible under their sealed older
  identities; the refresh creates new identities rather than mutating a prior
  Catalog Release.
- [ ] A new Catalog Release and offline bundle are created and independently
  verified without access to the Team Template repository.
- [ ] Release notes expose the exact compatibility coordinates needed by a
  corresponding Python Template Release.
