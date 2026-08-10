const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
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
