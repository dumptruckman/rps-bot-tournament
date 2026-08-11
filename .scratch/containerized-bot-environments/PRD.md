# Containerized Bot Build and Execution

Status: ready-for-agent

Implementation status: complete

## Problem Statement

The Tournament Runner can execute a complete deterministic Tournament, but its
real Match executor still starts Bot Artifacts as ordinary host processes. The
sealed Match-execution request already carries CPU, memory, process, filesystem,
network, timing, and output limits, yet the local executor enforces only protocol
timing and stream limits. As a result, organizer machines must have each language
runtime installed, Bot Artifacts can see more of the host than intended, and the
published container security contract is not implemented.

This is also an event-operations problem. Teams have roughly forty minutes to
implement their strategies during a two-hour event. After submissions close,
the organizer has roughly another forty minutes to collect the selected source,
build and validate the official Bot Artifacts, preserve them, and run the
Tournament. A build failure discovered only after the cutoff could prevent a Team
from competing, while a slow or host-specific build pipeline could prevent the
Tournament from finishing before winners must be announced.

Teams need templates and feedback that let them know their source will build and
obey protocol version 1 without requiring them to design containers or understand
Tournament infrastructure. The organizer needs one predictable local workflow
that can consume manually acquired source directories, build immutable images,
produce a reviewable roster, and run the existing Tournament unchanged through a
Docker-compatible engine such as OrbStack.

The first milestone needs a complete Python path while leaving a clean extension
contract for Rust, C#, Java, Clojure, JavaScript/TypeScript, Ruby, Go, Dart, and
Kotlin. It must prioritize local ARM64 execution on the organizer's Apple Silicon
machine, retain ordinary Linux/AMD64 compatibility for validation and future
GitHub Actions execution, and avoid committing the project to multi-platform
builds, a registry, automated source collection, or a heavy security-forensics
stack.

## Solution

Provide a language-neutral source-to-Tournament container pipeline centered on
the existing Match-execution boundary. An organizer-owned Language Environment
defines the Team-editable source schema, template, wrapper, readiness contract,
networkless build recipe, pinned platform runtimes, fixed entrypoint, and
conformance cases for one supported language. The first required Language
Environment is Python. Additional languages plug into the same contract without
changing Tournament scheduling, scoring, protocol handling, or container
execution logic.

Teams work in a separate shared template/submission repository and may use a
one-command local container smoke test when Docker is available. A thin GitHub
Actions workflow in that repository invokes the same versioned conformance suite
on Linux/AMD64 and marks successful commits as eligible submission candidates.
At the cutoff, the organizer manually obtains the selected source directories,
uses the frozen Language Environment catalog to rebuild and validate them on
Linux/ARM64, and treats only those local images as canonical Bot Artifacts.

The organizer builder produces exact platform-specific image identities, frozen
source bundles, Bot Artifact Manifests, validation reports, and a human-reviewable
Tournament plan. It exports all selected images to a durable local Docker image
archive so Tournament creation and resumption do not depend on an unpruned image
cache or a remote registry. Tournament creation seals the selected image,
runtime, platform, wrapper, build-recipe, entrypoint, validation, execution
profile, and resource identities.

For every Match, the host Tournament Runner launches each Bot Artifact in its own
fresh container. Both containers use one versioned, prevention-first execution
profile with no network, no host mounts, a read-only root filesystem, a bounded
writable temporary filesystem, a non-root user, no Linux capabilities, no
privilege escalation, a pinned syscall policy, a minimal environment, and
equivalent global resource limits. Organizer-owned wrappers signal readiness
before Turn 0 so container and runtime startup remain outside competitive
response-time budgets. The existing Match Runner remains authoritative for
protocol version 1, timing, move validation, Round scoring, and competitive
outcomes.

The public single-Match and Tournament workflows both use the same container
executor. Direct host-process execution remains available only as an explicitly
insecure development and test mode. Read-only diagnosis, machine preparation,
and an explicit full rehearsal make the organizer workflow offline-capable after
submissions close. On the organizer's sixteen-core, 128-GB Apple Silicon machine,
the initial operating profile gives each Bot Artifact at most one CPU and runs
four Matches concurrently. A measured sixteen-Team build, validation, archive,
and worst-case Tournament must complete within forty minutes as a release
readiness gate, not as a competitive timeout.

## User Stories

1. As a Team, I want to begin from an organizer-owned Python template, so that I
   can spend the coding period on strategy rather than infrastructure.
2. As a Team, I want to implement the same `choose_move` strategy contract used
   by the current Python wrapper, so that containerization does not change the
   participant API.
3. As a Team, I want to add multiple source and accessory files within a
   controlled submission directory, so that my strategy is not limited to one
   physical file.
4. As a Team, I want the Python Language Environment to define which source and
   resource files I may change, so that I cannot accidentally alter organizer
   infrastructure.
5. As a Team, I want organizer-owned wrappers, build recipes, entrypoints, and
   dependency definitions injected from a frozen catalog, so that branch edits
   cannot silently change the official environment.
6. As a Team, I want builds limited to the standard library and dependencies
   already pinned by the organizer, so that package downloads cannot fail after
   submissions close.
7. As a Team, I want a one-command local build and smoke test when Docker is
   installed, so that I can verify my Bot Artifact throughout development.
8. As a Team without Docker, I want the same validation available through
   GitHub Actions, so that participant-side Docker remains optional.
9. As a Team, I want GitHub validation to run automatically on new branch
   commits, so that I receive compatibility feedback before the cutoff.
10. As a Team, I want actionable build, wrapper-readiness, protocol, determinism,
    limit, and smoke-Match diagnostics, so that I can correct failures quickly.
11. As a Team, I want validation to measure compatibility rather than strategy
    quality, so that losing to a practice Bot Artifact never rejects my source.
