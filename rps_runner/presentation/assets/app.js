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
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function render(tournament) {
  const teamNames = new Map(
    tournament.teams.map((team) => [team.team_id, team.display_name])
  );
  title.textContent = tournament.tournament_id;
  document.title = `${tournament.tournament_id} standings`;

  const section = element("section");
  section.setAttribute("aria-labelledby", "standings-title");
  const summary = element("div", undefined, "summary");
  summary.append(
    element("p", labels[tournament.status] || tournament.status, "status"),
    element("p", labels[tournament.phase] || tournament.phase, "phase")
  );
  const heading = element("h2", "Qualifying standings");
  heading.id = "standings-title";

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
    const cells = [
      index + 1,
      teamNames.get(standing.team_id) || standing.team_id,
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
  section.append(summary, heading, table);
  liveView.replaceChildren(section);
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
