# Batch official sources into a reviewable Tournament plan

Status: resolved

Blocked by: 07, 08, 09

## What to build

Turn organizer-selected local Team source directories into the official set of
validated ARM64 Bot Artifacts and a draft human-reviewable JSON Tournament plan.
Safe source bundling, builds, and validation should run concurrently without
making completion timing part of artifact identity.

The workflow must support a supervised compatibility-only repair while retaining
the original source, repair diff, explanation, and final validation identity.
Source acquisition and cutoff selection remain explicit organizer inputs rather
than GitHub automation.

## Acceptance criteria

- [x] The batch command consumes an explicit mapping of Team IDs, Team Display Names, and already-present local source directories.
- [x] Validations and builds run concurrently up to an explicit operational limit while producing deterministic per-Team identities and stable plan ordering.
- [x] Failed Team builds or validations are reported independently and cannot produce a roster-ready plan entry.
- [x] A supervised compatibility repair retains the original frozen candidate, complete repair diff, organizer explanation, replacement source digest, and successful final validation identity.
- [x] The generated JSON plan names Team identity, display name, selected source, validated Bot Artifact Manifest, artifact-store reference, Tournament Seed, execution mode, parallelism, catalog, execution profile, and global resource values.
- [x] Mutable tags, branch names, GitHub URLs, contact details, archive paths, and local cache names do not become canonical Tournament identity.
- [x] The plan is human-reviewable and supports intentional edits to presentation and Tournament configuration while preserving immutable artifact references.
- [x] The workflow supports four through thirty-two Teams and defaults to the conservative four-Match parallelism for Continuous Mode.
- [x] Source acquisition, GitHub authentication, branch discovery, cutoff enforcement, and remote pulling remain outside the core command.

## Answer

Added `rps-batch-plan`, which consumes an explicit local Team source mapping and
runs each source-to-organizer-final Bot Artifact workflow concurrently under the
required `--jobs` limit. It writes stable Team-ordered results, reports failures
independently, preserves successful Bot Artifacts in one shared local store, and
only emits a draft roster-ready Tournament plan when every Team succeeds.

The plan includes immutable source, Bot Artifact, store-index, validation,
catalog, profile, resource, seed, mode, and parallelism values. It structurally
separates the exact validated Bot Artifact Manifest from the cache-free canonical
identity projection. Supervised repairs retain both frozen source bundles, a
complete deterministic diff (including complete binary content), organizer
explanation, replacement digest, and final validation identity.
