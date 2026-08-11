# Catalog compatibility interface

A Catalog Release is the only published seam between the RPS Tournament Runner
and an independently maintained Team Template. The Runner publishes the release;
a Template Release copies the complete compatibility coordinates below into its
compatibility claim without weakening or replacing any value.

## Compatibility coordinates

The claim is a JSON object with exactly these required coordinates:

```json
{
  "format_version": "rps-catalog-compatibility-v1",
  "runner": {
    "commit": "<full 40-lowercase-hex Git commit>",
    "package_version": "<exact installed rps-tournament package version>"
  },
  "catalog": {
    "path": "language_environments/catalog-v1/catalog.json",
    "identity": "rps-language-environment-catalog-v1@sha256:<64-lowercase-hex>",
    "assets": {
      "<environment>.<asset>": "<asset-version>@sha256:<64-lowercase-hex>"
    }
  },
  "offline_bundle": {
    "identity": "rps-runner-offline-bundle-v1@sha256:<64-lowercase-hex>"
  }
}
```

- `runner.commit` identifies the exact Runner source tree. It is a complete Git
  object ID, never a branch, tag, abbreviated commit, or other moving ref.
- `runner.package_version` is the exact package version built from that commit.
- `catalog.path` is the repository-relative POSIX path at that commit. It must
  not be absolute and must not contain `.` or `..` segments.
- `catalog.identity` is the catalog's declared version joined to the SHA-256
  digest of its canonical content. Loading the path at the pinned commit must
  reproduce this value and verify all catalog-owned asset identities.
- `catalog.assets` is the complete map of every catalog environment/asset key to
  the asset's declared version joined to its verified SHA-256 digest. The
  placeholder above describes the key and value forms; a published claim
  contains one concrete entry for every asset and no placeholder entry.
- `offline_bundle.identity` is the declared offline-bundle format joined to the
  SHA-256 digest of the bundle bytes. The bundle must materialize the pinned
  Runner commit and reproduce the catalog identity without network access.

Every coordinate is equality-matched. Consumers must reject a missing field,
missing or extra asset, different commit, version, path, identity, asset
identity, or bundle identity. Values such as a mutable branch, `latest`, or an
unqualified mutable container tag are invalid and must not be resolved as a
fallback.

## Repository direction

The compatibility claim belongs to a Template Release and is evidence that its
participant-facing files adapt the named Catalog Release. It does not become a
Runner input. The Runner never fetches, imports, or tests a Team Template or its
repository, whether online, from an offline bundle, or as a release prerequisite.

The offline bundle contains Runner history and Runner-owned catalog assets only.
It must not contain a Team Template, Template Release, Team Template digest, or
Team Template repository history.

## Validation authority

Advisory Validation may use a Template Release's claim to give a Team early
compatibility feedback. Its result cannot enter a Tournament roster. Final
Validation independently uses the organizer-selected exact Catalog Release
coordinates, rebuilds the selected Team Source using only Runner-owned catalog
assets, and is the authoritative gate for the resulting Bot Artifact. Comparing
a Template Release claim with those coordinates happens outside the Runner and
remains advisory; the claim is never a Runner input.

These coordinates add no mutable Tournament input. Once a Tournament Manifest
is sealed, the existing catalog, artifact, validation, execution-profile, seed,
and replay identities remain immutable.
