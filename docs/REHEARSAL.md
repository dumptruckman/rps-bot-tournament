# Sixteen-Team release rehearsal

`rps-rehearse` is the explicit release-readiness gate for the prepared Tournament
machine. It is distinct from the synthetic capacity benchmarks: it uses sixteen
real local Python source directories, the official ARM64 builder and conformance
suite, the shared durable archive, a reviewed general Tournament plan, the real
container executor, and public Tournament storage and projection seams.

Create a Team source mapping in the same format accepted by `rps-batch-plan`:

```json
{
  "teams": [
    {
      "team_id": "team-01",
      "display_name": "Team 01",
      "source_directory": "/absolute/path/to/team-01"
    }
  ]
}
```

The mapping must contain exactly sixteen valid local directories. To exercise
the worst case, every representative strategy must produce draws against every
other strategy; the verifier requires all 123 Fixtures to consume three Matches
and all 369 Matches to complete 300 scheduled Turns without a Bot Artifact
fault.

Run the rehearsal only after the frozen catalog and pinned runtime have been
prepared:

```text
rps-rehearse \
  --teams path/to/sixteen-teams.json \
  --catalog language_environments/catalog-v1/catalog.json \
  --output path/to/rehearsal-output \
  --tournament-seed 8675309 \
  --profile docker-execution-v1 \
  --parallelism 4 \
  --jobs 4 \
  --expected-context orbstack
```

The output destination must not exist. The command preserves the batch output,
artifact store, draft plan, real Tournament directory, and
`rehearsal-report.json`. After automated validation it prints the exact Team,
source, artifact, runtime, validation, mode, and parallelism evidence and pauses
for explicit organizer approval before sealing. It then removes only
rehearsal-built image references, loads the shared verified archive, and resolves
every exact selected image before Tournament execution.

The `rps-rehearsal-report-v1` report records exact machine, engine, platform,
catalog, profile, resource, parallelism, runtime, validation, and Bot Artifact
identities; timings for each automated phase and the whole run; archive restore;
Competition Records; Operational Telemetry; reconstructed Tournament state;
Scoreboard Projection; and the Tournament Champion or canonical no-champion
completion.

The command verifies that it is running on the documented 16-logical-CPU Apple
M4 Max with 128 GiB memory and records those hardware facts in addition to the
comparable doctor machine identity. The objective is 2,400 seconds. Human time
at the plan approval prompt is excluded; every automated phase from input
validation through final public verification is included. A correct run at or
below the objective exits
zero. A correct run over the objective writes a failed readiness report and
exits 1 only after Tournament completion and verification. Timing is never
written to Competition Records or the Scoreboard Projection. Build, validation,
integrity, isolation, execution, storage, reconstruction, or projection failures
are reported separately as correctness failures and exit 2.

The synthetic 32-Team capacity command remains the correctness-capacity contract
for the supported four-through-thirty-two-Team range; its timings are not Tournament
release evidence.
