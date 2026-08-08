# Prepare an offline-capable organizer machine

Status: ready-for-agent

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

- [ ] Preparation uses an explicit catalog, target platform, execution profile, and artifact-store location and refuses implicit mutable `latest` selections.
- [ ] It may pull already-pinned platform images, build organizer-owned cached layers and practice Bot Artifacts, and populate runner-owned local metadata.
- [ ] It proves that a representative valid Python source can rebuild and validate with external network access unavailable after preparation.
- [ ] It exercises the published isolation profile, readiness handshake, artifact archive, and restore path.
- [ ] The readiness report records machine, Docker context and version, platform, catalog, profile, resource values, parallelism, cached identities, offline checks, and elapsed time.
- [ ] Preparation does not install Docker, change host or engine settings, delete unrelated images, broadly prune caches, or silently change the selected catalog or profile.
- [ ] Failures explain whether preparation can be retried, requires a catalog correction, or requires organizer intervention without attributing a Team fault.
- [ ] Fast preparation is the default and the full worst-case Tournament rehearsal requires an explicit option or separate command.
- [ ] Running doctor after successful preparation reports the prepared configuration consistently.

