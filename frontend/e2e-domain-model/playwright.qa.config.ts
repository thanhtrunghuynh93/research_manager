import { defineConfig, devices } from "@playwright/test";

/**
 * The domain-model pass described in ../../test/QA-REPORT-domain-model.md.
 *
 * Separate from playwright.config.ts because these specs run serially against a *fresh* workspace
 * they build themselves, rather than against the seeded demo dataset: several of the checks are
 * only true of a workspace nobody has touched ("leaving your only workspace is refused", "the roll
 * holds one professor"). They share state through state.json, written as they go.
 *
 *   cd frontend
 *   PROF_TOKEN=<from `app.cli identity bootstrap`> \
 *     npx playwright test --config=e2e-domain-model/playwright.qa.config.ts
 */
export default defineConfig({
  testDir: ".",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"], ["json", { outputFile: "results.json" }]],
  use: { baseURL: "http://localhost:8020", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
