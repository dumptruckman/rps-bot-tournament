# Offline Organizer Preparation

`rps-prepare` makes one explicit frozen Language Environment catalog, target
platform, execution profile, Bot Artifact store, and Match parallelism ready
before the Tournament. Fast preparation is always the command's only mode; it never
silently chooses a `latest` catalog or profile.

## Fast preparation

```text
rps-prepare \
  --catalog language_environments/catalog-v1/catalog.json \
  --platform linux/arm64 \
  --profile docker-execution-v1 \
  --artifact-store path/to/prepared-artifact-store \
  --report path/to/preparation-report.json \
  --parallelism 4 \
  --expected-context orbstack \
  --allow-pull
```

`--allow-pull` permits only the already-pinned platform runtime references in
the frozen catalog to be pulled. Without it, a missing pinned runtime is a
retryable preparation failure. Every Bot Artifact build still uses
`docker build --network=none --pull=false`.

The command validates the active context and native server platform before it
builds. It then builds and certifies a representative Python Bot Artifact,
retains the four catalog practice Bot Artifacts, runs the readiness handshake
and published isolation profile, writes a durable artifact archive, removes
only the preparation-owned representative tag, and restores the exact image
from the verified archive. Finally, it runs the read-only doctor checks against
the prepared identities.

The `rps-preparation-report-v1` JSON report records:

- machine, Docker engine, context, and version identities;
- target platform, catalog identity, profile identity and all resource values;
- Match parallelism and elapsed time;
- organizer, practice, representative, validation, and artifact-store identities;
- networkless rebuild, readiness, isolation, archive, and restore results;
- the exact `rps-doctor` argument array that reproduced the successful check.

Both the artifact-store and report destinations must be absent. Preparation
does not replace either destination, install Docker, change host or engine
settings, prune caches, delete unrelated images, or alter the selected catalog
or profile.

## Failure disposition

Failures are JSON diagnostics with `team_fault: false` and one disposition:

- `retry`: repeat after a transient Docker, build, archive, or cached-input issue;
- `catalog_correction`: restore or correct the frozen organizer catalog first;
- `organizer_intervention`: correct the explicit context, native platform,
  profile, destination, capacity, or other machine configuration first.

No preparation failure is attributed to a Team or changes a competitive result.

## Full Tournament rehearsal

Fast preparation deliberately does not run the sixteen-Team worst-case
Tournament benchmark. Run that separate, opt-in operation explicitly:

```text
rps-tournament-capacity continuous --parallelism 4 \
  --directory path/to/full-rehearsal
```

Use `--rehearsal-evidence` with `rps-doctor` when comparable rehearsal evidence
has been produced for the exact machine, engine, context, catalog, profile,
platform, and parallelism.