12. As a Team, I want deterministic practice Bot Artifacts available through the
    same execution path, so that smoke testing represents official Matches.
13. As a Team, I want the latest pre-cutoff GitHub-green commit to be eligible
    for official selection, so that a later broken commit does not erase all
    evidence of a working submission.
14. As a Team, I want the organizer to perform the final build from my selected
    source rather than trust an image I provide, so that image sharing is not a
    participant responsibility.
15. As a Team, I want a rare architecture-specific compatibility failure to
    permit a supervised repair, so that an infrastructure mismatch does not
    unnecessarily exclude me.
16. As a Team, I want any post-cutoff repair restricted to compatibility and
    retained as a diff, so that the repair window cannot become extra strategy
    development time.
17. As a Team, I want only my protocol version, scheduled Turns, and bot-visible
    seed exposed as competitive inputs, so that containers do not reveal an
    opponent or hidden Tournament data.
18. As a Team, I want equivalent container timing and resources for both Bot
    Positions, so that infrastructure does not create a competitive advantage.
19. As a Team, I want container and language-runtime startup excluded from my
    first-move allowance, so that a heavier conforming runtime is not charged for
    organizer infrastructure work.
20. As a Team, I want one fresh container for every Match, so that Bot Artifact
    state cannot persist between Matches.
21. As a Team, I want my exact official image reused for retries and Tournament
    resumption, so that a rebuild cannot change competitive behavior.
22. As a Team, I want resource breaches attributable to my Bot Artifact treated
    consistently as Match faults, so that container enforcement follows the
    published rules.
23. As a Team, I want Docker daemon and host failures treated as Infrastructure
    Failures, so that I do not forfeit because of organizer infrastructure.
24. As a Team, I want blocked prohibited access to be prevention-first, so that
    the event does not depend on invasive monitoring or unreliable attribution.
25. As an organizer, I want source acquisition separate from building, so that I
    can use shared Git branches, ZIP files, email, or another manual transport.
26. As an organizer, I want the official builder to accept already-present local
    source directories, so that it does not need GitHub credentials or branch
    automation.
27. As an organizer, I want to freeze one event Language Environment catalog
    before coding begins, so that Team and organizer validation use known inputs.
28. As an organizer, I want the same catalog to name pinned ARM64 and AMD64 base
    images, so that each workflow can build natively without a multi-platform
    image build.
29. As an organizer, I want GitHub/AMD64 validation treated as advisory
    eligibility and local/ARM64 validation treated as final authority, so that
    the Bot Artifact used in the Tournament is actually tested.
30. As an organizer, I want official builds to use no network after event
    preparation, so that registry or package-service availability cannot delay
    the Tournament.
31. As an organizer, I want submission contexts checked for unexpected paths,
    symlinks, counts, and sizes, so that malformed source cannot escape its
    controlled build context.
32. As an organizer, I want untrusted source excluded from Dockerfiles, wrappers,
    entrypoints, dependency manifests, and build targets, so that Teams cannot
    customize infrastructure.
33. As an organizer, I want source bundles and images built concurrently where
    safe, so that submission count does not create unnecessary serial delay.
34. As an organizer, I want every successful build to produce a complete Bot
    Artifact Manifest and validation report, so that acceptance is inspectable.
35. As an organizer, I want all selected images exported into a durable local
    archive, so that Docker cache pruning cannot make a Tournament irrecoverable.
36. As an organizer, I want shared image layers retained efficiently, so that
    archiving up to sixteen Python Bot Artifacts does not duplicate the entire
    runtime for every Team.
37. As an organizer, I want missing selected images loaded automatically from the
    verified archive, so that resumption requires no manual image reconstruction.
38. As an organizer, I want a draft JSON Tournament plan generated from validated
    Bot Artifacts, so that roster construction is reviewable rather than a long
    sequence of command flags.
39. As an organizer, I want to review Team IDs, Team Display Names, source
    identities, artifact identities, Tournament Seed, mode, parallelism, and the
    execution profile before sealing, so that mistakes are caught before play.
40. As an organizer, I want Tournament creation to reject an unvalidated,
    missing, wrong-platform, or digest-mismatched Bot Artifact, so that every
    roster entry resolves to the intended executable.
41. As an organizer, I want the current four-Team demo replaced or complemented
    by a general artifact-plan workflow, so that the official event is not tied
    to bundled Bot Artifacts.
42. As an organizer, I want both the single-Match and Tournament CLIs to execute
    validated image references, so that practice and official operation share
    one path.
43. As an organizer, I want the host Tournament Runner to control containers
    directly, so that I do not need Docker-socket nesting or a containerized
    organizer stack.
44. As an organizer using OrbStack, I want tooling to honor the active Docker
    context, so that a Docker-compatible local engine satisfies the prerequisite.
45. As an organizer, I want a read-only doctor command, so that I can diagnose
    engine, platform, capacity, disk, catalog, and profile readiness safely.
46. As an organizer, I want a preparation command, so that pinned images,
    organizer layers, practice Bot Artifacts, caches, offline behavior, and
    isolation controls are ready before the event.
47. As an organizer, I want preparation to avoid deleting unrelated images or
    changing host settings, so that machine readiness is not destructive.
48. As an organizer, I want the full sixteen-Team rehearsal to be explicit, so
    that ordinary preparation does not always require a forty-minute benchmark.
49. As an organizer, I want the rehearsal to record the exact machine, catalog,
    profile, parallelism, and timing result, so that event-day readiness can be
    compared with the proven configuration.
50. As an organizer, I want a conservative initial four-Match parallelism on my
    sixteen-core machine, so that up to eight one-CPU bot containers leave CPU
    headroom for the runner and timing stability.
51. As an organizer, I want the rehearsal to justify any higher event
    parallelism, so that speed improvements do not silently increase timeout
    risk.
