"use strict";

const liveView = document.querySelector("#live-view");
const title = document.querySelector("#tournament-name");
const warning = document.querySelector("#freshness-warning");
const connectivityStatus = document.querySelector("#connectivity-status");
const replayPanel = document.querySelector("#replay-panel");
let etag = null;
let missedPolls = 0;
let lastValidAt = null;
let lastFreshness = null;
let currentTournament = null;
let replayState = null;
let replayOpener = null;
let replayRequest = 0;
let connectivityUnavailable = false;

const labels = {
  paused: "Tournament paused",
  running: "Tournament running",
  awaiting_security_ruling: "Paused for organizer review",
  complete: "Tournament complete",
  aborted: "Tournament aborted",
  qualifying: "Qualifying Phase",
  playoff: "Playoff Phase",
  win: "Win",
  draw: "Draw",
  double_forfeit: "Double Forfeit",
  semifinal: "Semifinal",
  final: "Final",
};

const completionMessages = {
  no_eligible_teams: "No eligible Teams remained.",
  all_finalists_disqualified: "All Playoff finalists were disqualified.",
  operator_requested: "The Tournament was stopped by the organizer.",
};

const fixtureLabels = {
  scheduled: "Scheduled",
  active: "Active",
  in_progress: "In progress",
  complete: "Complete",
  skipped: "Skipped",
};

const moveLabels = { R: "Rock", P: "Paper", S: "Scissors" };

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function namedSection(name, id, className) {
  const section = element("section", undefined, className);
  section.setAttribute("aria-labelledby", id);
  const heading = element("h2", name);
  heading.id = id;
  section.append(heading);
  return section;
}

function teamName(teamNames, teamId) {
  if (teamId === null) return "Open bracket position";
  return teamNames.get(teamId) || teamId;
}

function displayCode(value) {
  return value.replaceAll("_", " ");
}

function renderOverview(tournament) {
  const summary = element("section", undefined, "summary");
  summary.setAttribute("aria-label", "Tournament status");
  summary.append(
    element("p", labels[tournament.status] || "Tournament status unavailable", "status"),
    element("p", labels[tournament.phase] || "Tournament phase unavailable", "phase")
  );
  return summary;
}

function renderOutcome(tournament, teamNames) {
  const shouldRender = tournament.status === "awaiting_security_ruling"
    || tournament.status === "complete"
    || tournament.status === "aborted"
    || tournament.champion !== null;
  if (!shouldRender) return null;

  const section = namedSection(
    "Tournament outcome",
    "outcome-title",
    `outcome outcome-${tournament.status}`
  );
  if (tournament.status === "awaiting_security_ruling") {
    section.append(element("p", "Paused for organizer review", "outcome-lead"));
    if (tournament.security_review !== undefined) {
      section.append(
        element(
          "p",
          `Reviewing Match ${tournament.security_review.match_id} in Fixture ${tournament.security_review.fixture_id}.`
        )
      );
    } else {
      section.append(element("p", "Match results will resume after organizer review."));
    }
    return section;
  }

  if (tournament.champion !== null) {
    section.append(
      element("p", "Tournament Champion", "champion-label"),
      element("p", teamName(teamNames, tournament.champion), "champion-name")
    );
    return section;
  }

  if (tournament.status === "aborted") {
    section.append(element("p", "Tournament aborted", "outcome-lead"));
  } else {
    section.append(element("p", "Tournament complete", "outcome-lead"));
  }
  section.append(element("p", "No Tournament Champion was declared."));
  section.append(
    element(
      "p",
      completionMessages[tournament.completion_reason]
        || "The Tournament ended without a declared Champion."
    )
  );
  return section;
}

