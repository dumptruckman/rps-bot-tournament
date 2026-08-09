# Published Execution Profile

`docker-execution-v1` is the initial organizer-owned execution profile. Its
canonical values live in `rps_runner.execution_profile`; the profile identity is
the version plus the SHA-256 digest of those values. Certification, single-Match
defaults, Tournament defaults, and container startup/shutdown all consume that
one definition.

The published initial identity is
`docker-execution-v1@sha256:54b69b7eae0b15191a13b2b14fcc75c4537358b971b8f84a65731589b8ad3bb1`.

## Global defaults

The same outer ceilings apply to both Bot Positions and every Language
Environment. A language may use less, but it cannot receive a larger ceiling.
These values are the calibration basis that a future Language Environment must
pass before it is supported.

| Control | Initial value |
| --- | ---: |
| Concurrent CPU per Bot Artifact | 1,000 ms/second (one CPU) |
| Total CPU per Match | 2,000 ms |
| Memory including swap | 268,435,456 bytes |
| PIDs/threads | 64 |
| Open files | 64 |
| Writable private `/tmp` | 16,777,216 bytes |
| Runtime/readiness startup | 10 seconds |
| Graceful shutdown | 3 seconds |
| First response | 250 ms |
| Later response | 50 ms |
| Total competitive response time | 2,000 ms |
| stdout per response | 4,096 bytes |
| stderr per Match | 65,536 bytes |

Four concurrent Matches is the conservative initial organizer setting. That is
at most eight one-CPU Bot Artifacts, leaving half of the organizer's sixteen
cores for the runner, Docker, and timing stability. A later measured rehearsal
may select another global value before Tournament creation; there is no dynamic
or language-specific scaling.

## Python calibration evidence

The representative probe loads Python, allocates memory, performs a fixed CPU
workload, holds eight additional threads, opens 24 additional files, and writes
1 MiB to its private temporary filesystem. It runs with the published isolation
and resource controls. Before launch it compares the Docker server architecture
to the requested platform and rejects emulation.

On 2026-08-09, the native Linux/ARM64 lane passed using Python 3.13.14 and the
pinned ARM64 runtime digest
`sha256:8c5de2243cba89f49a93e05cacb78e27058bcaa69c148baac127005da03af39e`.
The probe observed 441.366 ms container/runtime startup, 29,687,808 bytes peak
RSS, 53.352 ms fixed-workload CPU time, nine peak threads, 29 peak open files,
one visible PID, and 1,048,576 temporary bytes. The same lane then passed the
real networkless build, image-identity, readiness, protocol, determinism,
isolation, resource, stream, signal, and lifecycle certification suite.

AMD64 evidence is produced by the `Native AMD64 portability` GitHub workflow on
a native `ubuntu-latest` runner. It uses only `linux/amd64`, the pinned digest
`sha256:69e18bd8d831d88e0ef70239dc7771ab7c28bc296ae78ac75cde71e60aa4434f`,
and `github-advisory` certification. The local organizer lane uses only
`linux/arm64` and `organizer-final` certification:

```text
scripts/ratify-native-platform.sh linux/arm64 path/to/evidence
```

Both lanes execute the same source schema, wrapper, entrypoint, build recipe,
protocol fixtures, isolation profile, and conformance suite from the frozen
catalog. This establishes equivalent source compatibility, not identical
artifacts. Each build is single-platform; ARM64 and AMD64 runtime, image, and
validation identities remain distinct. The acceptance path never invokes QEMU,
creates a multi-platform build, produces a combined OCI index, or compares
cross-platform image digests for equality.