52. As an organizer, I want a sixteen-Team worst-case source-to-Tournament run to
    complete within forty minutes before release, so that the event schedule is
    credible.
53. As an organizer, I want a real Tournament to continue if that objective is
    exceeded, so that an operational estimate cannot alter competitive results.
54. As an organizer, I want all global resource values configurable before
    creation and immutable afterward, so that measured tuning does not permit
    mid-Tournament rule changes.
55. As an organizer, I want all supported languages subject to the same outer
    resource ceilings, so that adding a runtime does not create language-specific
    competitive allowances.
56. As an organizer, I want ceilings calibrated for managed runtimes before those
    Language Environments are declared supported, so that PID, memory, startup,
    and temporary-filesystem defaults do not accidentally exclude them.
57. As an organizer, I want stale runner-owned containers identified and cleaned
    up safely, so that interrupted Match Attempts do not consume later capacity.
58. As an organizer, I want interruption during a containerized Match Attempt to
    retain the existing retry and recovery behavior, so that containerization
    does not change Tournament semantics.
59. As an auditor, I want the final platform-specific container image to be the
    Bot Artifact, so that the competitive identity names what actually ran.
60. As an auditor, I want source, image, runtime, wrapper, recipe, entrypoint,
    platform, catalog, execution-profile, and validation-suite identities
    retained, so that the official build is attributable.
61. As an auditor, I want the exact official image preserved rather than assumed
    reproducible from source, so that compiler or image-builder variability
    cannot replace Tournament history.
62. As an auditor, I want image-archive paths and Docker cache locations excluded
    from canonical competition identity, so that mutable local storage does not
    affect results.
63. As an auditor, I want container IDs, host details, startup durations, resource
    observations, Docker diagnostics, and stderr retained only as Operational
    Telemetry, so that variable execution data cannot change Competition Records.
64. As an auditor, I want the same sealed image, profile, seed, and Match inputs
    to produce timing-independent competitive records, so that container
    scheduling does not become canonical input.
65. As an auditor, I want image digest verification before every unresolved
    execution boundary, so that a mutable tag cannot substitute another image.
66. As a developer, I want one container Match executor behind the existing
    Match-execution request/result boundary, so that Tournament code does not
    learn Docker lifecycle details.
67. As a developer, I want the existing Match Runner to remain authoritative for
    protocol I/O, response timing, faults, completed Rounds, and scoring, so that
    host and container modes cannot drift.
68. As a developer, I want direct host-process execution retained as explicitly
    insecure development behavior, so that fast unit tests and debugging remain
    available.
69. As a developer, I want every Language Environment to implement one common
    descriptor and conformance contract, so that adding a language does not add
    conditionals to the Tournament Runner.
70. As a developer adding a Language Environment, I want to provide a submission
    schema, template, pinned platform runtimes, build recipe, wrapper, readiness
    marker, entrypoint, example strategy, and conformance fixtures, so that
    support is complete and reviewable.
71. As a developer, I want the readiness marker emitted only after the wrapper
    loads the Team strategy, so that protocol timing begins from a known state.
72. As a developer, I want readiness control data removed from Team stderr
    telemetry and limits, so that organizer coordination is not mistaken for
    Team diagnostics.
73. As a developer, I want container startup governed by a separate operational
    timeout, so that Docker latency is not charged as a move response.
74. As a developer, I want the container executor compatible with standard Linux
    Docker on AMD64, so that future GitHub-hosted Tournament execution does not
    require a redesign.
75. As a developer, I want no Docker SDK dependency when the standard Docker CLI
    can provide the required contract, so that the tool respects Docker Desktop,
    OrbStack, and ordinary Docker contexts consistently.
76. As a maintainer, I want a clean manifest-schema transition for this first-use
    system, so that unused pre-container artifacts do not impose migration work.
77. As a maintainer, I want execution-profile changes versioned rather than
    silently applied, so that later hardening is an explicit compatibility
    decision.
78. As a maintainer, I want the companion repository to own the event-facing
    Language Environment catalog while this repository owns its generic
    consumer contract, so that templates have one source of truth.
79. As a maintainer, I want companion GitHub workflows to invoke pinned core
    tooling with minimal permissions and no secrets, so that Team source is not
    given unnecessary repository authority.
80. As a maintainer, I want GitHub validation images to remain disposable, so
    that this milestone does not require a remote image registry.

## Implementation Decisions

### Authority and architectural seams

- The accepted Tournament design, protocol version 1, domain glossary, and ADRs
  0001 through 0004 remain normative. This work changes how Bot Artifacts are
  constructed and launched; it does not change scheduling, Series scoring,
  standings, playoff behavior, seed derivation, Competition Record authority,
  retry policy, or operator controls.
- The primary implementation seam is the existing Match-execution request and
  result boundary. A container executor consumes the already sealed identities,
  seeds, Bot Positions, timing limits, stream limits, CPU limit, memory limit,
  process limit, filesystem-write limit, and network policy.
- The existing Match Runner remains the sole owner of protocol version 1 I/O,
  simultaneous request dispatch, response timing, move validation, completed
  Round construction, protocol-fault detection, and Match scoring.
- The public single-Match and Tournament workflows are the highest acceptance
  seams. Lower-level Docker command construction is not a separate source of
  competitive behavior.
- The host organizer process controls Docker. The Tournament Runner itself is not
  containerized.
- Direct host-process execution remains available only as an explicitly insecure
  development/test mode. Official validation and Tournament execution require the
  container executor.

### Repository and Language Environment boundary

- This repository is the sole authority for the Language Environment Catalog,
  Team Source schema, source validator, organizer wrapper and Seed Adapter,
  runtimes, build recipe, readiness contract, entrypoint, conformance fixtures
  and runner, builder orchestration, Bot Artifact store, container executor,
  organizer commands, and Tournament integration.
