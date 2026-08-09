# Tournament Runner Capacity Benchmarks

Use these opt-in commands to verify a host before a Tournament or to compare
capacity after a runner or storage change. They use `TournamentRunner` with a
controllable conforming Match executor; no Bot Artifact subprocesses are
started. These commands preserve the correctness contract through 32 Teams but
are not the real sixteen-Team release rehearsal; see
[REHEARSAL.md](REHEARSAL.md) for that operation.

## Prerequisites

From a clean checkout, create the repository virtual environment and install the
package in editable mode:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

No benchmark-only dependency is required. The suite supports Python 3.9 and
newer and uses only the standard library plus this package.

## Step Mode preflight

Run one conforming 300-Round Match through the public Step Mode operation,
terminal Competition Record commit, Tournament state fold, and Scoreboard
Projection update:

```text
.venv/bin/python -m rps_runner.tournament.capacity step
```

The objective is three seconds. This command is suitable for a quick preflight.

## Maximum Continuous Mode benchmark

Run the full maximum-capacity workload:

```text
.venv/bin/python -m rps_runner.tournament.capacity continuous --parallelism 16
```

The deterministic draw executor forces every Series to consume all three
Matches. The command verifies 32 Teams, 496 qualifying Fixtures, three standard
playoff Fixtures, 1,497 terminal Matches, 449,100 completed Round entries,
canonical Tournament completion, a Tournament Champion, reconstructed state,
and the final Scoreboard Projection. The objective is twenty minutes.

The default commands create and remove a temporary Tournament store. To retain
the canonical artifacts for inspection, pass an empty or new directory:

```text
.venv/bin/python -m rps_runner.tournament.capacity continuous \
  --parallelism 16 \
  --directory results/capacity-preflight
```

Do not reuse a directory containing a sealed Tournament.

## Interpreting output

Each successful command prints the benchmark name, exact workload, elapsed
duration, objective, and either `MET` or `EXCEEDED (non-binding)`. Wall-clock
duration is Operational Telemetry: it is not written into Competition Records
and does not affect Tournament state, results, pause behavior, or the Tournament
Champion.

An objective overrun exits successfully. It is a planning and regression signal,
not a Tournament fault. A genuine creation, execution, storage-integrity,
reconstruction, count, completion, or Scoreboard Projection failure still
terminates the command unsuccessfully.
