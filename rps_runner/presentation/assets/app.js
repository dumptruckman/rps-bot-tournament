"use strict";

const liveView = document.querySelector("#live-view");
const title = document.querySelector("#tournament-name");
const warning = document.querySelector("#freshness-warning");
let etag = null;
let missedPolls = 0;
let lastValidAt = null;
let lastFreshness = null;

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
    .forEach((label) => headerRow.append(element("th", label)));
  head.append(headerRow);
  const body = element("tbody");
  tournament.standings.forEach((standing, index) => {
    const row = element("tr");
    const projectedTeam = tournament.teams.find(
      (team) => team.team_id === standing.team_id
    );
    const teamLabel = projectedTeam !== undefined && projectedTeam.status === "disqualified"
      ? `${teamName(teamNames, standing.team_id)} — Disqualified`
      : teamName(teamNames, standing.team_id);
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
}

function recordFailure() {
  missedPolls += 1;
  if (missedPolls < 3) return;
  const age = lastValidAt === null
    ? "No presentation data has been received yet."
    : `Last update received ${Math.max(0, Math.floor((Date.now() - lastValidAt) / 1000))} seconds ago.`;
  warning.textContent = `Updates unavailable. ${age}`;
  warning.hidden = false;
}

function recordSuccess() {
  missedPolls = 0;
  lastValidAt = Date.now();
  warning.hidden = true;
  warning.textContent = "";
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
    lastFreshness = false;
    recordFailure();
  } finally {
    setTimeout(poll, 1000);
  }
}

poll();
