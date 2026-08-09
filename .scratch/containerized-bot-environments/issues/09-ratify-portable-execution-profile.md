# Prove portability and ratify the execution profile

Status: resolved

Blocked by: 06

## What to build

Prove that the generic builder and container executor work with native
Linux/ARM64 and ordinary Linux/AMD64 Docker without OrbStack- or macOS-specific
behavior. Use measured Python runtime probes to replace the currently
unenforced placeholder limits with an explicit initial execution profile.

Each platform build remains a distinct single-platform Bot Artifact. The work
must not introduce multi-platform image builds or imply equal image digests
across architectures.

## Acceptance criteria

- [x] The Python base environment is pinned by platform-specific immutable digest for both `linux/arm64` and `linux/amd64`.
- [x] Native ARM64 and native Linux/AMD64 runs exercise real build, readiness, protocol, isolation, resource, stream, signal, image-identity, and lifecycle behavior.
- [x] Local organizer builds target only `linux/arm64`, while GitHub advisory validation targets only `linux/amd64`.
- [x] Platform-specific source compatibility rules are equivalent even though image and runtime digests remain distinct.
- [x] Representative probes measure Python startup, memory, CPU, PID/thread, open-file, and temporary-filesystem needs.
- [x] CPU, memory, process, open-file, startup, shutdown, writable-temporary-filesystem, and output defaults are documented as the published initial profile.
- [x] The same outer ceilings apply to both Bot Positions and form the calibration basis for later Language Environments.
- [x] The profile gives each Bot Artifact no more than one CPU and documents four concurrent Matches as the conservative initial organizer setting.
- [x] No acceptance path depends on QEMU, a multi-platform image build, an OCI index containing both targets, or identical cross-platform image digests.

## Answer

Published `docker-execution-v1` as one code-owned, content-addressed definition
consumed by Match, Tournament, certification, startup, and shutdown defaults.
The normative profile document records all ceilings, one-CPU Bot Artifacts,
four-Match initial parallelism, and measured native ARM64 Python evidence.

Added a native-only Python probe and a complete platform-ratification script.
The probe rejects a Docker server architecture mismatch before execution. The
script runs the real networkless builder and complete certification suite, then
records the profile probe, manifest, and validation report. The local path maps
ARM64 to canonical organizer-final validation; the GitHub workflow maps only
AMD64 to advisory validation. Both consume the same frozen compatibility assets
while preserving distinct platform runtime and Bot Artifact identities.

The native ARM64 run exposed and fixed two stale certification expectations:
successful null fault slots were treated as failures, and diagnostic fixtures
expected obsolete protocol and OOM fault names. After correction, the full
ARM64 build, readiness, protocol, isolation, resource, stream, signal,
image-identity, and lifecycle lane passed. The AMD64 workflow provides the same
real lane on GitHub's native Linux/AMD64 runner without QEMU or multi-platform
images.
