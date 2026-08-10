# Tournament Presentation

## Decision

The first Tournament presentation release is a local, read-only browser view
served by a presentation process that is separate from the Tournament Runner.
It consumes the runner-owned `scoreboard.json` Scoreboard Projection for the
live view and verified `match_terminal` Competition Records for replay. It does
not run Bot Artifacts, fold Tournament state, calculate standings, choose a
Match, or write to the Tournament directory.

This release is deliberately a presentation adapter, not a second Tournament
application. If a fact is absent from the Scoreboard Projection or the selected
Match's committed Competition Record, the view omits it rather than deriving
it.

## Users and event-day workflow

The intended users are:

- the organizer, who launches one presentation process against the active
  Tournament directory, confirms that the browser is receiving fresh
  projections, and puts the view on a shared display; and
- the audience, who follows the Qualifying Phase, Playoff Phase, completed
  Matches, and Tournament Champion and can inspect the replay of a selected
  completed Match.

The organizer continues to operate the Tournament exclusively through the
Tournament Runner's commands. The presentation release has no controls for
start, pause, resume, rulings, abort, scheduling, or scoring.

The event-day workflow is:

1. Create or open the Tournament with the Tournament Runner.
2. In another process, run
   `rps-tournament present --directory TOURNAMENT_DIRECTORY`.
3. Open the printed loopback URL in a supported browser and optionally mirror
   it to the audience display.
4. Leave the page open while the runner atomically replaces `scoreboard.json`.
   The page follows accepted projections without a browser refresh.
5. Select a completed Match to inspect its committed completed Rounds. Closing
   replay returns to the current live view; replay never changes runner state.
6. Stop the presentation process independently. Doing so does not interrupt the
   Tournament, and resuming presentation requires only relaunching the command.

## Smallest independently useful release

One responsive page provides:

- a Tournament header with current status and phase;
- Qualifying Phase standings in projection order, including every projected
  tie-break field;
- Fixture and Match cards showing scheduled, active, in-progress, complete,
  skipped, and administratively resolved states;
- the Playoff Phase bracket when it exists;
- a completed-Match history assembled by displaying the projected Fixture
  Match summaries in projected Fixture order and Match order;
- a Tournament Champion treatment, or a clear completed-without-champion or
  aborted treatment; and
- a replay panel for one selected completed Match.

“Match progress” in this release means the runner-published Match-boundary
states: scheduled, active, and committed. The Scoreboard Projection is not
updated per Turn, so the presentation does not estimate a live Round score or
animate uncommitted Turns. That would require a separate future projection
contract.

The release supports one local Tournament directory and one browser-facing
presentation process. It does not include remote hosting, authentication,
operator controls, theming, commentary, audio, multiple Tournaments, or
re-execution-based replay.

## Authority and displayed-fact mapping

The presentation server emits a narrow, allowlisted browser contract. Copying,
labeling, ordering an already ordered array, joining a projected Team ID to its
projected Team Display Name, and formatting values are presentation operations.
Recalculating, reranking, inferring an outcome, or selecting the next Match are
not.

| Displayed fact | Authoritative input | Presentation rule |
| --- | --- | --- |
| Tournament identity | Scoreboard Projection `tournament_id` | Display as supplied. |
| Tournament lifecycle | Projection `status` | Map the supplied enum to audience language; never infer status from Fixture counts. |
| Current phase | Projection `phase` | Display Qualifying Phase or Playoff Phase as supplied. |
| Team Display Name | Projection `teams[].team_id` and `display_name` | Use the Team Display Name and retain Team ID as the stable lookup key. |
| Team eligibility | Projection `teams[].eligible` and `status`, when present | Display Disqualification without exposing evidence. Absence means no extra eligibility label, not an inferred `true`. |
| Standings rank | Position in projection `standings[]` | Preserve array order; never sort or rerank. |
| Standing Points and tie-break values | Fields in projection `standings[]` | Display the supplied values exactly. Do not recompute from Match history. |
| Qualifying Fixture order and Teams | Projection `fixtures[]` | Preserve projection order and `team_ids`. |
| Fixture progress | Projection Fixture `status`, `skip_reason`, and `active_match_id` | Show the supplied state. Do not select or announce the next Fixture. |
| Series progress and result | Projection Fixture `matches[]`, `status`, and `administrative_series_win` | Summarize only the supplied Match outcomes and administrative result; do not calculate Series Points. |
| Completed Match history | Projection Fixture `matches[]` across Qualifying and Playoff Fixtures | Flatten only for navigation while preserving phase, Fixture, and Match order. Each item remains linked to its source Fixture. |
| Match summary | Projection Match `match_id`, `outcome`, and `winner_team_id` | Display the supplied outcome and winner. A Double Forfeit is not displayed as a draw. |
| Playoff seeds and bracket | Projection `bracket` | Display `locked`, supplied seed order, Fixture stage, Teams, state, replacement, and resolved Team exactly as supplied. Never seed or advance a Team. |
| Tournament Champion | Projection `champion` plus the matching projected Team | Display only when non-null. A standings leader is never labeled Tournament Champion. |
| Terminal reason | Projection `completion_reason` and `status` | Map known codes to fixed audience copy. Unknown codes use neutral copy and remain observable to the organizer. |
| Match pending organizer review | Projection `security_review.fixture_id` and `security_review.match_id` | The allowlist may identify only the affected Fixture and Match. It excludes `suspected_team_id`, `suspected_team_ids`, and any evidence. |
| Replay identity and result | Verified `match_terminal` record `phase`, `fixture_id`, `match_id`, `match_ordinal`, `team_ids`, `outcome`, `winner_team_id`, `round_wins`, and `protocol_forfeit_team_id` | Expose only after the Match appears completed in the current projection. Copy fields; do not rescore. |
| Replay completed Rounds | Verified record `rounds[]` | Preserve recorded order and display each Round's `turn`, moves, and `winner_team_id`. |
| Replay protocol faults | Verified record `faults` | Display normalized fault kind and Turn only. Never fetch or expose diagnostic evidence. |

