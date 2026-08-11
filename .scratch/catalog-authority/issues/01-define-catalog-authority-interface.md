# Define the catalog authority and compatibility interface

Status: ready-for-agent

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

- [ ] An accepted decision assigns the Language Environment Catalog, Team Source
  schema, wrapper, Seed Adapter, runtimes, recipe, readiness contract,
  entrypoint, and conformance fixtures exclusively to this repository.
- [ ] The domain language distinguishes a Language Environment, Team Template,
  Template Release, catalog release, Advisory Validation, and Final Validation.
- [ ] The published compatibility interface identifies the exact Runner commit,
  package version, catalog path and identity, and offline bundle identity without
  naming a mutable branch or `latest` value.
- [ ] The decision states that this repository never fetches, imports, or tests
  the Team Template repository.
- [ ] Existing deterministic replay, organizer-wrapper authority, and immutable
  Tournament input decisions remain unchanged.

## Comments

This prefactors the ownership language before either repository moves files or
release tooling.
