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

## Event-day process recovery

The release rehearsal launches the public Tournament Runner as a child process,
waits until it has committed a Match, requests a pause at the next Match
boundary, waits for the Runner process to exit, and resumes it in a new process.
The report's `event_day.runner` evidence must show separate process execution,
interruption, resumption, and the observed `running`, `paused`, and `complete`
states. A Runner that completes before interruption does not satisfy the gate.
While that first Runner process is active, rehearsal starts presentation, reads
the live view, stops presentation, starts it again, and reads the live view a
second time. Both presentation processes must exit without the Runner exiting.

After completion, rehearsal launches the presentation on an ephemeral loopback
port, reads `/api/live`, stops that process, launches a new presentation process,
and reads a verified completed-Match replay. Before and after those reads it
captures every Competition Record byte, `scoreboard.json`, reconstructed
Tournament state, and the Tournament Champion. All four equality checks under
`event_day.presentation` must be true. Presentation failure never requires
stopping the Runner: restart only this command against the same directory:

```text
rps-tournament present --directory path/to/rehearsal-output/tournament --port 0
```

Rehearsal also creates a non-authoritative sibling directory named
`presentation-event-scenarios`. It presents controlled copies of the final
projection as running qualification, running Playoff Phase, pending organizer
review, and aborted states. This exercises phase transition, pending review, and
abort without modifying or inventing Competition Records in the real Tournament
directory. The controlled copies are presentation inputs only; the real
Tournament's completion and Champion remain authoritative.

Runner recovery uses the exact sealed inputs printed by the rehearsal. Request a
boundary pause from a second terminal with `rps-tournament plan ...
--request-pause`; after the running process exits and the projection says
`paused`, use the same command inputs with `--resume`. Never delete `run.lock`,
edit a Competition Record, or replace `scoreboard.json` by hand.

The automated browser suite supplies the running, phase-transition, pending
review, completion, abort, responsive, accessibility, hostile-string, and
connectivity scenarios. Before release, repeat the Firefox and Safari manual
matrix in [PRESENTATION.md](PRESENTATION.md) and retain it beside
`rehearsal-report.json`. Use the checked-in
[browser release record](PRESENTATION_BROWSER_SMOKE_CHECK.md).
