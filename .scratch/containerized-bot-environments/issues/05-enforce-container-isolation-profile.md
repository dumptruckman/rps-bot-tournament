# Enforce the versioned container isolation profile

Status: ready-for-agent

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

- [ ] Every Match container has no external network, no host bind mounts, no Docker socket, and a private network and filesystem namespace.
- [ ] The root filesystem is read-only and the only writable location is a bounded private temporary filesystem.
- [ ] Containers run as a non-root numeric user with all Linux capabilities dropped, no privilege escalation, and the pinned syscall policy.
- [ ] CPU, memory, PID/process, open-file, writable-filesystem, stdout, and stderr limits are applied equivalently to both Bot Positions.
- [ ] The visible environment contains only the versioned infrastructure allowlist plus `RPS_PROTOCOL_VERSION`, `RPS_ROUNDS`, and that Bot Artifact's own `RPS_SEED`.
- [ ] Bot Artifacts cannot observe opponent identity, Team identity, ranking, language, host paths, arbitrary host variables, or credentials through the supported interface.
- [ ] Runtime-visible infrastructure values such as locale, timezone, home, temporary directory, and hostname are fixed or explicitly non-contractual.
- [ ] Isolation fixtures prove prevention of network access, host-file reads, root writes, privilege escalation, capability use, Docker access, and resource-limit escape.
- [ ] Profile values are represented as one immutable versioned contract that can be configured before Tournament creation but not varied by Team or Bot Position.

