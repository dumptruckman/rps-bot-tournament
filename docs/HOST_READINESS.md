# Container Host Readiness

`rps-doctor` inspects whether the active Docker-compatible environment can use
the frozen Language Environment catalog, the published execution profile, and a
durable Bot Artifact store. It accepts Docker Desktop, OrbStack, or another
compatible active Docker context; no product name is required.

The command is deliberately read-only. Its complete Docker command allowlist is:

- `docker context show`
- `docker version --format`
- `docker info --format`
- `docker image inspect`

It never pulls, builds, loads, tags, creates or starts a container, changes a
setting, prunes a cache, repairs metadata, or deletes anything. A failed check
includes remediation guidance, but remediation remains a separate explicit
operation.

## Usage

Pass the exact cached organizer layers and practice Bot Artifacts produced by
preparation. Each reference must be either an image ID or a repository reference
pinned by a SHA-256 digest. Omitting either group is reported as not ready rather
than silently skipping the check.

```text
rps-doctor \
  --catalog language_environments/catalog-v1/catalog.json \
  --platform linux/arm64 \
  --artifact-store path/to/artifact-store \
  --parallelism 4 \
  --expected-context orbstack \
  --organizer-layer sha256:<organizer-image-id> \
  --practice-artifact fixed-move=sha256:<practice-image-id>
```

Repeat `--organizer-layer` and `--practice-artifact` for the complete prepared
set. `--expected-context` is optional; when supplied, it distinguishes a healthy
but unintended active context from an unavailable engine. The disk check uses a
conservative 10 GiB minimum by default and can be configured with
`--minimum-free-disk-bytes`.

The command prints one `container-host-readiness-v1` JSON object and returns zero
only when every required check passes. The object contains stable top-level
sections for the machine, Docker engine, catalog, local images, Bot Artifact
store, disk, CPU capacity, execution profile, rehearsal comparison, and ordered
checks. Each check has `status`, `code`, `detail`, and `remediation` fields for
organizer automation and concise human guidance.

## Rehearsal evidence

An optional prior rehearsal report can be supplied with
`--rehearsal-evidence`. The report must be a JSON object with these binding
fields:

```json
{
  "rehearsal_report_format_version": "rps-rehearsal-report-v1",
  "status": "passed",
  "machine_identity": "container-host-machine-v1@sha256:<digest>",
  "engine_identity": "docker-engine-v1@sha256:<digest>",
  "docker_context": "orbstack",
  "catalog_identity": "rps-language-environment-catalog-v1@sha256:<digest>",
  "profile_identity": "docker-execution-v1@sha256:<digest>",
  "platform": "linux/arm64",
  "parallelism": 4
}
```

Doctor reports exactly which bindings differ. Missing evidence is recorded as
`not_provided` and does not make otherwise usable host prerequisites fail;
corrupt, failed, or mismatched supplied evidence does.
