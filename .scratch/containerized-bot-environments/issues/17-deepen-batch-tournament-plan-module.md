# Deepen the batch Tournament-plan module

Status: resolved

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

- [x] The public batch command retains its existing arguments, exit behavior, output artifacts, and human-reviewable JSON compatibility.
- [x] Team source mapping and validation form one focused module boundary with explicit Team identity and display-name concepts.
- [x] Supervised compatibility-repair input and retained evidence form one value object with an all-or-nothing source, explanation, and provenance contract.
- [x] Batch execution coordinates bounded concurrent Team workflows without owning mapping validation, repair-diff construction, or plan/report serialization details.
- [x] Tournament-plan and batch-report projections expose focused interfaces and preserve stable Team ordering independently of worker completion timing.
- [x] Internal execution modes and Team workflow states cannot represent values outside their supported domains, while serialized JSON retains the established string values.
- [x] Exact validated Bot Artifact Manifests remain structurally distinct from cache-free canonical Bot Artifact identity projections.
- [x] Existing success, independent failure, root-symlink rejection, and complete supervised-repair behavior remains covered through the public batch-command seam.
- [x] The complete repository test suite remains green.

## Answer

Split the batch source-to-Tournament-plan workflow into focused modules for Team
source mapping, supervised compatibility-repair evidence, bounded concurrent
execution, exact and canonical Bot Artifact identities, and stable JSON
projections. The public command now limits itself to orchestration while
preserving its established arguments, outputs, exit behavior, ordering,
concurrency, and independent failure behavior.

Team IDs, Team Display Names, execution modes, and Team workflow states now use
constrained domain types. Compatibility repair input and complete retained
provenance travel together, and exact validated Bot Artifact Manifests remain a
different structural type from cache-free canonical identity projections. The
public batch-command tests and the complete 356-test repository suite pass.
