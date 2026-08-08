# Validate frozen Language Environment source

Status: ready-for-agent

Blocked by: None

## What to build

Give Teams and organizers one public validation path from an already-present
source directory to a frozen, deterministic source bundle identity. The first
real Language Environment is Python and preserves the existing `choose_move`
strategy API while allowing multiple approved source and accessory files.

The Language Environment descriptor must define the Team-editable schema and
organizer-owned inputs without teaching Tournament scheduling or scoring about
individual languages. A small non-Python contract fixture should demonstrate
that another descriptor can be represented without adding language conditionals
to Tournament code.

## Acceptance criteria

- [ ] A public command loads a versioned, immutable Language Environment catalog and validates a selected local source directory against its Python descriptor.
- [ ] Valid multi-file Python source is copied into a frozen bundle with a deterministic source digest.
- [ ] Traversal, absolute paths, escaping symlinks, unsupported file types, forbidden infrastructure files, excessive file counts, excessive individual sizes, and excessive aggregate size are rejected before Docker can receive the source.
- [ ] Team source cannot provide or replace the official wrapper, Dockerfile, dependency definition, build target, workflow, readiness behavior, or entrypoint.
- [ ] The Python participant surface remains the organizer-wrapper `choose_move` contract and supports approved accessory modules or resources.
- [ ] Validation errors identify the offending source path and rule in actionable participant-facing language.
- [ ] Catalog, descriptor, source-schema, wrapper, recipe, entrypoint, base-runtime, platform, and conformance identities have explicit immutable version fields.
- [ ] A second contract-only Language Environment fixture can be loaded and validated without modifying Tournament scheduling, scoring, state, storage, or projection behavior.