function fixtureCard(fixture, teamNames) {
  const card = element("article", undefined, `fixture-card status-${fixture.status}`);
  card.append(
    element("h3", fixture.fixture_id),
    element(
      "p",
      fixture.team_ids.map((teamId) => teamName(teamNames, teamId)).join(" vs "),
      "fixture-teams"
    ),
    element(
      "p",
      fixtureLabels[fixture.status] || displayCode(fixture.status),
      "fixture-status"
    )
  );
  if (fixture.active_match_id !== undefined) {
    card.append(element("p", `Match active: ${fixture.active_match_id}`, "active-match"));
  } else if (fixture.status === "in_progress") {
    card.append(element("p", "Between committed Matches", "match-boundary"));
  }
  if (fixture.skip_reason !== undefined) {
    const reason = fixture.skip_reason === "teams_disqualified"
      ? "Teams disqualified"
      : displayCode(fixture.skip_reason);
    card.append(element("p", `Skip reason: ${reason}`));
  }
  if (fixture.administrative_series_win !== undefined) {
    const result = fixture.administrative_series_win;
    card.append(
      element(
        "p",
        `Administrative Series Win: ${teamName(teamNames, result.winner_team_id)} (${displayCode(result.reason_code)})`,
        "administrative-result"
      )
    );
  }
  if (fixture.resolved_team_id !== undefined) {
    card.append(
      element("p", `Resolved Team: ${teamName(teamNames, fixture.resolved_team_id)}`)
    );
  }
  if (fixture.bracket_position_replacement !== undefined) {
    const replacement = fixture.bracket_position_replacement;
    const replacementText = replacement.reinstated_team_id === null
      ? `Bracket position vacated after Team ${teamName(teamNames, replacement.disqualified_team_id)} was disqualified`
      : `${teamName(teamNames, replacement.reinstated_team_id)} replaced disqualified Team ${teamName(teamNames, replacement.disqualified_team_id)}`;
    card.append(
      element(
        "p",
        `${replacementText} from ${replacement.source_fixture_id} (${displayCode(replacement.reason_code)}).`,
        "bracket-replacement"
      )
    );
  }
  return card;
}

function fixtureGrid(fixtures, teamNames) {
  const grid = element("ol", undefined, "fixture-grid");
  fixtures.forEach((fixture) => {
    const item = element("li");
    item.append(fixtureCard(fixture, teamNames));
    grid.append(item);
  });
  return grid;
}

function renderQualifyingFixtures(tournament, teamNames) {
  const section = namedSection(
    "Qualifying Fixtures",
    "qualifying-fixtures-title",
    "fixtures"
  );
  section.append(fixtureGrid(tournament.fixtures, teamNames));
  return section;
}

function renderBracket(bracket, teamNames) {
  const section = namedSection("Playoff bracket", "bracket-title", "bracket");
  section.append(
    element(
      "p",
      bracket.locked ? "Bracket locked" : "Bracket not locked",
      bracket.locked ? "bracket-lock locked" : "bracket-lock"
    )
  );

  const seedsHeading = element("h3", "Supplied seeds");
  const seeds = element("ol", undefined, "seed-list");
  bracket.seeds.forEach((seed) => {
    seeds.append(
      element("li", `Seed ${seed.seed}: ${teamName(teamNames, seed.team_id)}`, "seed")
    );
  });
  section.append(seedsHeading, seeds);

  const fixturesHeading = element("h3", "Playoff Fixtures");
  const grid = fixtureGrid(bracket.fixtures, teamNames);
  bracket.fixtures.forEach((fixture, index) => {
    const card = grid.children[index].firstElementChild;
    card.insertBefore(
      element("p", labels[fixture.stage] || displayCode(fixture.stage), "fixture-stage"),
      card.firstChild
    );
  });
  section.append(fixturesHeading, grid);
  return section;
}

function renderHistory(tournament, teamNames) {
  const section = namedSection("Match history", "history-title", "history");
  const list = element("ol", undefined, "history-list");
  const phaseFixtures = [
    ["Qualifying Phase", tournament.fixtures],
    ["Playoff Phase", tournament.bracket === undefined ? [] : tournament.bracket.fixtures],
  ];
  phaseFixtures.forEach(([phase, fixtures]) => {
    fixtures.forEach((fixture) => {
      fixture.matches.forEach((match) => {
        const item = element("li", undefined, "history-item");
        item.append(
          element("p", `${phase} · Fixture ${fixture.fixture_id}`, "history-context"),
          element("h3", match.match_id),
          element("p", `Outcome: ${labels[match.outcome] || displayCode(match.outcome)}`)
        );
        if (match.winner_team_id !== null) {
          item.append(element("p", `Winner: ${teamName(teamNames, match.winner_team_id)}`));
        }
        const replayButton = element("button", `Replay Match ${match.match_id}`, "replay-open");
        replayButton.type = "button";
        replayButton.dataset.matchId = match.match_id;
        replayButton.addEventListener("click", () => openReplay(match.match_id, replayButton));
        item.append(replayButton);
        list.append(item);
      });
    });
  });
  if (list.children.length === 0) {
    section.append(element("p", "No committed Matches yet.", "empty-state"));
  } else {
    section.append(list);
  }
  return section;
}

