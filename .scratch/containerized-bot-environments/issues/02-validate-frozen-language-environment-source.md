# Validate frozen Language Environment source

Status: resolved

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

- [x] A public command loads a versioned, immutable Language Environment catalog and validates a selected local source directory against its Python descriptor.
- [x] Valid multi-file Python source is copied into a frozen bundle with a deterministic source digest.
- [x] Traversal, absolute paths, escaping symlinks, unsupported file types, forbidden infrastructure files, excessive file counts, excessive individual sizes, and excessive aggregate size are rejected before Docker can receive the source.
- [x] Team source cannot provide or replace the official wrapper, Dockerfile, dependency definition, build target, workflow, readiness behavior, or entrypoint.
- [x] The Python participant surface remains the organizer-wrapper `choose_move` contract and supports approved accessory modules or resources.
- [x] Validation errors identify the offending source path and rule in actionable participant-facing language.
- [x] Catalog, descriptor, source-schema, wrapper, recipe, entrypoint, base-runtime, platform, and conformance identities have explicit immutable version fields.
- [x] A second contract-only Language Environment fixture can be loaded and validated without modifying Tournament scheduling, scoring, state, storage, or projection behavior.

## Answer

Added `rps-validate-source`, which loads a content-identified, versioned Language
Environment catalog and validates an already-present Team source directory before
creating a new, non-overwritable frozen bundle. Bundle identity is deterministic
over sorted relative paths and file bytes, and the resulting manifest records the
catalog digest, participant contract, and content-bound identity of every
organizer-controlled version. Catalog loading verifies the referenced assets,
including pinned ARM64 and AMD64 runtime definitions, before source validation.

The Python descriptor preserves `strategy.py` and the organizer-owned
`choose_move` contract while allowing accessory Python modules and controlled
resource files. Validation rejects unsafe catalog paths, all symlinks, special
files, unsupported locations and types, infrastructure paths, and count or size
limit breaches with the offending path and rule. It parses `strategy.py` without
executing Team code and requires the exact four-argument `choose_move` surface. A
contract-only non-Python descriptor exercises the same catalog and command
without touching Tournament behavior.
