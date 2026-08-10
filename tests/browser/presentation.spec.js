const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

function projection(overrides = {}) {
  return {
    version: 1,
    tournament_id: "audience-cup",
    status: "paused",
    phase: "qualifying",
    teams: [
      { team_id: "alpha", display_name: "Alpha" },
      { team_id: "beta", display_name: "Beta" },
      { team_id: "gamma", display_name: "Gamma" },
      { team_id: "delta", display_name: "Delta" },
    ],
    standings: [
      {
        team_id: "alpha",
        standing_points: 6,
        series_wins: 2,
        match_differential: 3,
        round_differential: 8,
        protocol_fault_forfeits: 0,
        tie_break_key: "11",
      },
      {
        team_id: "beta",
        standing_points: 3,
        series_wins: 1,
        match_differential: 1,
        round_differential: 2,
        protocol_fault_forfeits: 0,
        tie_break_key: "22",
      },
    ],
    fixtures: [
      {
        fixture_id: "qualifying-0001",
        team_ids: ["alpha", "beta"],
        status: "scheduled",
        matches: [],
      },
      {
        fixture_id: "qualifying-0002",
        team_ids: ["gamma", "delta"],
        status: "scheduled",
        matches: [],
      },
    ],
    champion: null,
    ...overrides,
  };
}

function replaceProjection(directory, value) {
  const replacement = path.join(directory, ".scoreboard.next");
  fs.writeFileSync(replacement, JSON.stringify(value));
  fs.renameSync(replacement, path.join(directory, "scoreboard.json"));
}

