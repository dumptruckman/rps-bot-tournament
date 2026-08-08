# Preserve and restore the local Bot Artifact set

Status: ready-for-agent

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

- [ ] The local store retains frozen source bundles, Bot Artifact Manifests, validation reports, and an indexed set of selected images.
- [ ] Multiple selected images can be exported together into one durable Docker image archive with an integrity-protected index.
- [ ] Shared layers are preserved according to Docker archive behavior rather than intentionally duplicated once per Team.
- [ ] Archive paths, local tags, and Docker cache locations remain operational references outside canonical Bot Artifact identity.
- [ ] If an indexed image is absent from the active engine, the resolver loads the verified archive and re-verifies the exact image digest and platform.
- [ ] Corrupt archives, corrupt indices, missing reports, missing images, wrong platforms, and digest mismatches fail closed with actionable integrity diagnostics.
- [ ] Restoration never triggers a rebuild or mutable-tag substitution.
- [ ] Deleting the selected images from the Docker cache and resolving them from the archive restores a launchable artifact with the original authoritative digest.
- [ ] The store is local-first and requires no registry, object store, or network service.

