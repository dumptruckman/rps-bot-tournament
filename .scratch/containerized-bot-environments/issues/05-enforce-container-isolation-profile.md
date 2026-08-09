# Enforce the versioned container isolation profile

Status: resolved

Blocked by: 04

## What to build

Apply one versioned, prevention-first execution profile to every official Bot
Position and demonstrate the controls through the public single-Match path. The
profile must prevent Bot Artifacts from reaching host, opponent, Docker, or
external-network state while giving each container an equivalent bounded
runtime environment.

All supported languages and both Bot Positions share the same configurable
outer ceilings. Language Environments cannot request exceptions.

## Acceptance criteria

- [x] Every Match container has no external network, no host bind mounts, no Docker socket, and a private network and filesystem namespace.
- [x] The root filesystem is read-only and the only writable location is a bounded private temporary filesystem.
- [x] Containers run as a non-root numeric user with all Linux capabilities dropped, no privilege escalation, and the pinned syscall policy.
- [x] CPU, memory, PID/process, open-file, writable-filesystem, stdout, and stderr limits are applied equivalently to both Bot Positions.
- [x] The visible environment contains only the versioned infrastructure allowlist plus `RPS_PROTOCOL_VERSION`, `RPS_ROUNDS`, and that Bot Artifact's own `RPS_SEED`.
- [x] Bot Artifacts cannot observe opponent identity, Team identity, ranking, language, host paths, arbitrary host variables, or credentials through the supported interface.
- [x] Runtime-visible infrastructure values such as locale, timezone, home, temporary directory, and hostname are fixed or explicitly non-contractual.
- [x] Isolation fixtures prove prevention of network access, host-file reads, root writes, privilege escalation, capability use, Docker access, and resource-limit escape.
- [x] Profile values are represented as one immutable versioned contract that can be configured before Tournament creation but not varied by Team or Bot Position.

## Answer

Added the immutable `docker-execution-v1` contract and sealed its version and
global ceilings into Tournament Manifests and Match-execution requests. The
public single-Match CLI now runs validated image references through the same
container executor with no networking or mounts, read-only storage except for a
bounded private `/tmp`, read-only shared memory, numeric non-root execution,
dropped capabilities, no privilege escalation, a digest-pinned seccomp policy,
fixed namespaces and hostname, and equivalent CPU, memory, PID, open-file, stream,
and filesystem limits for both Bot Positions.

The Python wrapper re-executes before loading Team strategy so inherited image or
host variables cannot cross the supported interface. The bot-visible environment
is limited to the fixed locale/timezone/home/temp values and the three protocol
inputs, and the wrapper compatibility identity is bumped to `python-wrapper-v2`.

Added synthetic public-Match coverage plus an opt-in real ARM64 isolation Bot
Artifact that actively attempts external networking, host and Docker access,
root and shared-memory writes, privilege escalation, capability use, temporary
filesystem overflow, and CPU, memory, PID, and open-file escape. The real public
CLI Match and existing container/host competitive parity integration both pass.