- A separate Team Template repository owns only participant-facing Team
  Templates, participant convenience commands, and Advisory Validation workflow.
  It claims compatibility with an exact immutable Catalog Release and does not
  supply organizer-owned assets to this repository.
- This repository never fetches, imports, or tests the Team Template repository.
  The repositories meet only through the immutable compatibility interface in
  `docs/CATALOG_COMPATIBILITY.md`.
- This boundary supersedes the earlier split-authority wording in this PRD. ADR
  0005 records the accepted decision; there is no duplicated mutable copy of an
  organizer-owned catalog asset.
- A Language Environment is a versioned organizer-owned package containing a
  descriptor, Team Source schema, platform-specific pinned base-image digests,
  networkless build recipe, fixed entrypoint, protocol-version-1 wrapper, Seed
  Adapter, readiness behavior, and conformance fixtures. Participant-facing
  starter content belongs to a Team Template, not the Language Environment.
- Python is the only required Language Environment in this PRD. The extension
  contract must be capable of representing Rust, C#, Java, Clojure,
  JavaScript/TypeScript, Ruby, Go, Dart, and Kotlin without changes to Tournament
  logic or container execution.
- A new Language Environment is not supported until it passes the complete build,
  protocol, readiness, determinism, isolation, resource, practice-Match, ARM64,
  and AMD64 conformance contract.

### Team source contract

- Team source is transport-neutral. Git branches, archives, email, or other
  acquisition mechanisms end at the same validated local-directory boundary.
  The core organizer tool does not clone, pull, authenticate to, or monitor a
  remote source provider.
- Each Language Environment defines one controlled Team-editable source subtree.
  The schema may allow multiple language source files and approved accessory
  resources; it is not limited to one file or one universal extension list.
- Organizer-owned Dockerfiles, wrappers, project/dependency manifests, build
  targets, runner tools, workflows, and entrypoints never come from the Team
  branch at official build time.
- Source validation rejects traversal, absolute paths, escaping symlinks,
  unsupported file types, forbidden infrastructure files, excessive file count,
  excessive individual files, and excessive aggregate size before Docker receives
  the context.
- Third-party dependency declaration and package installation are prohibited in
  the initial catalog. A Language Environment may expose only the standard
  library and organizer-preinstalled pinned dependencies.
- The existing Python strategy-function semantics remain participant-facing.
  The organizer wrapper owns stdin/stdout protocol parsing, deterministic seeded
  randomness, readiness, and process lifecycle.

### Catalog freeze and platform model

- The organizer publishes and freezes one event catalog before the coding period.
  Routine catalog, wrapper, recipe, base-image, or conformance changes are
  prohibited until the event completes.
- An organizer-declared infrastructure correction may publish a replacement
  catalog version. Validation results against the replaced version cease to be
  eligible, and affected candidates must run the new suite.
- Every selected base image must be available by platform-specific immutable
  digest for both `linux/arm64` and `linux/amd64`.
- Each build targets exactly one platform. Multi-platform image builds and OCI
  indexes containing both official targets are not required.
- Local participant builds use their native supported platform. GitHub Actions
  advisory validation uses Linux/AMD64. The organizer's official build and
  Tournament use Linux/ARM64.
- Linux/AMD64 build and container-executor integration tests are required even
  though the first official Tournament runs locally on ARM64.

### Build and Bot Artifact identity

- The organizer rebuilds selected Team source through the frozen catalog. A
  Team-built image is a confidence artifact only and can never enter the roster.
- Builds receive only the validated source context and organizer-owned Language
  Environment inputs. Builds run with networking disabled, no secrets, no
  privileged mode, and bounded operational time and output.
- Event preparation pre-pulls every platform-specific base image and constructs
  reusable organizer-owned layers. Official post-cutoff builds must succeed with
  external network access unavailable.
- The final single-platform container image is the Bot Artifact. Its
  platform-specific OCI image manifest digest is `artifact_digest`.
- `runtime_digest` identifies the exact platform-specific organizer base runtime,
  not a mutable tag. The Bot Artifact Manifest also records source digest,
  Language Environment/catalog identity, wrapper version, build-recipe version,
  entrypoint, platform, conformance-suite version, and validation result identity.
- Mutable source locations, branch names, Docker tags, local image-cache names,
  archive paths, contact metadata, and GitHub URLs remain operational data outside
  canonical Tournament identity.
- Bit-for-bit reproduction of an image through a later rebuild is not required in
  this milestone. The exact official image is preserved and reused. Rebuild
  reproducibility is a future hardening property, not a substitute for artifact
  retention.
- A Bot Artifact is launchable only by verified immutable image digest. Mutable
  tags may aid human inspection but are never execution authority.

### Validation and cutoff policy

- Participant local testing, companion-repository GitHub Actions, and organizer
  final validation invoke the same versioned conformance suite through the same
  public core command.
- The suite covers source validation, networkless build, expected image identity,
  wrapper readiness, clean shutdown, representative protocol transcripts,
  repeated same-seed behavior, timing and stream limits, memory/PID/filesystem
  enforcement, a complete containerized smoke Match, and diagnostics.
- Bundled fixed-move, random, copycat, and protocol-test practice Bot Artifacts
  are ordinary Python Bot Artifacts built and executed through the same pipeline.
- A practice Match outcome never gates validation. Only build, launch, protocol,
  determinism, isolation, and resource conformance gate it.
- GitHub Actions validation is advisory and platform-specific. It produces a
  durable check result identifying the exact source commit, catalog, core tool,
  suite, platform, source digest, and disposable image identity. It does not push
  an official image.
- The companion workflow runs with minimal permissions and no repository or
  deployment secrets available to Team code. It should cancel superseded work on
  the same Team branch where GitHub supports doing so.
- The nominal Git workflow selects the latest GitHub-green source commit before
  the hard cutoff. The organizer manually exports or pulls that source and may
  explicitly select an earlier pre-cutoff green candidate.
