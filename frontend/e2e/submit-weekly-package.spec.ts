/**
 * REP-02, REP-03, REP-05: one weekly package, one tab per required project, one submission.
 *
 * The browser-level proof that a student can actually get their week in. The service tests cover
 * the rules; this covers the thing that would make them irrelevant — a form nobody can submit.
 */
import { expect, test } from "@playwright/test";

import { signIn, STUDENT } from "./helpers";

test("a student sees this week, opens it, drafts it, and submits once", async ({ page }) => {
  await signIn(page, STUDENT);

  await expect(page.getByRole("heading", { level: 1, name: /this week/i })).toBeVisible();
  // REP-01: the deadline is stated in the workspace timezone, at 23:59.
  await expect(page.getByTestId("next-deadline")).toContainText("23:59");

  await page.getByRole("link", { name: /start this week|open this week/i }).click();
  await expect(page.getByRole("heading", { name: /weekly package/i })).toBeVisible();

  const work = page.getByLabel(/work performed/i).first();
  await work.fill("Ran the hybrid fusion baseline and recorded nDCG@10 with a bootstrap interval.");
  await page
    .getByLabel(/results and research learning/i)
    .first()
    .fill("Fusion adds 1.4 points.");

  // REP-04: autosave is visible, so the student knows the draft is safe before they submit.
  await expect(page.getByText(/saved/i)).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: /submit package/i }).click();
  await expect(page.getByText(/submitted as version/i)).toBeVisible();
});

test("a student on two projects gets a tab for each required entry", async ({ page }) => {
  // AC-01: one package, two entries, assessed separately.
  await signIn(page, STUDENT);
  await page.getByRole("link", { name: /start this week|open this week/i }).click();

  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(2);
});

test("a student cannot reach the professor's overview", async ({ page }) => {
  // AUTH-02: the guard redirects, and the API would refuse anyway.
  await signIn(page, STUDENT);

  await page.goto("/overview");

  await expect(page).toHaveURL(/\/me$/);
});
