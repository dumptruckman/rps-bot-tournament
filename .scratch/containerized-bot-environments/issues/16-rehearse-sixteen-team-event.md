# Rehearse the complete sixteen-Team event workflow

Status: resolved

Blocked by: 14, 15

## What to build

Exercise the real event path on the prepared organizer machine from sixteen
representative local Python source directories through official build,
validation, preservation, plan review, containerized Tournament execution,
storage reconstruction, and Scoreboard Projection. Use the real builder,
artifact store, public commands, container executor, 300 scheduled Turns, and
worst-case three-Match Series behavior.

The rehearsal is a release-readiness gate measured against forty minutes on the
target sixteen-core M4 Max. Timing overrun must fail only the readiness report;
it can never become competitive state or stop a real Tournament.

## Acceptance criteria

- [x] The explicit rehearsal begins from sixteen valid local Team source directories and the frozen prepared catalog without including human acquisition time.
- [x] All sixteen sources are built and authoritatively validated as native ARM64 Bot Artifacts using the real builder and conformance suite.
- [x] Selected images are exported to the durable shared archive, removed or resolved as needed, and verified through the general Tournament plan.
- [x] The plan creates and completes a real Continuous Mode Tournament with four concurrent Matches, 300 scheduled Turns per Match, and worst-case three-Match Series fixtures.
- [x] Competition Records, Operational Telemetry, Scoreboard Projection, Tournament state reconstruction, and Tournament Champion or canonical no-champion completion are verified through public seams.
- [x] The complete automated work after valid source directories are supplied finishes within forty minutes on the documented target machine and prepared configuration.
- [x] The report records exact machine, engine, platform, catalog, profile, resource values, parallelism, artifact identities, phase timings, total timing, and objective result.
- [x] A timing overrun fails release-readiness reporting without creating a Bot Artifact fault, Infrastructure Failure, pause, abort, Competition Record, or Scoreboard change in actual Tournament execution.
- [x] Genuine correctness, integrity, isolation, or execution failures remain distinguishable from a timing-objective overrun.
- [x] Support for up to thirty-two Teams remains a correctness capacity contract even though the forty-minute objective is calibrated for sixteen Teams.

## Answer

Added the explicit `rps-rehearse` release gate. It consumes exactly sixteen
local Python Team source directories, uses the public batch-plan and Tournament
commands, requires organizer review before sealing, proves shared archive
restoration, and verifies Competition Records, Operational Telemetry,
reconstructed state, Scoreboard Projection, worst-case Series, and canonical
Tournament completion. Timing-only failure exits separately after competitive
execution and never enters Tournament state.

The real target-machine run completed successfully on the 16-logical-CPU Apple
M4 Max with 128 GiB memory and OrbStack `linux/arm64`. All sixteen distinct Bot
Artifacts passed authoritative certification; the 123 Fixtures consumed 369
real container Matches of 300 Turns each; `team-15` became Tournament Champion.
Total automated time was 829.721665 seconds against the 2,400-second objective.
The complete comparable report is retained at
`../evidence/16-rehearsal-report.json`.

The rehearsal uncovered and fixed two release-blocking parallel-certification
defects: shared conformance Match ownership caused container collisions, and
resource-exhaustion fixtures interfered with concurrent conformance Matches.
Conformance workspaces now own distinct Match identities, and live conformance
suites execute in uncontended windows while official source builds remain
parallel. The separate synthetic maximum-capacity command continues to verify
the 32-Team correctness contract.
