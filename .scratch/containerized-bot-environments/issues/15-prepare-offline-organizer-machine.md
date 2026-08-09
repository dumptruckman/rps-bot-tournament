# Prepare an offline-capable organizer machine

Status: resolved

Blocked by: 07, 08, 09, 10

## What to build

Give the organizer an explicit, non-destructive preparation command that makes
the selected frozen catalog and execution profile ready before the event. Fast
preparation should pull pinned inputs when allowed, warm organizer-owned layers
and practice Bot Artifacts, prove networkless rebuilding, exercise isolation,
and write a comparable readiness report.

The full sixteen-Team rehearsal remains an explicit separate operation rather
than part of every preparation run.

## Acceptance criteria

- [x] Preparation uses an explicit catalog, target platform, execution profile, and artifact-store location and refuses implicit mutable `latest` selections.
- [x] It may pull already-pinned platform images, build organizer-owned cached layers and practice Bot Artifacts, and populate runner-owned local metadata.
- [x] It proves that a representative valid Python source can rebuild and validate with external network access unavailable after preparation.
- [x] It exercises the published isolation profile, readiness handshake, artifact archive, and restore path.
- [x] The readiness report records machine, Docker context and version, platform, catalog, profile, resource values, parallelism, cached identities, offline checks, and elapsed time.
- [x] Preparation does not install Docker, change host or engine settings, delete unrelated images, broadly prune caches, or silently change the selected catalog or profile.
- [x] Failures explain whether preparation can be retried, requires a catalog correction, or requires organizer intervention without attributing a Team fault.
- [x] Fast preparation is the default and the full worst-case Tournament rehearsal requires an explicit option or separate command.
- [x] Running doctor after successful preparation reports the prepared configuration consistently.

## Answer

Added `rps-prepare`, an explicit fast preparation command that validates the
selected native Docker context, optionally pulls only catalog-pinned runtimes,
performs a networkless representative Python rebuild and certification, and
retains the catalog practice Bot Artifacts. It creates an integrity-checked Bot
Artifact store, removes only its own representative image tag, proves exact
archive restoration, and runs `rps-doctor` against the prepared identities.

The versioned readiness report records the comparable machine, engine, context,
platform, catalog, execution profile and resource values, parallelism, cached
identities, offline checks, store identity, doctor arguments, and elapsed time.
Failures use retry, catalog-correction, or organizer-intervention dispositions
with no Team fault, and every late failure rolls back only the outputs created by
that invocation so the same command remains retriable. The sixteen-Team
worst-case Tournament rehearsal remains the separate explicit
`rps-tournament-capacity continuous` operation.
