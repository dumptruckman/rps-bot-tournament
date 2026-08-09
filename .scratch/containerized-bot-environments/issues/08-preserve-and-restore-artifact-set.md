# Preserve and restore the local Bot Artifact set

Status: resolved

Blocked by: 03

## What to build

Provide a durable local Bot Artifact store that retains frozen source bundles,
manifests, reports, an integrity-checked index, and the exact selected container
images. Selected images should be exported together so Docker can preserve
shared layers without duplicating the runtime once per Team.

The store must restore a missing image by exact digest and platform. It must
never rebuild, substitute a tag, or treat archive location as competitive
identity.

## Acceptance criteria

- [x] The local store retains frozen source bundles, Bot Artifact Manifests, validation reports, and an indexed set of selected images.
- [x] Multiple selected images can be exported together into one durable Docker image archive with an integrity-protected index.
- [x] Shared layers are preserved according to Docker archive behavior rather than intentionally duplicated once per Team.
- [x] Archive paths, local tags, and Docker cache locations remain operational references outside canonical Bot Artifact identity.
- [x] If an indexed image is absent from the active engine, the resolver loads the verified archive and re-verifies the exact image digest and platform.
- [x] Corrupt archives, corrupt indices, missing reports, missing images, wrong platforms, and digest mismatches fail closed with actionable integrity diagnostics.
- [x] Restoration never triggers a rebuild or mutable-tag substitution.
- [x] Deleting the selected images from the Docker cache and resolving them from the archive restores a launchable artifact with the original authoritative digest.
- [x] The store is local-first and requires no registry, object store, or network service.

## Answer

Added a local-first artifact store API that atomically retains each selected
frozen source bundle, Bot Artifact Manifest, and validation report beside one
shared Docker image archive. Preservation verifies the selected image IDs and
platforms, invokes `docker image save` once for the complete set, excludes
mutable tags and absolute store locations from the index, and protects the
archive, retained files, and index with SHA-256 identities.

The resolver verifies the entire store before inspecting Docker state. When the
exact immutable image ID is absent, it loads only the verified local archive and
then re-verifies the image ID and platform. Corrupt or incomplete stores, wrong
platforms, digest mismatches, failed archive loads, and archives missing the
selected image fail with integrity diagnostics; no restore path contains a
build, tag, registry, object-store, or network fallback.

The focused store suite covers multi-image export, retained inputs, index and
archive integrity, missing reports and images, digest and platform mismatches,
and exact restoration. The complete repository suite passes with the existing
three Docker-dependent tests skipped.