- The local ARM64 rebuild and full conformance result are authoritative. No image
  enters the Tournament solely because its AMD64 GitHub check passed.
- If a rare local incompatibility remains, the organizer may supervise a
  post-cutoff compatibility-only repair. The original source, repair diff,
  explanation, catalog, and successful validation are retained. Strategy
  enhancement is prohibited. This is an operator policy backed by the event's
  honor system, not a complex semantic source-diff classifier.
- Failures caused by the catalog, Docker engine, core tooling, or organizer host
  may be repaired and retried without attributing a Team validation failure.

### Durable local Bot Artifact store

- Successful official builds produce a local artifact set containing frozen
  source bundles, Bot Artifact Manifests, validation reports, an index, and all
  selected container images.
- At roster finalization, selected images are exported together into a Docker
  image archive so shared layers need not be stored once per Team. The archive
  and its index are integrity-checked and retained with the Tournament's
  operational artifacts.
- The image archive is preservation media, not Bot Artifact identity. The
  platform-specific image manifest digest remains authoritative.
- Before creation or resumption, the resolver verifies the index and selected
  image digests. If an image is absent from the active Docker engine, the resolver
  loads it from the verified archive and verifies it again.
- A missing, corrupt, wrong-platform, or identity-mismatched image blocks
  execution as an infrastructure/integrity condition. It never triggers a
  rebuild or substitutes a mutable tag after Tournament creation.
- Artifact storage is local-first. A remote registry, object store, or image
  distribution service is not required.

### Organizer plan and commands

- The batch builder consumes organizer-selected local Team source directories and
  produces a draft human-reviewable JSON Tournament plan.
- The plan names Team IDs, Team Display Names, selected source identities, Bot
  Artifact Manifests, artifact-store references, Tournament Seed, execution mode,
  parallelism, Language Environment catalog, execution profile, and global
  resource values.
- Tournament creation validates the complete plan, Bot Artifact store, platform,
  images, profile, resources, and existing Tournament invariants before sealing a
  new Tournament Manifest.
- The general artifact-plan workflow complements or supersedes the fixed bundled
  demo for event operation. The demo may remain for development if it uses
  explicit development behavior and does not masquerade as the event workflow.
- The single-Match CLI accepts two validated Bot Artifact references and uses the
  same container executor, profile, protocol engine, and normalized result
  contract as Tournament Matches.
- Participant convenience commands in the companion repository are thin wrappers
  over the public build, conformance, and single-Match commands. They do not
  reimplement validation logic.

### Container execution profile

- New official Tournaments seal a versioned organizer-owned execution profile.
  The initial profile is conceptually `docker-execution-v1`; its final published
  identifier is an implementation-owned compatibility name.
- Every Bot Position runs in its own fresh container for every Match. Two Bot
  Artifacts never share a container, filesystem, process namespace, network
  namespace, or writable temporary storage.
- The profile enforces no external network, no host bind mounts, no Docker socket,
  a read-only root filesystem, a bounded private temporary filesystem, a non-root
  numeric user, all Linux capabilities dropped, no privilege escalation, a
  pinned syscall policy, process/open-file limits, memory limit, CPU limits, and
  bounded stdout/stderr.
- The executor passes no arbitrary host environment. It supplies only
  `RPS_PROTOCOL_VERSION`, `RPS_ROUNDS`, the Bot Artifact's own `RPS_SEED`, and a
  fixed versioned allowlist of infrastructure environment such as locale,
  timezone, home, and temporary-directory values.
- Container hostname and other runtime-visible infrastructure values are fixed or
  non-contractual and must not reveal Team identity, opponent identity, ranking,
  language, seed derivations, host paths, or credentials.
- Global outer resource ceilings are identical for all supported languages and
  both Bot Positions. A Language Environment cannot request an exception.
- CPU, memory, PID, open-file, writable-filesystem, startup, shutdown, and related
  initial values are established through measured conformance and documented with
  the published profile. The currently unenforced one-process and zero-write
  defaults are not presumed valid for managed runtimes.
- The organizer may tune global values before Tournament creation. Every selected
  Bot Artifact must be revalidated under those exact values. Creation seals them,
  and retries, resumption, mode changes, or language cannot change them afterward.
- The initial performance calibration gives each Bot Artifact no more than one
  CPU and begins with four concurrent Matches on the organizer's sixteen-core
  machine. A measured rehearsal may justify another explicit value before
  sealing; no runtime auto-scaling or host-derived dynamic parallelism is added.
- Basic preflight may reject an obviously impossible requested configuration, but
  it does not claim to calculate a perfectly safe host-specific concurrency
  ceiling.

### Readiness, lifecycle, and timing

- Every organizer wrapper emits one reserved, versioned readiness marker on
  stderr only after its runtime and Team strategy are loaded and it is ready to
  read Turn 0.
- The executor creates and starts both Bot Position containers concurrently,
  attaches their streams, and waits for both readiness markers. Protocol response
  timing begins only when the Match Runner sends Turn 0.
- Readiness markers are infrastructure control data. They are removed from Team
  stderr, do not consume the Team stderr allowance, and may be recorded only as
  Operational Telemetry.
- Container creation, image loading, stream attachment, readiness waiting, and
  cleanup use operational timeouts separate from competitive response budgets.
  An alive and otherwise silent wrapper that fails to become ready before the
  startup timeout produces an Infrastructure Failure under the agreed startup
  contract.
- Team-attributable unexpected process exit or prohibited stdout remains a Bot
  Artifact fault even when it happens early. Docker creation or attachment
  failure remains an Infrastructure Failure.
- Once either Bot Artifact produces a terminal fault or the Match completes, the
  executor closes input, terminates both containers with a bounded grace period,
  force-kills survivors, reaps Docker processes, captures final status, and
  removes runner-owned containers.
