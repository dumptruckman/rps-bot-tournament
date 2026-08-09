# Container Isolation Profile

Official Bot Artifacts run under `docker-execution-v1`. The version and its
global ceilings are sealed before Tournament creation and copied unchanged to
both Bot Positions for every Match. Language Environments and Teams cannot
override the profile.

## Fixed contract

- Docker networking is `none`; containers receive no mounts, Docker socket,
  host devices, host environment, or added capabilities.
- The root filesystem and `/dev/shm` are read-only. `/tmp` is the only writable
  location and is a private, size-bounded `tmpfs` mounted with
  `noexec,nosuid,nodev` for numeric user and group `65532`.
- Containers use a fixed `rps-bot` hostname and private IPC, PID, mount,
  network, UTS, and cgroup namespaces. PID, mount, network, and UTS privacy are
  Docker's non-host defaults; the profile never selects a host namespace.
- All Linux capabilities are dropped, `no-new-privileges` is enabled, and the
  packaged seccomp policy is verified against its profile-pinned SHA-256 digest
  before each container is created.
- Memory and swap share one hard byte limit. PID and open-file limits are hard
  limits. `cpu_quota_millis_per_second` is translated to Docker's CPU-count
  throttle (`1000` means one CPU); `cpu_limit_ms` is also applied as a hard
  total CPU-time ulimit. Configured totals must use exact whole seconds because
  Linux does not provide a millisecond-granularity hard CPU-time ulimit.
- stdout and stderr remain bounded by the Match Runner's existing per-Bot Artifact
  protocol stream limits.

## Bot-visible environment

The organizer-owned wrapper re-executes itself with exactly these fixed
infrastructure values before loading Team strategy:

| Variable | Value |
| --- | --- |
| `LANG` | `C.UTF-8` |
| `LC_ALL` | `C.UTF-8` |
| `TZ` | `UTC` |
| `HOME` | `/tmp` |
| `TMPDIR` | `/tmp` |

It also supplies `RPS_PROTOCOL_VERSION`, `RPS_ROUNDS`, and only that Bot
Artifact's `RPS_SEED`. Container IDs, engine details, kernel/cgroup presentation,
and other runtime implementation details are explicitly non-contractual and are
not competitive inputs.

## Initial global ceilings

The normative values and calibration evidence are published in
[`EXECUTION_PROFILE.md`](EXECUTION_PROFILE.md).

| Ceiling | Initial value |
| --- | ---: |
| Concurrent CPU | 1,000 ms per second (one CPU) |
| Total CPU | 2,000 ms |
| Memory including swap | 268,435,456 bytes |
| PIDs/threads | 64 |
| Open files | 64 |
| Writable `/tmp` | 16,777,216 bytes |
| Runtime/readiness startup | 10 seconds |
| Graceful shutdown | 3 seconds |
| First response | 250 ms |
| Later response | 50 ms |
| Total competitive response time | 2,000 ms |
| stdout per response | 4,096 bytes |
| stderr per Match | 65,536 bytes |

Organizers may configure these outer ceilings only before Tournament creation.
Changing a fixed control requires a new execution-profile version.

## Runtime faults and lifecycle

The executor labels every container with `rps.runner.owner=rps-tournament`, the
canonical `<Tournament ID>/<Match ID>` Match identity, the absolute
`<Tournament ID>/<Match ID>/attempt-<number>` Match Attempt identity, and its Bot
Position. Before an attempt starts, stale cleanup selects containers by both the
runner-owner and canonical Match labels, rejects unsafe container identities,
and removes those containers individually. This clears interrupted earlier
attempt ordinals without inspecting or pruning containers owned by another
Match or unrelated Docker state.

On Match completion or a terminal fault, the runner closes both input streams,
starts graceful stops concurrently, force-kills a survivor after the bounded
grace period, reaps Docker helper processes, captures final state, and attempts
to remove both containers. Cleanup errors are retained in Operational Telemetry.
They do not replace an already determined competitive outcome.

Protocol errors, response timeouts, premature output, stdout overflow, and an
unexpected Bot Artifact process exit use the existing competitive fault kinds. Docker's
explicit `OOMKilled` state is attributable OOM evidence. A trusted runtime
monitor can report the other published resource breaches through the reserved
`RPS_RESOURCE_EVIDENCE_V1:` state-error control signal with one of
`pid_exhaustion`, `open_file_exhaustion`, or `filesystem_exhaustion`. Generic
Docker errors, including ambiguous resource text that could describe host
exhaustion, are Infrastructure Failures.

Prevention remains the primary security mechanism. Only the trusted runtime
signal `RPS_SECURITY_EVIDENCE_V1:<evidence>` can produce a suspected Security
Violation. The executor requires the evidence to be attributable to a Bot
Position, retains the raw signal only in Operational Telemetry, and exposes an
opaque SHA-256 evidence link through the existing ruling seam. Ordinary denied
operations do not imply a Security Violation.

Container IDs and names, labels, exact Docker commands, engine and host facts,
timestamps, startup and cleanup durations, readiness observations, Bot Artifact stderr,
resource observations, exit metadata, OOM state, and raw errors are Operational
Telemetry only. Readiness markers are removed before Bot Artifact stderr accounting and
do not consume its allowance.
