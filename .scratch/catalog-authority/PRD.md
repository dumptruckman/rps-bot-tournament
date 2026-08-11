# Runner-owned Language Environment Catalog

Status: ready-for-agent

Implementation status: not started

## Purpose

Make this repository the sole authority for the Language Environment Catalog
and every organizer-owned asset needed to validate, build, certify, and execute
Bot Artifacts. Participant-facing Team Templates remain exclusively in the
companion repository and consume one exact published catalog identity.

## Repository seam

This repository publishes a small immutable interface: Runner commit, package
version, catalog path and identity, bundled-history identity, and catalog asset
identities. It never fetches, imports, or validates the Team Template repository.

The companion repository pins that interface, materializes the exact Runner
checkout, and proves its Team Template remains compatible.

## Delivery order

1. Define the catalog authority and compatibility interface.
2. Publish an immutable Runner-owned catalog release.
3. Remove participant-template coupling from Runner demos and documentation.
4. Prove catalog operation without the Team Template repository.

Tickets 02 and 03 can proceed independently after ticket 01. Ticket 04
integrates them and blocks the companion repository's final cutover proof.

## Completion

This effort is complete when a clean Runner clone can publish and verify the
frozen catalog offline, the Runner contains no participant-facing Team Template,
and deleting the companion repository cannot affect preparation, Final
Validation, Tournament execution, rehearsal, or presentation.

## Companion effort

The consuming work is tracked in
`rps-bot-templates/.scratch/catalog-consumer/`.
