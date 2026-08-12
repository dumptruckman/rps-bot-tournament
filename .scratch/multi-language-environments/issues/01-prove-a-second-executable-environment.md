# Prove a second executable Language Environment

Status: ready-for-agent

Blocked by: None

## Parent

[Multi-language Language Environments](../PRD.md)

## What to build

Carry a small internal non-Python executable Language Environment through the
complete Runner path so catalog selection, Team Source freezing, container
build, certification, planning, Match execution, retention, and Catalog Release
publication no longer depend on Python constants.

## Acceptance criteria

- [ ] Public source, artifact, certification, preparation, and planning commands
  select the Language Environment from explicit input or immutable upstream
  manifests rather than selecting Python internally.
- [ ] Candidate verification, Bot Artifact Manifests, validation reports,
  Tournament plans, and retained artifacts preserve and verify the selected
  language and its exact catalog-owned identities.
- [ ] The catalog can describe distinct immutable build-toolchain and execution-
  runtime images for Linux/AMD64 and Linux/ARM64 while preserving the current
  single-image Python environment during migration.
- [ ] Catalog publication validates every production environment generically,
  records every environment's conformance-suite identity, and rejects mutable,
  incomplete, or contract-only production entries.
- [ ] Static Team Source validation is selected by a versioned catalog policy;
  Python syntax rules no longer leak into another language's validation.
- [ ] One internal executable fixture passes source freezing, networkless build,
  wrapper readiness, representative protocol, same-seed determinism, isolation,
  resource, lifecycle, practice-Match, and artifact-retention checks.
- [ ] Existing Python Advisory and Final Validation behavior and immutable
  identities remain covered throughout the expansion.
- [ ] Generic Runner modules contain no new language-name branches, and the
  Runner does not read or test the Team Template repository.

## Comments

This is the architectural tracer bullet. The internal fixture is certification
evidence, not a supported participant language or Team Template.
