const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "tests/browser",
  timeout: 20_000,
  expect: { timeout: 6_000 },
  fullyParallel: false,
  workers: 1,
  use: {
    browserName: "chromium",
    headless: true,
  },
});
