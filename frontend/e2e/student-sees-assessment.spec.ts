/**
 * UI-02: the student reads the assessment that was published to them.
 *
 * This is the test for the gap `use_cases.md` §8.2 described: "An assessment is drafted by the
 * pipeline, held back until the professor approves it, and approving it is one of the few professor
 * actions that is 🖥️. The student it is approved for has no screen on which to read it."
 *
 * The demo dataset approves one assessment for the first student, so this runs against the seeded
 * stack without anything having to be set up first.
 *
 * Half of what it proves is negative, and deliberately so: a student must not be shown a draft, a
 * review state, or any control that belongs to the professor's decision.
 */
import { expect, test } from "@playwright/test";

import { signIn, STUDENT } from "./helpers";

test("the assessment published to a student is readable by that student", async ({ page }) => {
  await signIn(page, STUDENT);
  await page.goto("/me");

  const released = page.getByTestId("released-assessments");
  await expect(released).toBeVisible();

  // The link the whole feature exists for: the publish now has a destination.
  await released.getByRole("link").first().click();

  await expect(page.getByTestId("my-ratings")).toBeVisible();
  await expect(page.getByTestId("released-at")).toContainText(/released to you/i);
});

test("the student is offered no approval control and is shown no draft", async ({ page }) => {
  await signIn(page, STUDENT);
  await page.goto("/me");
  await page.getByTestId("released-assessments").getByRole("link").first().click();
  await expect(page.getByTestId("my-ratings")).toBeVisible();

  // The policy already returns approved-only, so a review-state badge would always read
  // "Approved" and invite the question of what else exists (ASSESS-08, QA-06).
  await expect(page.getByRole("button", { name: /approve/i })).toHaveCount(0);
  await expect(page.getByText(/draft/i)).toHaveCount(0);
});

test("the student can put a correction request on the record", async ({ page }) => {
  // ASSESS-08 has always allowed this and nothing called it, so publishing was an announcement
  // rather than a loop.
  await signIn(page, STUDENT);
  await page.goto("/me");
  await page.getByTestId("released-assessments").getByRole("link").first().click();

  await page
    .getByLabel(/ask for a correction/i)
    .fill("The merged pull request is not in the evidence.");
  await page.getByRole("button", { name: /send correction request/i }).click();

  await expect(page.getByTestId("feedback")).toContainText(/not in the evidence/i);
});

test("their own progress page carries the trajectory and every released assessment", async ({
  page,
}) => {
  await signIn(page, STUDENT);

  await page.getByRole("link", { name: /my progress/i }).click();

  await expect(page.getByTestId("my-assessments")).toBeVisible();
  await expect(page.getByTestId("trajectory")).toBeVisible();
});
