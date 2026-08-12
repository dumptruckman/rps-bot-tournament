# Offline Organizer Preparation

`rps-prepare` makes one explicit frozen Language Environment catalog, target
platform, execution profile, Bot Artifact store, and Match parallelism ready
before the Tournament. Fast preparation is always the command's only mode; it never
silently chooses a `latest` catalog or profile.

## Fast preparation

```text
rps-prepare \
  --catalog language_environments/catalog-v1/catalog.json \
  --environment python \
  --platform linux/arm64 \
  --profile docker-execution-v1 \
  --artifact-store path/to/prepared-artifact-store \
  --report path/to/preparation-report.json \
  --parallelism 4 \
  --expected-context orbstack \
  --allow-pull
```

`--environment` explicitly selects the catalog environment whose representative
fixture is prepared. `--allow-pull` permits only its already-pinned build-toolchain
and execution-runtime references in
the frozen catalog to be pulled. Without it, a missing pinned runtime is a
retryable preparation failure. Every Bot Artifact build still uses
`docker build --network=none --pull=false`.

The command validates the active context and native server platform before it
builds. It then builds and certifies a representative Bot Artifact for the
selected Language Environment,
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
- the identity and filenames of the installed, network-independent presentation
  assets;
- the exact `rps-doctor` argument array that reproduced the successful check.

Both the artifact-store and report destinations must be absent. Preparation
does not replace either destination, install Docker, change host or engine
settings, prune caches, delete unrelated images, or alter the selected catalog
or profile.

After installing the prepared package, verify the exact installed presentation
resources before disconnecting the event machine:

```text
rps-tournament verify-presentation-assets
```

The command reads HTML, CSS, and JavaScript through Python package resources,
rejects missing, empty, non-UTF-8, or externally hosted assets, and prints their
combined SHA-256 identity. It performs no network request. The same check runs
inside `rps-prepare` and is recorded as `offline_checks.presentation_assets`.

## Failure disposition

Failures are JSON diagnostics with `team_fault: false` and one disposition:

- `retry`: repeat after a transient Docker, build, archive, or cached-input issue;
- `catalog_correction`: restore or correct the frozen organizer catalog first;
- `organizer_intervention`: correct the explicit context, native platform,
  profile, destination, capacity, or other machine configuration first.

No preparation failure is attributed to a Team or changes a competitive result.

## Full Tournament rehearsal

Fast preparation deliberately does not run the sixteen-Team worst-case
Tournament rehearsal. Run that separate, opt-in operation explicitly:

```text
rps-rehearse \
  --teams path/to/sixteen-teams.json \
  --catalog language_environments/catalog-v1/catalog.json \
  --environment python \
  --output path/to/full-rehearsal \
  --tournament-seed 8675309 \
  --profile docker-execution-v1 \
  --parallelism 4 \
  --jobs 4 \
  --expected-context orbstack
```

Use `--rehearsal-evidence` with `rps-doctor` when comparable rehearsal evidence
has been produced for the exact machine, engine, context, catalog, profile,
platform, and parallelism. See [REHEARSAL.md](REHEARSAL.md) for the source
mapping, worst-case strategy requirement, retained evidence, and exit codes.
