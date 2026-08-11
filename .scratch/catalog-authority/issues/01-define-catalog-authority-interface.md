# Define the catalog authority and compatibility interface

Status: resolved

Priority: 2

Blocked by: None

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Define one explicit repository seam in which the Runner owns the Language
Environment Catalog while Team Templates are independent adapters that claim
compatibility with an exact published catalog identity. Align the domain
language and architecture decisions so later migration work cannot recreate two
authorities.

## Acceptance criteria

- [x] An accepted decision assigns the Language Environment Catalog, Team Source
  schema, wrapper, Seed Adapter, runtimes, recipe, readiness contract,
  entrypoint, and conformance fixtures exclusively to this repository.
- [x] The domain language distinguishes a Language Environment, Team Template,
  Template Release, catalog release, Advisory Validation, and Final Validation.
- [x] The published compatibility interface identifies the exact Runner commit,
  package version, catalog path and identity, and offline bundle identity without
  naming a mutable branch or `latest` value.
- [x] The decision states that this repository never fetches, imports, or tests
  the Team Template repository.
- [x] Existing deterministic replay, organizer-wrapper authority, and immutable
  Tournament input decisions remain unchanged.

## Comments

This prefactors the ownership language before either repository moves files or
release tooling.

## Answer

Accepted ADR 0005 makes this repository the sole authority for the Language
Environment Catalog and every organizer-owned Language Environment asset. The
domain glossary now distinguishes Language Environment, Team Source, Team
Template, Template Release, Catalog Release, Advisory Validation, and Final
Validation.

`docs/CATALOG_COMPATIBILITY.md` defines the immutable compatibility coordinates:
the full Runner commit, exact package version, catalog path and identity, the
complete catalog asset identity map, and offline bundle identity. It rejects
mutable refs and makes the dependency one-way: Template Releases may claim
compatibility, while the Runner never fetches, imports, or tests their repository.

The superseded split-authority paragraph in the earlier containerized-environment
PRD now points to the accepted boundary. ADR 0005 explicitly preserves the
existing deterministic replay, organizer-wrapper, immutable Tournament input,
Competition Record, telemetry, and resumption decisions.