- Runner-owned labels and canonical Match Attempt identifiers support precise
  cleanup after interruption. Cleanup targets only containers proven to belong
  to this runner and never broadly prunes Docker state.
- An interrupted uncommitted container Match Attempt restarts from Turn 0 with
  the exact sealed images and inputs under the existing Match Attempt policy.

### Outcome classification and telemetry

- Invalid protocol, competitive response timeout, unexpected Team process exit,
  stdout overflow, stderr policy breach, OOM, PID exhaustion, writable-filesystem
  exhaustion, or another attributable published resource breach is a Bot Artifact
  fault and follows existing Match-forfeit behavior.
- The per-container CPU quota throttles concurrent CPU use. The sealed total CPU
  and response budgets remain enforceable resource contracts; an attributable
  breach becomes a Bot Artifact resource fault.
- Image loading, Docker daemon availability, container creation, stream
  attachment, host exhaustion, runner cleanup, and other non-attributable
  execution failures are Infrastructure Failures and use the existing automatic
  retry and pause policy.
- Prevention is the primary security mechanism. The executor returns a suspected
  Security Violation only when the runtime supplies clear evidence attributable
  to one or both Bot Artifacts. It does not promise to detect or explain every
  denied operation.
- Opaque security evidence links continue through the existing Tournament ruling
  seam. Raw Docker or security diagnostics remain Operational Telemetry.
- Docker container IDs, names, host/engine versions, platform observations,
  timestamps, startup and cleanup durations, stderr, runtime resource use, exit
  metadata, OOM status, raw errors, and failed Match Attempts are Operational
  Telemetry only.
- Container execution does not add Docker details, launch commands, local image
  names, archive paths, or host state to Competition Records or the Scoreboard
  Projection.
- Timing or container completion order may change telemetry but cannot change the
  canonical scheduler, commit order, standings, or reconstructed Tournament
  state.

### Machine diagnosis, preparation, and performance

- A read-only doctor command reports Docker connectivity, active context,
  engine/server architecture, required feature support, catalog availability,
  pinned-image presence, available disk, configured CPU visibility, profile
  enforcement prerequisites, and prior rehearsal compatibility.
- Doctor works with a Docker-compatible active context, including OrbStack. It
  does not require Docker Desktop specifically.
- A separate preparation command may pull the already pinned ARM64 base images,
  build organizer-owned cached layers and practice Bot Artifacts, verify offline
  rebuild behavior, exercise the execution profile, and write a readiness report.
- Preparation does not install Docker, mutate host settings, delete unrelated
  images, broadly prune caches, or silently change the selected catalog/profile.
- Fast preparation is the default. The complete sixteen-Team rehearsal is an
  explicit option because it may consume the entire target window.
- The full rehearsal uses representative conforming Python Team source, the real
  builder, final local validation, the durable image archive, the general plan,
  public Tournament Runner, real container executor, 300 scheduled Turns per
  Match, worst-case three-Match Series, Competition Record storage,
  reconstruction, and Scoreboard Projection.
- On the organizer's sixteen-core Apple M4 Max with 128 GB RAM, a warmed,
  offline-capable sixteen-Team rehearsal must complete build, validation,
  archival, and the worst-case Tournament within forty minutes before the system
  is considered event-ready.
- The objective excludes human source acquisition and supervised repair time,
  which cannot be measured deterministically. It includes all automated work
  after valid local source directories are supplied.
- A readiness overrun fails the release/rehearsal report but never creates a Bot
  Artifact fault, Infrastructure Failure, operator pause, Competition Record
  mutation, or Tournament abort during actual play.

### Versioning and migration

- This first-use project may make a clean Tournament Manifest and Bot Artifact
  Manifest schema transition to the container contract. Compatibility with
  unused pre-container Tournament artifacts is not required.
- The new schema retains all accepted deterministic Tournament fields and adds
  only the immutable identities required to select the exact container artifact,
  platform, build inputs, validation, and execution profile.
- Execution-profile, Language Environment, catalog, and conformance changes are
  explicit compatibility versions. No mutable `latest` value participates in a
  sealed Tournament.
- Host-process single-Match development remains supported, but it is not evidence
  that an official Bot Artifact is valid and cannot create a container-profile
  Tournament roster entry.

## Testing Decisions

- Tests assert externally observable behavior through the highest useful seam.
  The preferred seam is source directory plus frozen catalog in, followed by a
  public build/validate command, artifact store, JSON plan, public Match or
  Tournament command, Competition Records, Operational Telemetry, and Scoreboard
  Projection out.
- The central parity test runs deterministic Python Bot Artifacts through both
  host-process development mode and container mode with identical protocol
  inputs, then compares normalized competitive outcomes while explicitly allowing
  Operational Telemetry to differ.
- Repeated runs of the same sealed container Bot Artifacts and Tournament inputs
  must produce byte-identical deterministic Competition Records and equivalent
  reconstructed state regardless of Docker container IDs, startup durations,
  completion timing, or worker completion order.
- Existing Match Runner tests remain prior art for simultaneous request dispatch,
  response timing, protocol faults, Double Forfeit behavior, stdout/stderr bounds,
  process termination, and match-result structure. Container tests reuse those
  expectations rather than duplicating scoring logic.
- Existing Match-executor contract tests remain prior art for sealed request
  forwarding, competitive normalization, telemetry separation, security
  suspicion, and Infrastructure Failure behavior. The container executor must
  pass the same contract suite.
- Existing Tournament Runner and CLI tests remain prior art for retries,
  interruption, Step Mode, Continuous Mode, parallel commit buffering, artifact
  verification, storage reconstruction, and projection. Each path receives
  containerized end-to-end coverage without new Tournament-only Docker branches.
