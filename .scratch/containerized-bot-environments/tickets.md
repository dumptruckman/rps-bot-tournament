# Tickets: Post-container Bot Artifact follow-ups

Follow-up work to preserve the event workflow, language-expansion, and remote-execution decisions that are intentionally outside the initial Python containerized Bot Environment implementation.

Work the **frontier**: any ticket whose blockers are all done. The “Containerized Bot Environments implementation” blocker refers to the parent effort that will be specified separately in this directory.

## Create the companion Team submission repository

**What to build:** Give Teams one shared repository containing the supported source templates and thin validation automation, while keeping source acquisition manual for the organizer. The repository starts with Python, permits one branch per Team under the event honor code, and reports which commits have passed the official validation contract.

**Blocked by:** Containerized Bot Environments implementation.

- [ ] The repository contains the organizer-owned Python template, wrapper, build recipe, and participant smoke-test entry point.
- [ ] A pinned release of the validator owned by the Tournament repository is invoked rather than duplicating validation logic.
- [ ] GitHub Actions builds and validates one `linux/amd64` image per commit without producing a multi-platform Bot Artifact image.
- [ ] Successful validation identifies the exact source commit, source digest, recipe version, base-image digest, platform, and validation result.
- [ ] The documented cutoff rule selects the latest successfully validated commit before the deadline.
- [ ] The workflow documents manual clone/pull/export into organizer-controlled local submission directories; automated submission pulling is explicitly deferred.

## Calibrate and ratify the shared resource profile

**What to build:** Replace placeholder resource ceilings with one fair, evidence-based profile that allows intended native, interpreted, JVM, .NET, Node, and Dart runtimes to start and execute while bounding untrusted Bot Artifacts consistently.

**Blocked by:** Containerized Bot Environments implementation.

- [ ] Representative runtime probes measure startup, memory, CPU, PID/thread, open-file, and temporary-filesystem requirements.
- [ ] CPU, memory, process, open-file, startup-timeout, and writable-temporary-filesystem defaults are adjusted from the currently unenforced placeholders where evidence requires it.
- [ ] Every language receives the same outer ceilings; no language-specific resource exception is introduced.
- [ ] The organizer may tune the global values before Tournament creation, but the selected values and execution-profile version are immutable after the Tournament Manifest is sealed.
- [ ] Conformance tests prove that limits apply equivalently to both Bot Positions and that limit breaches receive the intended competitive or Infrastructure Failure classification.
- [ ] The accepted values and benchmark evidence are recorded in the normative documentation.

## Verify native ARM64 execution against AMD64 validation

**What to build:** Make the GitHub Actions confidence check useful for the native local Tournament without pretending that architecture-specific images are identical. Each organizer-owned base environment is available for both platforms, while each build targets only its native platform.

**Blocked by:** Create the companion Team submission repository; Calibrate and ratify the shared resource profile.

- [ ] The Python base environment is pinned and available for both `linux/arm64` and `linux/amd64`.
- [ ] Local organizer builds and Tournament execution use a single-platform `linux/arm64` image.
- [ ] GitHub Actions validation uses a single-platform `linux/amd64` image.
- [ ] The local ARM64 rebuild remains the canonical Bot Artifact used by the Tournament; the AMD64 result is explicitly a source-compatibility signal.
- [ ] Cross-platform conformance fixtures detect wrapper, protocol, seeded-random, and entrypoint behavior that would make the AMD64 signal misleading.
- [ ] No acceptance criterion requires building or publishing a multi-platform Bot Artifact image.

## Expand the language-environment catalog

**What to build:** Add organizer-owned language environments through the common template, wrapper, readiness, build, validation, and execution contracts without changing the Tournament Runner for each language.

**Blocked by:** Verify native ARM64 execution against AMD64 validation.

- [ ] Create a small child ticket before adding each language so every environment can land and be verified independently.
- [ ] Track Rust, C#, Java, Clojure, JavaScript/TypeScript, Ruby, Go, Dart, and Kotlin as the initial expansion backlog.
- [ ] Each environment supplies ARM64 and AMD64 base-image options, but builds one platform at a time.
- [ ] Each environment uses only its standard library and organizer-pinned template contents; build-time package downloads remain prohibited.
- [ ] Each organizer-owned wrapper implements the readiness handshake, protocol version 1, and its versioned Seed Adapter.
- [ ] Each environment passes the shared build, smoke-Match, determinism, isolation, and resource-profile conformance suite before being advertised as supported.

## Rehearse and document the 16-Team local event workflow

**What to build:** Give the organizer a timed, recoverable runbook for turning manually acquired submissions into an official Tournament on the local ARM64 machine within the event window.

**Blocked by:** Create the companion Team submission repository; Calibrate and ratify the shared resource profile; Containerized Bot Environments implementation.

- [ ] The rehearsal covers manual source acquisition, cutoff snapshotting, canonical ARM64 batch builds, validation, durable Bot Artifact export, Tournament creation, execution, inspection, and resumption.
- [ ] Required base images and tools are preflighted and cached before the event so the official workflow does not depend on build-time network downloads.
- [ ] A worst-case 16-Team build plus Tournament run is measured against the 40-minute operational objective.
- [ ] The 40-minute result is operational reporting rather than a competitive rule, and support for up to 32 Teams remains correctness-only capacity.
- [ ] The runbook includes failed-build handling, the latest-green-commit rule, disk-space checks, Docker/OrbStack recovery, and restoration from the local Bot Artifact archive.
- [ ] A no-GitHub fallback explains how manually delivered directories or ZIP archives enter the same validator.

## Investigate Tournament execution through GitHub Actions

**What to build:** Produce a decision-ready design for optionally executing an already-built Tournament through GitHub Actions after the local workflow is proven, without weakening Bot Artifact identity, isolation, Competition Record authority, or recovery behavior.

**Blocked by:** Rehearse and document the 16-Team local event workflow.

- [ ] Compare hosted and self-hosted runner architecture, Docker capability, capacity, time, cost, and untrusted-code risks.
- [ ] Define how canonical ARM64 or future platform-specific Bot Artifacts, the Tournament Manifest, Competition Records, Operational Telemetry, and the Scoreboard Projection would enter and leave an ephemeral runner.
- [ ] Preserve the same container execution profile and Match-execution boundary used locally.
- [ ] Identify required changes, unresolved risks, and a migration path without implementing remote Tournament execution in this ticket.
- [ ] Keep GitHub Actions Tournament execution optional; local execution remains the primary supported operation.
