/**
 * REP-02..05: the read-and-respond loop, end to end, through both roles' screens.
 *
 * `docs/use_cases.md` §2.5 used to record that this loop "has no surface at either end" — the
 * professor could not read a submitted report's text anywhere in the app, and could not answer
 * one. This spec is the browser-level proof that both halves now exist and meet in the middle:
 * the professor reads the week from the overview and asks for a change, and the student reads
 * that reason on their own screen rather than only in an email.
 */
import { expect, test } from "@playwright/test";

import { PROF, signIn, signOut, STUDENT_REVIEWED } from "./helpers";

test("a professor reads a submitted week and asks for a revision; the student reads why", async ({
  page,
}) => {
  const reason = `The ablation table is missing — asked at ${new Date().toISOString()}`;

  await signIn(page, PROF);
  // The one click from "this week is in" to what is actually in it.
  await page.getByTestId("read-submitted").first().click();

  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("versions")).toBeVisible();
  // The text of the week, which is the thing that had no screen.
  await expect(page.getByTestId("submitted-at")).toContainText(/submitted/i);

  await page
    .getByPlaceholder(/What needs to change/)
    .first()
    .fill(reason);
  await page
    .getByRole("button", { name: /request a revision/i })
    .first()
    .click();
  await expect(page.getByRole("status")).toBeVisible();

  await page.getByRole("button", { name: /mark reviewed/i }).click();
  await expect(page.getByRole("button", { name: /^reviewed$/i })).toBeDisabled();
  await signOut(page);

  await signIn(page, STUDENT_REVIEWED);
  await page.getByTestId("read-submitted").click();

  await expect(page.getByTestId("revision-reason")).toContainText("The ablation table is missing");
  // The professor's controls are the professor's.
  await expect(page.getByRole("button", { name: /request a revision/i })).toHaveCount(0);
  await expect(page.getByTestId("mark-reviewed")).toHaveCount(0);
});

test("a professor is still turned away from the student's own editor", async ({ page }) => {
  // The new route does not widen the old one: `/report/:periodId` stays student-only.
  await signIn(page, PROF);

  await page.goto("/report/00000000-0000-0000-0000-000000000000");

  await expect(page).toHaveURL(/\/overview$/);
});