The browser contract excludes Match seeds, bot-visible seeds, Bot Positions,
artifact digests, raw move-history strings, operator identity and notes,
Security Violation suspects, Security Violation evidence links, and all
Operational Telemetry. The replay endpoint selects fields from one verified
terminal record rather than returning a Competition Record file wholesale.

## Process and implementation boundary

The `present` command starts a dedicated loopback HTTP process. The Tournament
Runner remains a producer of files and never imports, starts, or calls the
presentation server. The presentation package has three boundaries:

1. A read-only Tournament-store adapter reads `scoreboard.json` and uses the
   existing verified Competition Record loader for replay lookup. It opens no
   run lock and performs no writes.
2. A browser-contract adapter validates the supported Scoreboard Projection
   version and copies allowlisted fields into live and replay responses. It does
   not import scheduler, scoring, standings, bracket-construction, runner, or
   Bot Artifact execution code.
3. A small HTTP server serves immutable bundled assets and same-origin JSON
   endpoints. The browser renders those responses and owns only ephemeral UI
   state such as the selected Match and the time at which it last received a
   valid response.

The endpoints are:

- `GET /api/live`: the latest accepted allowlisted Scoreboard Projection plus a
  presentation-only response revision and freshness metadata; and
- `GET /api/matches/{match_id}/replay`: the allowlisted replay of one completed
  Match, or an explicit unavailable/not-found response.

The response revision may be an ETag over the projection bytes. It is transport
metadata, not a competitive sequence number and is never displayed as one.
The server binds to `127.0.0.1` by default. A non-loopback bind is outside the
first release because there is no authentication or transport security.

## Live update and lifecycle behavior

The browser polls `/api/live` once per second with `If-None-Match`. Polling is
chosen over file watching, server-sent events, or WebSockets because atomic file
replacement is already the runner contract, polling is portable, and no live
connection to the Tournament Runner is required.

For each poll, the presentation process reads the whole projection from its
final path. Atomic replacement means it sees either the prior complete document
or the next complete document. It validates JSON shape and the supported
projection version before publishing the response. A changed valid projection
replaces the browser's complete live view in one render; fields from two
projection generations are never merged.

Lifecycle handling is:

| Runner-published condition | Presentation behavior |
| --- | --- |
| Initial `paused` projection | Render the schedule and standings and say the Tournament is ready or paused. |
| `running` with active Fixtures | Highlight every supplied active Fixture and `active_match_id`; show no uncommitted score. |
| Runner interruption | The last valid projection remains visible. After three missed or failed polls, show a local “updates unavailable” banner and last-received age without changing competitive status. |
| Runner resumption | The next valid atomic projection replaces the stale view and removes the connectivity banner. No inferred transition is inserted. |
| Phase transition | Replace the complete Qualifying Phase view with the new projection state while retaining Qualifying history and displaying the supplied bracket. Never construct a bracket client-side. |
| `awaiting_security_ruling` | Show “Paused for organizer review” and identify the affected Match only if supplied. Do not expose suspected Team IDs or evidence. |
| `complete` with `champion` | Present the matching projected Team as Tournament Champion and keep all history and replay available. |
| `complete` without `champion` | Show the mapped completion reason and explicitly state that no Tournament Champion was declared. |
| `aborted` | Show that the Tournament was aborted without a Tournament Champion and retain all previously committed facts. Do not expose organizer identity or free-text note. |

An absent projection at startup produces a waiting page and retries. An
unsupported version, invalid JSON, invalid required shape, or read failure does
not clear a previously accepted view. Instead the server retains the last valid
projection in memory, returns a degraded-health marker, and logs a concise local
diagnostic. With no last valid view, it returns a service-unavailable response
and the page explains that presentation data is not yet available.

The page's received time, retry count, ETag, and connectivity state are
presentation diagnostics. They are never written to the Tournament directory
or described as Competition Records or Operational Telemetry.

## Replay behavior

Replay is available only for a Match listed in the current projection's
completed Match summaries and backed by one verified `match_terminal`
Competition Record. The presentation process uses the existing storage loader,
which verifies record envelopes, sequence, hashes, and canonical JSON, then
selects the terminal record by exact Match ID. It never launches a Bot Artifact
and never treats an incomplete Match Attempt as replayable.

