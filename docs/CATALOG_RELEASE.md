# Publishing a Catalog Release

A Catalog Release freezes the Runner-owned Language Environment Catalog and all
organizer-owned assets at one exact Runner commit. Its release record is the
JSON annotation on an immutable annotated Git tag. Its offline bundle is a
separate release artifact whose identity is recorded in that annotation.

The release process never reads or packages the Team Template repository.

## Create the release

Use a clean Runner checkout with its complete Git history. Select a new,
previously unused versioned tag and an output path outside the checkout:

```text
git status --short
./freeze-tournament-catalog create catalog-v1 \
  --bundle ../rps-runner-catalog-v1.bundle
```

Creation verifies the catalog and every declared asset, the source-validation
workflow, standard-library-only dependency policy, networkless recipe, pinned
CI actions, both platform runtime digests, conformance suite identities, and
execution profile identity. It then bundles the exact commit and its required
history, records the bundle digest in the manifest, and creates the annotated
tag. Existing bundle destinations and tag names are rejected.

The manifest's `compatibility_coordinates` object is the exact, copy-ready
interface required by a companion Template Release. Do not reconstruct or
partially copy it from other manifest fields.

Publish the exact commit, annotated tag, and bundle together. Do not recreate
the bundle after publication: its bytes are part of the Catalog Release
identity.

## Verify from a clean clone

Download the published bundle beside a fresh Runner clone, fetch the exact
annotated tag, and verify it:

```text
git clone <runner-repository> rps-tournament
cd rps-tournament
git switch --detach catalog-v1^{}
./freeze-tournament-catalog verify catalog-v1 \
  --bundle ../rps-runner-catalog-v1.bundle
```

Verification rejects a dirty tree, a lightweight or malformed tag, a tag aimed
at another commit, a changed manifest, missing or changed catalog assets,
mutable references, and bundle digest drift. It also clones the bundle locally
and proves that the resulting network-independent checkout has the pinned
Runner commit and Catalog identity. No Team Template checkout is needed.

An organizer can materialize the same Runner checkout while offline:

```text
git clone rps-runner-catalog-v1.bundle rps-tournament-offline
```

## Retain the independence proof

For a release intended for publication, run the integrated proof instead of the
standalone `create` command. Run it from a clean clone whose parent directory
does not contain the companion repository. The tag must be unused; the bundle
and evidence destinations must be outside the checkout and must not already
exist:

```text
./freeze-tournament-catalog prove catalog-v1 \
  --bundle ../rps-runner-catalog-v1.bundle \
  --evidence ../rps-runner-catalog-v1-independence.json
```

The proof creates and verifies the annotated Catalog Release and reproduces its
checkout from the offline bundle. It scans active Python, JavaScript, shell,
catalog workflow, package/configuration, test, and GitHub workflow surfaces for
a checkout, import, path, or network dependency on the companion repository.
It also requires the catalog tree to contain only `catalog.json` and the exact
asset paths declared under the catalog's closed set of organizer-owned roles.
Participant-facing starter paths, participant assets or digests in the Catalog
Release, and a public command for the packaged internal certification fixtures
are rejected.

It then runs the public preparation, source-validation, Bot Artifact build,
Final Validation, batch planning, Tournament planning and execution, rehearsal,
and presentation suites from a fresh checkout materialized from the offline
bundle. The resulting
`runner-catalog-independence-v1` evidence embeds the annotated tag manifest and
its exact `compatibility_coordinates`, records the internal fixture identity,
and lists every workflow suite that passed. Retain the JSON evidence beside
the exact bundle. CI retains both as one 90-day artifact for every commit.

## Corrections and replacement versions

Once a Catalog Release is frozen for Team coding, never move its tag, replace
its bundle, edit its annotation, or silently change any catalog asset. A
correction always receives a new package version where applicable, a new
versioned Catalog Release tag, and a newly named offline bundle. Publish release
notes that identify the superseded release and the reason for replacement.

Teams already coding against the earlier Catalog Release remain pinned to it
until the organizer explicitly adopts the replacement. A corresponding Team
Template compatibility change is a separate Template Release made in the
companion repository; it cannot mutate or repair the original Catalog Release.
