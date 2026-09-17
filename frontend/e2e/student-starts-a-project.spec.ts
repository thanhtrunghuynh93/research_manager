/**
 * A student brings their own work into the system, end to end in a browser (PROJ-07).
 *
 * The chain this walks is the one `use_cases.md` §8.1 used to call broken from the other end: a
 * report can only become due if a project exists and someone is on it. Until now both halves were
 * the professor's, so a student with a project of their own had to ask for it to be created before
 * anything they did could be reported on.
 *
 * Two things here no unit test can show. The first is that a student's project is **active on
 * creation** — there is no activate button, and its absence is the whole point, because a proposed
 * project derives no obligation. The second is that joining is bounded: the panel lists only what
 * the professor opened, and the demo dataset opens exactly one.
 *
 * Runs as `STUDENT_SOLO` rather than the usual `STUDENT`: this spec gives an account another
 * project, and the specs share one dataset, so using the account whose report tabs
 * `submit-weekly-package` counts is how a suite-order failure gets written.
 */
import { expect, test } from "@playwright/test";

import { STUDENT_SOLO, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

const TITLE = `Spectral clustering ${Date.now()}`;

test("a student creates a project and it is active without anyone activating it", async ({
  page,
}) => {
  await signIn(page, STUDENT_SOLO);

  await page.getByRole("link", { name: /^projects$/i }).click();
  await expect(page.getByTestId("project-list")).toBeVisible();

  await page.getByLabel(/^title$/i).fill(TITLE);
  await page.getByRole("button", { name: /create project/i }).click();

  await page.getByRole("link", { name: TITLE }).click();
  await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();

  // Active already. The professor's project offers this button at this point; a student's must not,
  // because there is no second party whose assent it would record.
  await expect(page.getByTestId("activate-project")).toHaveCount(0);
  await expect(page.getByText(/^active$/i).first()).toBeVisible();

  // Their own record, theirs to correct (AUTH-07) — but not its standing.
  await expect(page.getByTestId("project-fields")).toBeVisible();
  await expect(page.getByTestId("project-status-controls")).toHaveCount(0);
});

test("a student joins a project the professor opened, and can then leave it", async ({ page }) => {
  await signIn(page, STUDENT_SOLO);
  await page.goto("/projects");

  const panel = page.getByTestId("joinable");
  await expect(panel).toBeVisible();

  const title = await panel.locator("li").first().locator("p").first().textContent();
  await panel.getByTestId("join-project").first().click();

  // Joining is what makes the project readable at all: before it, the page would have been a 404.
  await page.getByRole("link", { name: title!.trim() }).click();
  await expect(page.getByTestId("membership-controls")).toBeVisible();

  await page.getByTestId("leave-project").click();
  await expect(page.getByTestId("leave-project")).toHaveCount(0);
});
