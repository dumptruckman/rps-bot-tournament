# Serve live Tournament standings

Status: ready-for-agent

Priority: 2

Blocked by: None

## Parent

[Tournament Presentation](../PRD.md)

## What to build

Deliver the first end-to-end browser-visible presentation path: an organizer can
start a dedicated loopback presentation process against one Tournament
directory, open the printed URL, and see the Tournament identity, current
status, phase, Team Display Names, and runner-ordered qualifying standings. The
page follows atomically replaced Scoreboard Projections without requiring the
Tournament Runner to serve browser traffic.

## Acceptance criteria

- [ ] `rps-tournament present --directory TOURNAMENT_DIRECTORY` starts a
  dedicated read-only process on `127.0.0.1`, prints its URL, and supports
  configurable host and port arguments without changing the loopback default or
  accepting a non-loopback bind.
- [ ] The process starts while `scoreboard.json` is absent, but rejects an
  unreadable Tournament directory, an invalid bind address, and an unavailable
  port with a non-zero exit.
- [ ] A version-aware, allowlisted browser contract exposes only Tournament
  identity, lifecycle, phase, Team Display Names, and the standings fields already
  ordered and calculated by the Scoreboard Projection.
- [ ] The browser polls once per second with conditional requests and replaces
  its whole view for each accepted atomic projection rather than merging
  generations.
- [ ] Missing, corrupt, unreadable, or unsupported projections retain the last
  valid view and produce a visible local freshness warning; recovery clears the
  warning without altering competitive status.
- [ ] No presentation module imports scoring, standings calculation,
  scheduling, bracket construction, Tournament Runner, or Bot Artifact
  execution code, and the presentation process performs no Tournament-store
  writes or run-lock acquisition.
- [ ] Bundled HTML, CSS, and vanilla JavaScript load without a CDN, asset build,
  framework, or event-day runtime dependency beyond Python 3.9 and its standard
  library.
- [ ] Contract and HTTP integration tests cover paused and running views, ETag
  behavior, atomic replacement, failure and recovery, path traversal rejection,
  hostile Team Display Names, and exclusion of non-allowlisted fields.

## Comments

The full presentation boundary and displayed-fact mapping are defined in
[`docs/PRESENTATION.md`](../../../docs/PRESENTATION.md).