- Source-validation tests use traversal, absolute paths, symlinks, unexpected
  infrastructure files, unsupported types, oversize files, excessive counts,
  modified wrapper/build files, and valid multi-file Python source.
- Build tests prove that no network or undeclared dependency is required, that
  pinned platform digests are honored, that Team Dockerfiles/build scripts are
  ignored or rejected, and that an ARM64 build cannot satisfy an AMD64 artifact
  request or vice versa.
- Readiness tests cover successful marker detection, marker split across stream
  chunks, Team stderr before and after readiness, stdout before Turn 0, process
  exit, missing marker, startup timeout, one container ready before the other,
  concurrent start fairness, and marker removal from Team stderr.
- Isolation fixtures attempt network access, host-file reads, root-filesystem
  writes, temporary-filesystem overflow, privilege escalation, capability use,
  Docker-socket access, excessive processes, excessive open files, excessive
  memory, CPU use, stdout, and stderr. Tests assert prevention and the agreed fault
  classification, not unverifiable forensic explanations.
- Infrastructure fixtures simulate missing Docker, wrong context, image absence,
  corrupt archive, wrong image digest, wrong platform, create/start/attach/inspect
  failure, daemon loss, host exhaustion, cleanup failure, interrupted attempts,
  and stale runner-owned containers.
- Lifecycle tests prove that every Match receives fresh containers, both
  containers terminate after a terminal fault, survivors are killed after the
  grace period, only runner-owned containers are removed, and an interrupted
  uncommitted attempt restarts with the same immutable images.
- Environment tests inspect the complete visible environment and assert the
  versioned allowlist, per-Team seed separation, absence of opponent identity,
  absence of host variables and credentials, fixed infrastructure values, and
  no host mounts.
- Artifact-store tests cover multi-image export, shared-layer preservation where
  Docker provides it, manifest and archive integrity, automatic loading, digest
  re-verification, cache deletion, resumption, missing/corrupt sources and
  reports, and refusal to rebuild after Tournament sealing.
- Plan tests cover generation, human-editable presentation fields, duplicate or
  malformed Team IDs, missing validation, mismatched catalog/profile, mutable
  tags without digests, wrong platform, invalid resource values, artifact-store
  mismatch, and successful sealing through the public Tournament workflow.
- Validation-suite contract tests run the same suite entrypoint in participant,
  GitHub/AMD64, and organizer/ARM64 modes and prove that platform-specific image
  identities remain distinct while compatibility rules stay equivalent.
- The Python tracer environment includes a conforming strategy, deterministic
  random strategy, multi-file strategy, syntax/build failure, import-time failure,
  nondeterministic strategy, protocol fault, slow response, memory pressure,
  process pressure, filesystem pressure, and premature output fixtures.
- Linux/AMD64 Docker integration tests run in CI or an equivalent ordinary Linux
  Docker environment. ARM64 integration and the full rehearsal run against the
  organizer's Docker-compatible engine and frozen event catalog.
- Fast tests may use a controllable Docker-command adapter for rare daemon errors,
  but real Docker integration is required for security controls, stream
  attachment, signals, image identity, resource enforcement, archive loading, and
  lifecycle claims.
- The explicit full rehearsal is separate from the default unit/integration test
  suite. It records elapsed time and exact configuration, fails if the forty-minute
  release objective is exceeded, and treats genuine correctness or integrity
  failures distinctly from timing overruns.

## Acceptance Criteria

1. One valid Python Team source directory can be validated, built without
   network, identified by platform-specific image digest, archived, reloaded,
   and executed against a practice Bot Artifact through the public single-Match
   CLI.
2. The Python participant strategy API remains the existing organizer-wrapper
   `choose_move` contract and supports multiple Team source files under the
   controlled submission schema.
3. Team source cannot replace or modify the official wrapper, Dockerfile,
   dependency policy, entrypoint, readiness behavior, or build targets used by
   the official builder.
4. The same versioned suite validates participant-local, GitHub/AMD64, and
   organizer/ARM64 builds while retaining platform-specific validation and image
   identities.
5. A GitHub-green AMD64 candidate cannot enter a Tournament until its selected
   source passes the authoritative local ARM64 build and validation.
6. A supervised compatibility repair retains the original candidate, complete
   diff, explanation, and final validation identity.
7. Official local builds succeed with external network access unavailable after
   successful machine preparation.
8. Every new official Tournament roster entry references an exact ARM64 Bot
   Artifact image digest, exact base runtime digest, source digest, wrapper,
   recipe, entrypoint, catalog, suite, platform, and execution-profile identity.
9. A human-reviewable JSON plan generated from validated Bot Artifacts can create
   and run a general four-through-thirty-two-Team Tournament without the bundled
   demo roster.
10. Each Match starts exactly one fresh container per Bot Position and no
    container persists as Team state into a later Match.
11. Both wrappers must become ready before Turn 0, and startup time cannot consume
    first-move, later-move, or total response-time budgets.
12. Containers receive only the versioned environment allowlist and cannot see
    opponent identity, arbitrary host variables, credentials, host mounts, or a
    Docker socket.
13. The sealed execution profile enforces network isolation, read-only root,
    bounded temporary writes, non-root execution, dropped capabilities, no
    privilege escalation, syscall policy, CPU, memory, PIDs, open files, stdout,
    and stderr equivalently for both Bot Positions.
14. Global profile values may be changed only before creation, require
    revalidation of all selected Bot Artifacts, and are immutable after the
    Tournament Manifest is sealed.
15. Attributable protocol and resource breaches produce the existing competitive
    Match-fault outcomes; Docker and host failures produce Infrastructure
    Failures and use the existing retry/pause policy.
16. Prevention of prohibited access does not depend on comprehensive security
    forensics, and only clear attributable evidence enters the existing suspected
    Security Violation workflow.