Each replay frame is a committed completed Round. A frame displays:

- the one-based audience label “Round N”;
- the record's zero-based `turn` value explicitly labeled “Turn”; and
- each Team's recorded move and the recorded Round winner or draw.

The UI must not call a Turn a Round. Ordinarily each successful Turn produces
one Round. When a protocol fault occurs, the fault's Turn has no completed Round
and appears after the final Round as a terminal Match event. For example, six
recorded Rounds with a fault at Turn `6` are displayed as six Round frames
followed by “Protocol fault on Turn 6.”

For a protocol forfeit, replay shows all committed Rounds, the normalized fault
kind and Turn for the faulting Team, and the recorded Match winner. It does not
show stderr, measured timing, raw output, or diagnostic text. For a Double
Forfeit, replay shows the committed Rounds followed by both normalized faults
on their shared Turn and labels the Match outcome “Double Forfeit”; it declares
no Match winner and does not relabel the outcome as a draw.

If record verification fails, the selected replay becomes unavailable and the
live projection remains visible. The server logs the verification failure
without returning raw file contents or evidence to the browser.

## Runtime, assets, dependencies, and browser support

The supported runtime is the repository's Python 3.9 environment on the same
local machine that can read the Tournament directory. The launch contract is:

```text
.venv/bin/python -m rps_runner.tournament_cli present \
  --directory TOURNAMENT_DIRECTORY [--host 127.0.0.1] [--port 8000]
```

The installed equivalent is `rps-tournament present`. The command validates the
directory, starts even when `scoreboard.json` has not yet been created, prints
its URL, and exits non-zero for an unreadable directory, invalid bind address,
or unavailable port.

HTML, CSS, and JavaScript are package resources shipped with `rps_runner`. The
browser implementation uses standards-based HTML, CSS, and small vanilla
JavaScript modules. It has no CDN, network, framework, asset compilation, or
runtime package dependency beyond Python's standard library. Assets use content
types and cache rules set by the presentation server; the HTML shell and live
JSON are not persistently cached.

The support target is the latest two major versions, at implementation and
release time, of desktop Chrome/Chromium, Firefox, and Safari. The page remains
usable at 1280×720 for a shared display and at a 375 CSS-pixel viewport for an
organizer's phone. JavaScript is required for live replacement and replay;
without it, the shell explains the requirement rather than showing stale
competitive data.

Browser automation is a development-only dependency, pinned separately from the
Python runtime. It does not enter the offline event-day asset path. All runtime
assets and Python dependencies must be installable during the repository's
existing offline preparation workflow.

## Accessibility and audience safety

The page uses semantic tables for standings, semantic headings and lists for
Fixtures, text labels in addition to color, visible keyboard focus, a polite
status announcement for connectivity changes, and a replay control operable by
keyboard. Motion respects `prefers-reduced-motion`. Team Display Names and all
record-derived strings are inserted as text, never as HTML.

No authentication exists in the first release, so every browser response is
treated as audience-visible. The allowlist is the security boundary that keeps
operator notes, suspected Team identities, evidence links, seeds, Bot Artifact
details, and Operational Telemetry out of browser traffic.

## Verification approach

Implementation is accepted through four complementary seams:

1. Python unit tests feed complete projection fixtures into the browser-contract
   adapter and assert exact allowlisted output for paused, running, awaiting
   review, Playoff Phase, complete, completed-without-champion, and aborted
   states. Tests also prove forbidden fields never cross the adapter.
2. HTTP integration tests replace `scoreboard.json` atomically while polling and
   verify ETag behavior, whole-generation replacement, missing/corrupt/version-
   mismatched input, last-good retention, recovery, bind failures, path
   traversal rejection, and read-only operation.
3. Replay contract tests use verified terminal records for an ordinary Match,
   protocol forfeit, and Double Forfeit. They prove completed Round order, Turn
   labeling, fault placement, unavailable uncommitted Matches, and exclusion of
   seeds, artifact data, evidence, and Operational Telemetry.
4. Pinned browser tests exercise initial load, a live Match-boundary update,
   phase transition, organizer-review banner, completion, abort, responsive
   layout, keyboard replay, reduced motion, and safe rendering of hostile Team
   Display Names. Release verification runs these tests in Chromium and performs
   a manual smoke check in the supported Firefox and Safari versions.

The full existing Python suite runs at the end to demonstrate that adding the
presentation consumer did not change Tournament execution or competitive
records. Event rehearsal starts the runner and presentation as separate
processes, interrupts and resumes each independently, and confirms that
Competition Record bytes and reconstructed Tournament state remain unchanged.

## Explicit non-decisions for later releases

The first release does not add a live per-Turn projection, remote audience
hosting, authentication, presenter controls, multiple Tournament selection,
downloadable record archives, commentary, telemetry dashboards, or a new public
schema owned by the Tournament Runner. Any of those requires a separate design
that preserves the authority boundary in this document.
