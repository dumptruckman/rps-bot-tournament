# Restore Python 3.9 compatibility

Status: ready-for-agent

Priority: 1

Blocked by: None

## What to build

Restore the repository's declared Python 3.9 compatibility so the public Match
and Tournament commands, certification workflow, organizer preparation, batch
planning, rehearsal, and capacity verification can all import and run under the
supported Python 3.9 environment.

Keep the existing supported-version contract rather than raising the minimum
Python version to accommodate syntax introduced after Python 3.9.

## Acceptance criteria

- [ ] Every runtime-evaluated annotation and type alias imports successfully
  under Python 3.9.
- [ ] The public Match, Tournament, certification, organizer-preparation,
  batch-plan, rehearsal, and capacity modules import through their normal
  command seams under Python 3.9.
- [ ] The complete repository unit-test suite passes under the repository's
  Python 3.9 virtual environment, apart from explicitly gated Docker integration
  tests.
- [ ] A regression check protects the declared minimum Python version from
  future import-time syntax or annotation failures.
- [ ] Documentation and package metadata continue to agree on the supported
  minimum Python version.

## Comments

The current failure is an import-time `TypeError` caused by a runtime-evaluated
union in the Tournament Match-execution boundary. Because affected modules fail
during discovery, the failing test run does not exercise the full suite.
