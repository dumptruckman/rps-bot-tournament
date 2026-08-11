# Publish an immutable Runner-owned catalog release

Status: resolved

Priority: 2

Blocked by: 01

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Let an organizer freeze, publish, and reproduce one immutable catalog release
from a clean Runner checkout, including all organizer-owned assets and the exact
offline core history needed by catalog consumers.

## Acceptance criteria

- [x] A release manifest records the Runner commit and package version, catalog
  identity, every catalog asset identity, execution profile and suite identities,
  and both platform runtime digests.
- [x] Catalog release creation and verification use an immutable annotated tag
  and reject a dirty tree, mutable references, missing assets, digest drift, or a
  tag that targets the wrong commit.
- [x] A clean clone can verify the release without the Team Template repository.
- [x] The offline Runner bundle reproduces the pinned commit and catalog identity
  without network access.
- [x] CI exercises manifest creation, tag verification, asset integrity, source
  validation, build/certification compatibility, and Python 3.9 support.
- [x] Release documentation explains correction/version replacement without
  silently changing a catalog already frozen for Team coding.

## Comments

The existing catalog-release ideas in the companion repository should be moved
or adapted here, excluding all Team Template identities.

## Answer

`freeze-tournament-catalog` now creates and verifies an annotated-tag manifest
and a digest-pinned offline Runner bundle. The manifest records the exact Runner
commit and package version, catalog path and identity, every catalog asset,
Python certification suite, execution profile, and both platform runtimes.

Verification rejects dirty repositories, mutable workflow or runtime references,
missing or changed assets, changed bundle bytes, lightweight tags, and tags on
the wrong commit. It locally materializes the bundle to prove the pinned commit
and Catalog identity without network access or the Team Template repository.

The Catalog Release CI lane exercises the release contract plus source,
networkless-build, certification, and Python 3.9 compatibility. The publication
runbook defines clean-clone verification and requires corrections to use a new
versioned release rather than changing a Catalog Release already frozen for Team
coding.
