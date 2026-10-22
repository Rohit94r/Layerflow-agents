import { defineConfig, devices } from "@playwright/test";

// Runs the demo script (docs/demo-script.md) against an already running stack, e.g.
//   MODEL_PROVIDER=mock docker compose up -d
//   E2E_BASE_URL=http://localhost:3000 E2E_EMAIL=admin@example.com E2E_PASSWORD=… npx playwright test
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
});
