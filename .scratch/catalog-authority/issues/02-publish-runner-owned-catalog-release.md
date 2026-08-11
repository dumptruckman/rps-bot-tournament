# Publish an immutable Runner-owned catalog release

Status: ready-for-agent

Priority: 2

Blocked by: 01

## Parent

[Runner-owned Language Environment Catalog](../PRD.md)

## What to build

Let an organizer freeze, publish, and reproduce one immutable catalog release
from a clean Runner checkout, including all organizer-owned assets and the exact
offline core history needed by catalog consumers.

## Acceptance criteria

- [ ] A release manifest records the Runner commit and package version, catalog
  identity, every catalog asset identity, execution profile and suite identities,
  and both platform runtime digests.
- [ ] Catalog release creation and verification use an immutable annotated tag
  and reject a dirty tree, mutable references, missing assets, digest drift, or a
  tag that targets the wrong commit.
- [ ] A clean clone can verify the release without the Team Template repository.
- [ ] The offline Runner bundle reproduces the pinned commit and catalog identity
  without network access.
- [ ] CI exercises manifest creation, tag verification, asset integrity, source
  validation, build/certification compatibility, and Python 3.9 support.
- [ ] Release documentation explains correction/version replacement without
  silently changing a catalog already frozen for Team coding.

## Comments

The existing catalog-release ideas in the companion repository should be moved
or adapted here, excluding all Team Template identities.
