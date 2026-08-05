# Issue tracker: Local Markdown

Issues and PRDs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`,
  numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history append under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/`, creating the directory if
needed.

## When a skill says "fetch the relevant ticket"

Read the referenced file. The user will normally pass its path or issue number
directly.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Blocking: a `Blocked by: NN, NN` line
- Frontier: the first numbered open, unblocked, unclaimed issue
- Claim: set `Status: claimed`
- Resolve: append an `## Answer`, set `Status: resolved`, and update the map
