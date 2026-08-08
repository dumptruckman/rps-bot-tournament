# Prove portability and ratify the execution profile

Status: ready-for-agent

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

- [ ] The Python base environment is pinned by platform-specific immutable digest for both `linux/arm64` and `linux/amd64`.
- [ ] Native ARM64 and native Linux/AMD64 runs exercise real build, readiness, protocol, isolation, resource, stream, signal, image-identity, and lifecycle behavior.
- [ ] Local organizer builds target only `linux/arm64`, while GitHub advisory validation targets only `linux/amd64`.
- [ ] Platform-specific source compatibility rules are equivalent even though image and runtime digests remain distinct.
- [ ] Representative probes measure Python startup, memory, CPU, PID/thread, open-file, and temporary-filesystem needs.
- [ ] CPU, memory, process, open-file, startup, shutdown, writable-temporary-filesystem, and output defaults are documented as the published initial profile.
- [ ] The same outer ceilings apply to both Bot Positions and form the calibration basis for later Language Environments.
- [ ] The profile gives each Bot Artifact no more than one CPU and documents four concurrent Matches as the conservative initial organizer setting.
- [ ] No acceptance path depends on QEMU, a multi-platform image build, an OCI index containing both targets, or identical cross-platform image digests.