17. Container, host, startup, resource, stderr, and Docker observations appear
    only in Operational Telemetry and never alter Competition Records or the
    Scoreboard Projection.
18. Deterministic conforming Python Bot Artifacts produce equivalent competitive
    Match outcomes in host development and container modes, and repeated runs of
    the same sealed container Tournament inputs produce byte-identical canonical
    records.
19. Missing cached images are restored from the verified local archive; corrupt,
    missing, wrong-platform, or digest-mismatched artifacts block execution and
    never trigger an implicit rebuild or tag substitution.
20. The single-Match and Tournament CLIs share the same container executor and
    Match Runner behavior.
21. Direct host-process mode remains available for development and is clearly
    identified as insecure and insufficient for official validation.
22. The doctor command diagnoses the active Docker context, including OrbStack,
    without mutating host or Docker state.
23. The preparation command warms and verifies all pinned local prerequisites,
    proves offline build availability, and never deletes unrelated Docker data or
    changes host settings.
24. An explicit full rehearsal uses no fake Match executor or host Bot Artifact
    process and completes the automated sixteen-Team build, validation, archive,
    worst-case Tournament, reconstruction, and projection workflow within forty
    minutes on the organizer's prepared sixteen-core M4 Max.
25. A rehearsal timing overrun fails readiness reporting only; an actual
    Tournament never turns the forty-minute objective into a competitive timeout,
    fault, pause, record change, or abort.
26. The container builder and executor pass real Linux/AMD64 Docker integration
    tests without OrbStack- or macOS-specific assumptions.
27. A second organizer-owned Language Environment can be represented by the
    contract and run through contract tests without modifying Tournament
    scheduling, scoring, state, storage, or projection modules.

## Out of Scope

- Required production support for Rust, C#, Java, Clojure,
  JavaScript/TypeScript, Ruby, Go, Dart, Kotlin, or any language other than
  Python. Those environments are stretch deliverables against the contract.
- Creation, permissions, branch rules, and operational administration of the
  companion template/submission repository. It is separately tracked, although
  this PRD defines its catalog and workflow integration contract.
- Automated GitHub branch discovery, cloning, pulling, cutoff enforcement,
  commit selection, archive download, participant identity management, or source
  upload UI.
- Running the Tournament through GitHub Actions. Linux/AMD64 compatibility is an
  architectural acceptance seam only for this milestone.
- A remote container registry, image publication, cross-machine distribution,
  object storage, cloud build service, or remote artifact backup.
- Multi-platform image builds, multi-platform OCI indexes, QEMU-based official
  builds, or a requirement that ARM64 and AMD64 images have the same digest.
- Participant-provided Dockerfiles, participant-provided container images,
  custom base images, privileged containers, or per-Team execution profiles.
- Third-party package requests, online dependency resolution, arbitrary build
  scripts, package mirrors, or a dependency approval workflow.
- Byte-for-byte reproducible image rebuilding. Exact official image preservation
  is required instead.
- Comprehensive syscall auditing, intrusion detection, exploit attribution,
  container-escape forensics, or automatic Security Violation rulings.
- Native Podman, containerd, Kubernetes, or arbitrary OCI-runtime support beyond
  compatibility available through the standard Docker CLI contract.
- Containerizing the organizer CLI or Tournament Runner, Docker-in-Docker, or
  mounting the Docker socket into another container.
- Automatic host tuning, Docker installation, Docker Desktop/OrbStack
  configuration mutation, image pruning, or destructive disk cleanup.
- Automatic calculation of a supposedly safe Match parallelism from host
  resources or dynamic adjustment of parallelism during a Tournament.
- Per-language CPU, memory, process, filesystem, timing, or output advantages.
- Compatibility or migration for unused pre-container Tournament Manifests,
  Competition Records, or local demo artifacts created before this schema
  transition.
- Changes to protocol version 1, Tournament format, scheduling, scoring,
  tie-breaks, Disqualification, Security Violation rulings, retry policy,
  Competition Record authority, recovery semantics, or Scoreboard Projection.
- Submission secrecy enforcement. A shared branch repository may operate under
  the event's honor policy.
- Scoreboard UI, replay UI, source-code viewer, or participant-facing build web
  interface.

## Further Notes

- The normative Tournament behavior comes from the accepted Tournament design,
  protocol version 1 document, domain glossary, and ADRs 0001 through 0004. Older
  general README descriptions of the preferred Tournament format remain
  superseded.
- The term Bot Artifact now resolves concretely to the immutable official
  platform-specific container image. Team source is build input, not the
  competitive executable identity.
- Language-specific deterministic random streams remain accepted. ARM64 and
  AMD64 images need not produce identical image bytes, but a conforming frozen
  Bot Artifact must remain deterministic for its own platform, wrapper, runtime,
  bot-visible seed, and request sequence.
- The exact initial memory, PID/thread, open-file, writable-temporary-filesystem,
  startup-timeout, shutdown-grace, and related values are intentionally selected
  by measurement rather than copied from currently unenforced placeholders. The
  published profile and rehearsal report must make the final values explicit
  before event use.
- The forty-minute readiness profile begins after valid local source directories
  and the frozen catalog are present. Human Git operations and supervised repair
  cannot be meaningfully included in a deterministic capacity benchmark.
- The companion repository is required for the desired Team workflow even though
  its creation is separately tracked. The core implementation should expose a
  stable command contract early enough for that repository to integrate without
  copying logic.
- GitHub Actions validation is intentionally advisory because it builds AMD64
  while the official local Bot Artifact is ARM64. Its chief value is rapid Team
  feedback and identifying the latest compatible pre-cutoff candidate.
- The design remains suitable for a later GitHub Actions Tournament: the host
  process controls ordinary Linux Docker, images are immutable and
  platform-specific, all competitive inputs are sealed, and no OrbStack-specific
  behavior enters the Match-execution contract.