function renderStandings(tournament, teamNames) {
  const section = namedSection(
    "Qualifying standings",
    "standings-title",
    "standings"
  );
  const table = element("table");
  const caption = element("caption", "Runner-ordered qualifying standings");
  const head = element("thead");
  const headerRow = element("tr");
  ["Rank", "Team", "Standing points", "Series wins", "Match diff.", "Round diff.", "Protocol fault forfeits", "Tie-break key"]
    .forEach((label) => {
      const heading = element("th", label);
      heading.scope = "col";
      headerRow.append(heading);
    });
  head.append(headerRow);
  const body = element("tbody");
  tournament.standings.forEach((standing, index) => {
    const row = element("tr");
    const projectedTeam = tournament.teams.find(
      (team) => team.team_id === standing.team_id
    );
    let teamLabel = teamName(teamNames, standing.team_id);
    if (projectedTeam !== undefined && projectedTeam.status === "disqualified") {
      teamLabel = `${teamLabel} — Disqualified`;
    } else if (projectedTeam !== undefined && projectedTeam.role === "challenger") {
      teamLabel = `${teamLabel} — Challenger (cannot qualify)`;
    }
    const cells = [
      index + 1,
      teamLabel,
      standing.standing_points,
      standing.series_wins,
      standing.match_differential,
      standing.round_differential,
      standing.protocol_fault_forfeits,
      standing.tie_break_key,
    ];
    cells.forEach((value, cellIndex) => {
      const cell = element(cellIndex === 1 ? "th" : "td", String(value));
      if (cellIndex === 1) cell.scope = "row";
      row.append(cell);
    });
    body.append(row);
  });
  table.append(caption, head, body);
  section.append(table);
  return section;
}

function render(tournament) {
  const focusedMatchId = document.activeElement instanceof HTMLElement
    && document.activeElement.classList.contains("replay-open")
    ? document.activeElement.dataset.matchId
    : undefined;
  currentTournament = tournament;
  const teamNames = new Map(
    tournament.teams.map((team) => [team.team_id, team.display_name])
  );
  title.textContent = tournament.tournament_id;
  document.title = `${tournament.tournament_id} Tournament presentation`;

  const content = element("div", undefined, "presentation-grid");
  content.append(renderOverview(tournament));
  const outcome = renderOutcome(tournament, teamNames);
  if (outcome !== null) content.append(outcome);
  content.append(renderQualifyingFixtures(tournament, teamNames));
  if (tournament.bracket !== undefined) {
    content.append(renderBracket(tournament.bracket, teamNames));
  }
  content.append(
    renderHistory(tournament, teamNames),
    renderStandings(tournament, teamNames)
  );
  liveView.replaceChildren(content);
  if (focusedMatchId !== undefined) {
    const replacement = Array.from(document.querySelectorAll(".replay-open"))
      .find((button) => button.dataset.matchId === focusedMatchId);
    if (replacement !== undefined) replacement.focus({ preventScroll: true });
  }
}

function replayTeamNames() {
  return new Map(
    currentTournament === null
      ? []
      : currentTournament.teams.map((team) => [team.team_id, team.display_name])
  );
}

function replayHeader(matchId) {
  const header = element("div", undefined, "replay-header");
  const heading = element("h2", "Match replay");
  heading.id = "replay-title";
  const close = element("button", "Close replay", "replay-close");
  close.type = "button";
  close.addEventListener("click", closeReplay);
  header.append(heading, close, element("p", matchId, "replay-match-id"));
  return header;
}

function showReplayUnavailable(matchId) {
  replayState = null;
  replayPanel.replaceChildren(
    replayHeader(matchId),
    element("p", "Replay unavailable", "replay-unavailable"),
    element(
      "p",
      "This Match does not have one verified committed replay record. The live Tournament view is unchanged."
    )
  );
}

async function openReplay(matchId, opener) {
  const requestId = ++replayRequest;
  replayOpener = opener;
  replayState = null;
  replayPanel.hidden = false;
  replayPanel.replaceChildren(
    replayHeader(matchId),
    element("p", "Loading committed Match replay…", "replay-loading")
  );
  try {
    const response = await fetch(
      `/api/matches/${encodeURIComponent(matchId)}/replay`,
      { cache: "no-store" }
    );
    if (requestId !== replayRequest) return;
    if (!response.ok) {
      showReplayUnavailable(matchId);
      return;
    }
    const payload = await response.json();
    if (requestId !== replayRequest) return;
    const replay = payload.replay;
    replayState = {
      replay,
      events: [
        ...replay.rounds.map((round) => ({ type: "round", value: round })),
        ...(replay.faults.length === 0
          ? []
          : [{ type: "fault", value: replay.faults }]),
      ],
      index: 0,
    };
    renderReplay();
  } catch (_error) {
    if (requestId !== replayRequest) return;
    showReplayUnavailable(matchId);
  }
}

function closeReplay() {
  replayRequest += 1;
  replayPanel.hidden = true;
  replayPanel.replaceChildren();
  replayState = null;
  if (replayOpener !== null && replayOpener.isConnected) replayOpener.focus();
  replayOpener = null;
}

