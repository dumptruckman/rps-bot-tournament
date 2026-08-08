# Batch official sources into a reviewable Tournament plan

Status: ready-for-agent

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

- [ ] The batch command consumes an explicit mapping of Team IDs, Team Display Names, and already-present local source directories.
- [ ] Validations and builds run concurrently up to an explicit operational limit while producing deterministic per-Team identities and stable plan ordering.
- [ ] Failed Team builds or validations are reported independently and cannot produce a roster-ready plan entry.
- [ ] A supervised compatibility repair retains the original frozen candidate, complete repair diff, organizer explanation, replacement source digest, and successful final validation identity.
- [ ] The generated JSON plan names Team identity, display name, selected source, validated Bot Artifact Manifest, artifact-store reference, Tournament Seed, execution mode, parallelism, catalog, execution profile, and global resource values.
- [ ] Mutable tags, branch names, GitHub URLs, contact details, archive paths, and local cache names do not become canonical Tournament identity.
- [ ] The plan is human-reviewable and supports intentional edits to presentation and Tournament configuration while preserving immutable artifact references.
- [ ] The workflow supports four through thirty-two Teams and defaults to the conservative four-Match parallelism for Continuous Mode.
- [ ] Source acquisition, GitHub authentication, branch discovery, cutoff enforcement, and remote pulling remain outside the core command.

