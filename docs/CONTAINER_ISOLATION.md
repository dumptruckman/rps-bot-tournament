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

| Ceiling | Initial value |
| --- | ---: |
| Concurrent CPU | 1,000 ms per second (one CPU) |
| Total CPU | 2,000 ms |
| Memory including swap | 268,435,456 bytes |
| PIDs/threads | 64 |
| Open files | 64 |
| Writable `/tmp` | 16,777,216 bytes |
| stdout per response | 4,096 bytes |
| stderr per Match | 65,536 bytes |

Organizers may configure these outer ceilings only before Tournament creation.
Changing a fixed control requires a new execution-profile version.