function canonicalJson(value) {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map(
      (key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    ).join(",")}}`;
  }
  return JSON.stringify(value);
}

function terminalRecord({
  matchId,
  matchOrdinal,
  outcome = "win",
  winnerTeamId = "alpha",
  faults = { alpha: null, beta: null },
  protocolForfeitTeamId = null,
}) {
  return {
    type: "match_terminal",
    phase: "qualifying",
    fixture_id: "qualifying-0001",
    match_id: matchId,
    match_ordinal: matchOrdinal,
    team_ids: ["alpha", "beta"],
    outcome,
    winner_team_id: winnerTeamId,
    round_wins: { alpha: 1, beta: 0 },
    protocol_forfeit_team_id: protocolForfeitTeamId,
    moves: { alpha: "RP", beta: "SP" },
    rounds: [
      {
        turn: 0,
        moves: { alpha: "R", beta: "S" },
        winner_team_id: "alpha",
      },
      {
        turn: 1,
        moves: { alpha: "P", beta: "P" },
        winner_team_id: null,
      },
    ],
    faults,
    match_seed: "secret-seed",
    bot_positions: { a: "alpha", b: "beta" },
    artifact_digests: { alpha: "secret-alpha", beta: "secret-beta" },
  };
}

function writeCompetitionRecords(directory, records) {
  const recordsDirectory = path.join(directory, "records");
  fs.mkdirSync(recordsDirectory);
  const hashes = records.map((record, index) => {
    const sequence = index + 1;
    const contentHash = crypto.createHash("sha256")
      .update(canonicalJson({ record, sequence }))
      .digest("hex");
    fs.writeFileSync(
      path.join(recordsDirectory, `${String(sequence).padStart(8, "0")}.json`),
      canonicalJson({ content_hash: contentHash, record, sequence })
    );
    return contentHash;
  });
  const recordsHash = crypto.createHash("sha256")
    .update(canonicalJson(hashes))
    .digest("hex");
  fs.writeFileSync(
    path.join(directory, "records.index.json"),
    canonicalJson({ count: records.length, records_hash: recordsHash })
  );
}

async function startPresentation() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "rps-presentation-"));
  const child = spawn(
    path.resolve(".venv/bin/python"),
    [
      "-m",
      "rps_runner.tournament_cli",
      "present",
      "--directory",
      directory,
      "--port",
      "0",
    ],
    { cwd: path.resolve(".") }
  );
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += chunk.toString(); });
  const url = await new Promise((resolve, reject) => {
    let stdout = "";
    const timeout = setTimeout(
      () => reject(new Error(`presentation did not start: ${stderr}`)),
      5_000
    );
    child.once("exit", (code) => {
      clearTimeout(timeout);
      reject(new Error(`presentation exited ${code}: ${stderr}`));
    });
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
      const newline = stdout.indexOf("\n");
      if (newline !== -1) {
        clearTimeout(timeout);
        resolve(stdout.slice(0, newline));
      }
    });
  });
  return {
    directory,
    url,
    async stop() {
      child.kill("SIGTERM");
      await new Promise((resolve) => child.once("exit", resolve));
      fs.rmSync(directory, { recursive: true, force: true });
    },
  };
}

test("shows Match-boundary progress, committed history, and supplied bracket order", async ({ page }) => {
  const presentation = await startPresentation();
  try {
    replaceProjection(presentation.directory, projection({
      status: "running",
      fixtures: [
        {
          fixture_id: "qualifying-0001",
          team_ids: ["alpha", "beta"],
          status: "active",
          active_match_id: "qualifying-0001-match-1",
          matches: [],
        },
        projection().fixtures[1],
      ],
    }));
    await page.goto(presentation.url);

    await expect(page.getByText("Match active: qualifying-0001-match-1")).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Round score");
    await expect(page.getByText("qualifying-0002")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Qualifying Fixtures" }).locator("ol")
    ).toBeVisible();

    replaceProjection(presentation.directory, projection({
      status: "paused",
      fixtures: [
        {
          fixture_id: "qualifying-0001",
          team_ids: ["alpha", "beta"],
          status: "in_progress",
          matches: [
            {
              match_id: "qualifying-0001-match-1",
              outcome: "double_forfeit",
              winner_team_id: null,
            },
          ],
        },
        projection().fixtures[1],
      ],
    }));

    const history = page.getByRole("region", { name: "Match history" });
    await expect(history).toContainText("qualifying-0001-match-1");
    await expect(history).toContainText("Double Forfeit");
    await expect(history).not.toContainText("Draw");

    replaceProjection(presentation.directory, projection({
      phase: "playoff",
      fixtures: [
        {
          fixture_id: "qualifying-0001",
          team_ids: ["alpha", "beta"],
          status: "complete",
          matches: [
            {
              match_id: "qualifying-0001-match-1",
              outcome: "win",
              winner_team_id: "alpha",
            },
          ],
        },
      ],
      bracket: {
        locked: true,
        seeds: [
          { seed: 2, team_id: "beta" },
          { seed: 1, team_id: "alpha" },
        ],
        fixtures: [
          {
            fixture_id: "playoff-semifinal-2",
            stage: "semifinal",
            team_ids: ["beta", "gamma"],
            status: "complete",
            matches: [],
            administrative_series_win: {
              winner_team_id: "gamma",
              reason_code: "opponent_disqualified",
            },
          },
          {
            fixture_id: "playoff-final",
            stage: "final",
            team_ids: ["alpha", "gamma"],
            status: "scheduled",
            matches: [],
            bracket_position_replacement: {
              disqualified_team_id: "beta",
              reinstated_team_id: "gamma",
              source_fixture_id: "playoff-semifinal-2",
              reason_code: "disqualified_advancer",
            },
          },
        ],
      },
    }));

    const bracket = page.getByRole("region", { name: "Playoff bracket" });
    await expect(bracket).toContainText("Bracket locked");
    await expect(bracket.locator(".seed").nth(0)).toContainText("Seed 2");
    await expect(bracket.locator(".seed").nth(1)).toContainText("Seed 1");
    await expect(bracket.locator(".fixture-card").nth(0)).toContainText("playoff-semifinal-2");
    await expect(bracket.locator(".fixture-card").nth(1)).toContainText("playoff-final");
    await expect(bracket.locator(".fixture-card").nth(0)).toContainText("Complete");
    await expect(bracket.locator(".fixture-card").nth(0)).not.toContainText("Tournament complete");
    await expect(bracket).toContainText("Gamma replaced disqualified Team Beta");
  } finally {
    await presentation.stop();
  }
});

test("uses safe audience copy while organizer review is pending", async ({ page }) => {
  const presentation = await startPresentation();
  try {
    replaceProjection(presentation.directory, projection({
      status: "awaiting_security_ruling",
      security_review: {
        fixture_id: "qualifying-0001",
        match_id: "qualifying-0001-match-1",
        suspected_team_id: "suspected-secret-team",
        evidence: "secret evidence",
      },
    }));
    await page.goto(presentation.url);

    const outcome = page.getByRole("region", { name: "Tournament outcome" });
    await expect(outcome).toContainText("Paused for organizer review");
    await expect(outcome).toContainText("qualifying-0001-match-1");
    await expect(page.locator("body")).not.toContainText("suspected-secret-team");
    await expect(page.locator("body")).not.toContainText("secret evidence");
  } finally {
    await presentation.stop();
  }
});

test("declares only the supplied Tournament Champion", async ({ page }) => {
  const presentation = await startPresentation();
  try {
    replaceProjection(presentation.directory, projection({
      status: "complete",
      phase: "playoff",
      champion: "beta",
    }));
    await page.goto(presentation.url);

    const outcome = page.getByRole("region", { name: "Tournament outcome" });
    await expect(outcome).toContainText("Tournament Champion");
    await expect(outcome).toContainText("Beta");
    await expect(outcome).not.toContainText("Alpha");
  } finally {
    await presentation.stop();
  }
});

test("shows completion without a Champion and abort while retaining history", async ({ page }) => {
  const presentation = await startPresentation();
  const committedFixture = {
    fixture_id: "qualifying-0001",
    team_ids: ["alpha", "beta"],
    status: "complete",
    matches: [
      {
        match_id: "qualifying-0001-match-1",
        outcome: "win",
        winner_team_id: "alpha",
      },
    ],
  };
  try {
    replaceProjection(presentation.directory, projection({
      status: "complete",
      phase: "playoff",
      fixtures: [committedFixture],
      completion_reason: "no_eligible_teams",
    }));
    await page.goto(presentation.url);

    const outcome = page.getByRole("region", { name: "Tournament outcome" });
    await expect(outcome).toContainText("No Tournament Champion was declared");
    await expect(outcome).toContainText("No eligible Teams remained");
    await expect(page.getByRole("region", { name: "Match history" })).toContainText(
      "qualifying-0001-match-1"
    );

    replaceProjection(presentation.directory, projection({
      status: "aborted",
      fixtures: [committedFixture],
      completion_reason: "operator_requested",
      operator_abort: {
        organizer_id: "organizer-secret",
        note: "secret note",
      },
    }));

    await expect(outcome).toContainText("Tournament aborted");
    await expect(outcome).toContainText("No Tournament Champion was declared");
    await expect(page.getByRole("region", { name: "Match history" })).toContainText(
      "qualifying-0001-match-1"
    );
    await expect(page.locator("body")).not.toContainText("organizer-secret");
    await expect(page.locator("body")).not.toContainText("secret note");
  } finally {
    await presentation.stop();
  }
});

test("replays ordinary Rounds and terminal faults with keyboard controls", async ({ page }) => {
  const presentation = await startPresentation();
  const ordinaryId = "qualifying-0001-match-1";
  const forfeitId = "qualifying-0001-match-2";
  const doubleForfeitId = "qualifying-0001-match-3";
  const unavailableId = "qualifying-0001-match-4";
  const summaries = [
    { match_id: ordinaryId, outcome: "win", winner_team_id: "alpha" },
    { match_id: forfeitId, outcome: "win", winner_team_id: "alpha" },
    { match_id: doubleForfeitId, outcome: "double_forfeit", winner_team_id: null },
    { match_id: unavailableId, outcome: "draw", winner_team_id: null },
  ];
  try {
    replaceProjection(presentation.directory, projection({
      fixtures: [
        {
          fixture_id: "qualifying-0001",
          team_ids: ["alpha", "beta"],
          status: "complete",
          matches: summaries,
        },
      ],
    }));
    writeCompetitionRecords(presentation.directory, [
      terminalRecord({ matchId: ordinaryId, matchOrdinal: 1 }),
      terminalRecord({
        matchId: forfeitId,
        matchOrdinal: 2,
        protocolForfeitTeamId: "beta",
        faults: {
          alpha: null,
          beta: { kind: "malformed_response", turn: 2 },
        },
      }),
      terminalRecord({
        matchId: doubleForfeitId,
        matchOrdinal: 3,
        outcome: "double_forfeit",
        winnerTeamId: null,
        faults: {
          alpha: { kind: "timeout", turn: 2 },
          beta: { kind: "malformed_response", turn: 2 },
        },
      }),
    ]);
    await page.goto(presentation.url);

    const replay = page.getByRole("region", { name: "Match replay" });
    const ordinaryButton = page.getByRole("button", { name: `Replay Match ${ordinaryId}` });
    await ordinaryButton.focus();
    await page.keyboard.press("Enter");
    await expect(replay).toContainText("Round 1");
    await expect(replay).toContainText("Turn 0");
    await expect(replay).toContainText("Alpha: Rock");
    await expect(replay).toContainText("Round winner: Alpha");
    await page.keyboard.press("ArrowRight");
    await expect(replay).toContainText("Round 2");
    await expect(replay).toContainText("Turn 1");
    await expect(replay).toContainText("Drawn Round");
    await page.keyboard.press("Escape");
    await expect(replay).toBeHidden();

    await page.getByRole("button", { name: `Replay Match ${forfeitId}` }).click();
    await expect(replay).toContainText("Round 1");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(replay).toContainText("Protocol fault on Turn 2");
    await expect(replay).toContainText("Beta: malformed response");
    await expect(replay).toContainText("Winner: Alpha");
    await page.getByRole("button", { name: "Close replay" }).click();

    await page.getByRole("button", { name: `Replay Match ${doubleForfeitId}` }).click();
    await expect(replay).toContainText("Round 1");
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");
    await expect(replay).toContainText("Double Forfeit");
    await expect(replay).toContainText("Alpha: timeout");
    await expect(replay).toContainText("Beta: malformed response");
    await expect(replay).not.toContainText("Winner:");
    await expect(replay).not.toContainText("Outcome: Draw");
    await page.getByRole("button", { name: "Close replay" }).click();

    await page.getByRole("button", { name: `Replay Match ${unavailableId}` }).click();
    await expect(replay).toContainText("Replay unavailable");
    await expect(page.getByRole("region", { name: "Match history" })).toContainText(ordinaryId);
    await expect(page.locator("body")).not.toContainText("secret-seed");
    await expect(page.locator("body")).not.toContainText("secret-alpha");

    await page.getByRole("button", { name: "Close replay" }).click();
    await page.route(`**/api/matches/${ordinaryId}/replay`, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.continue();
    });
    await page.getByRole("button", { name: `Replay Match ${ordinaryId}` }).click();
    await page.getByRole("button", { name: `Replay Match ${forfeitId}` }).click();
    await expect(replay).toContainText(forfeitId);
    await expect(replay).toContainText("Round 1");
    await page.waitForTimeout(400);
    await expect(replay).toContainText(forfeitId);
  } finally {
    await presentation.stop();
  }
});
