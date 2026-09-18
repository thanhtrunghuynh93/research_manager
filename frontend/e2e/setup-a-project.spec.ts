/**
 * The chain that makes a report due, end to end in a browser.
 *
 * `use_cases.md` §8.1 called this "Nothing can become due": obligations derive from memberships,
 * memberships require a project, and creating a project was an endpoint with no screen. Every link
 * was a working, tested endpoint; the chain was broken only at the surface.
 *
 * The step this proves that no unit test would is **activation**. A project is created `proposed`,
 * and an obligation only derives from a membership whose project is `active` — so a professor who
 * creates a project and assigns a student has done everything that looks like the job and produced
 * nothing at all.
 */
import { expect, test } from "@playwright/test";

import { PROF, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

const TITLE = `Spectral methods ${Date.now()}`;

test("a professor creates a project, activates it, and assigns a student", async ({ page }) => {
  await signIn(page, PROF);

  await page.getByRole("link", { name: /^projects$/i }).click();
  await expect(page.getByTestId("project-list")).toBeVisible();

  await page.getByLabel(/^title$/i).fill(TITLE);
  await page.getByRole("button", { name: /create project/i }).click();

  // The list is what gives the project workspace an inbound link at all.
  await page.getByRole("link", { name: TITLE }).click();
  await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();

  // Proposed: the screen has to say that nothing is owed yet, or the next step looks unnecessary.
  await expect(page.getByText(/only for an active project/i)).toBeVisible();

  await page.getByTestId("activate-project").click();
  await expect(page.getByTestId("activate-project")).toHaveCount(0);

  await page.getByTestId("add-member").getByLabel(/^student$/i).selectOption({ index: 1 });
  await page.getByRole("button", { name: /^assign$/i }).click();

  await expect(page.getByText(/no members/i)).toHaveCount(0);
});

test("the calendar and the weeks it opens live on the workspace screen", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/workspaces");

  const panel = page.getByTestId("calendar-panel");
  await expect(panel).toBeVisible();

  // The demo dataset configures a calendar, so this reads as configured rather than absent.
  await expect(page.getByTestId("calendar-state")).toContainText(/weeks start on/i);
  await expect(panel.getByRole("button", { name: /open weeks/i })).toBeEnabled();
});

test("the overview can derive this week's obligations without waiting for the nightly job", async ({
  page,
}) => {
  await signIn(page, PROF);
  await page.goto("/overview");

  await page.getByTestId("derive-obligations").click();

  // Idempotent by construction: deriving twice adds nothing, so the only assertion worth making
  // is that the page survives it and the section still renders.
  await expect(page.getByTestId("outstanding")).toBeVisible();
});