function renderReplay() {
  if (replayState === null) return;
  const { replay, events, index } = replayState;
  const teamNames = replayTeamNames();
  const summary = element("div", undefined, "replay-summary");
  summary.append(
    element(
      "p",
      `Outcome: ${labels[replay.outcome] || displayCode(replay.outcome)}`,
      "replay-outcome"
    )
  );
  if (replay.winner_team_id !== null) {
    summary.append(
      element("p", `Winner: ${teamName(teamNames, replay.winner_team_id)}`, "replay-winner")
    );
  }

  const frame = element("article", undefined, "replay-frame");
  frame.setAttribute("aria-live", "polite");
  if (events.length === 0) {
    frame.append(element("h3", "No completed Rounds"));
  } else {
    const event = events[index];
    if (event.type === "round") {
      const round = event.value;
      frame.append(
        element("h3", `Round ${round.round}`),
        element("p", `Turn ${round.turn}`, "replay-turn")
      );
      const moves = element("ul", undefined, "replay-moves");
      replay.team_ids.forEach((teamId) => {
        moves.append(
          element("li", `${teamName(teamNames, teamId)}: ${moveLabels[round.moves[teamId]]}`)
        );
      });
      frame.append(moves);
      frame.append(
        element(
          "p",
          round.winner_team_id === null
            ? "Drawn Round"
            : `Round winner: ${teamName(teamNames, round.winner_team_id)}`,
          "replay-round-result"
        )
      );
    } else {
      const faults = event.value;
      frame.append(element("h3", `Protocol fault on Turn ${faults[0].turn}`));
      const list = element("ul", undefined, "replay-faults");
      faults.forEach((fault) => {
        list.append(
          element("li", `${teamName(teamNames, fault.team_id)}: ${displayCode(fault.kind)}`)
        );
      });
      frame.append(list);
    }
  }

  const controls = element("div", undefined, "replay-controls");
  const previous = element("button", "Previous", "replay-previous");
  previous.type = "button";
  previous.disabled = index === 0;
  previous.addEventListener("click", () => stepReplay(-1));
  const position = element(
    "p",
    events.length === 0 ? "No replay events" : `${index + 1} of ${events.length}`,
    "replay-position"
  );
  const next = element("button", "Next", "replay-next");
  next.type = "button";
  next.disabled = events.length === 0 || index === events.length - 1;
  next.addEventListener("click", () => stepReplay(1));
  controls.append(previous, position, next);
  replayPanel.replaceChildren(replayHeader(replay.match_id), summary, frame, controls);
}

function stepReplay(offset) {
  if (replayState === null) return;
  const nextIndex = replayState.index + offset;
  if (nextIndex < 0 || nextIndex >= replayState.events.length) return;
  replayState.index = nextIndex;
  renderReplay();
}

document.addEventListener("keydown", (event) => {
  if (replayPanel.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeReplay();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    stepReplay(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    stepReplay(1);
  }
});

function recordFailure() {
  missedPolls += 1;
  if (missedPolls < 3) return;
  const age = lastValidAt === null
    ? "No presentation data has been received yet."
    : `Last update received ${Math.max(0, Math.floor((Date.now() - lastValidAt) / 1000))} seconds ago.`;
  warning.textContent = `Updates unavailable. ${age}`;
  warning.hidden = false;
  if (!connectivityUnavailable) {
    connectivityUnavailable = true;
    connectivityStatus.textContent = "Updates unavailable.";
  }
}

function recordSuccess() {
  missedPolls = 0;
  lastValidAt = Date.now();
  warning.hidden = true;
  warning.textContent = "";
  if (connectivityUnavailable) {
    connectivityUnavailable = false;
    connectivityStatus.textContent = "Updates restored.";
  }
}

async function poll() {
  try {
    const headers = etag === null ? {} : { "If-None-Match": etag };
    const response = await fetch("/api/live", { headers, cache: "no-store" });
    if (response.status === 304) {
      if (lastFreshness === true) recordSuccess();
      else recordFailure();
      return;
    }
    if (!response.ok && response.status !== 503) throw new Error("poll failed");
    const payload = await response.json();
    const receivedEtag = response.headers.get("ETag");
    if (receivedEtag !== null) etag = receivedEtag;
    lastFreshness = payload.freshness.available;
    if (payload.tournament !== undefined) render(payload.tournament);
    if (!payload.freshness.available) {
      recordFailure();
      return;
    }
    recordSuccess();
  } catch (_error) {
    recordFailure();
  } finally {
    setTimeout(poll, 1000);
  }
}

poll();
