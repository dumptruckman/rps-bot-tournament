# Deepen the batch Tournament-plan module

Status: ready-for-agent

Blocked by: 11

## What to build

Refine the batch source-to-Tournament-plan workflow into deeper modules whose
interfaces express the organizer-facing domain concepts directly. Separate
Team source mapping, supervised compatibility-repair evidence, batch execution,
and plan/report projection so each concern can evolve without repeatedly
changing the public command orchestration.

Replace stringly typed internal execution modes and Team workflow states with
constrained domain types. Preserve the existing public command, JSON formats,
deterministic ordering, concurrency behavior, failure isolation, canonical Bot
Artifact identity, and supervised-repair evidence.

## Acceptance criteria

- [ ] The public batch command retains its existing arguments, exit behavior, output artifacts, and human-reviewable JSON compatibility.
- [ ] Team source mapping and validation form one focused module boundary with explicit Team identity and display-name concepts.
- [ ] Supervised compatibility-repair input and retained evidence form one value object with an all-or-nothing source, explanation, and provenance contract.
- [ ] Batch execution coordinates bounded concurrent Team workflows without owning mapping validation, repair-diff construction, or plan/report serialization details.
- [ ] Tournament-plan and batch-report projections expose focused interfaces and preserve stable Team ordering independently of worker completion timing.
- [ ] Internal execution modes and Team workflow states cannot represent values outside their supported domains, while serialized JSON retains the established string values.
- [ ] Exact validated Bot Artifact Manifests remain structurally distinct from cache-free canonical Bot Artifact identity projections.
- [ ] Existing success, independent failure, root-symlink rejection, and complete supervised-repair behavior remains covered through the public batch-command seam.
- [ ] The complete repository test suite remains green.
