/**
 * UI-05 and ASSESS-08: the professor reviews a draft and publishes it, or changes it with a reason.
 *
 * The rule worth proving in a browser is the one a form can quietly lose: a changed rating must
 * not be approvable until a reason is written.
 */
import { expect, test } from "@playwright/test";

import { PROF, signIn } from "./helpers";

test("the overview leads to a draft and the draft shows its evidence", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/overview");

  await expect(page.getByRole("heading", { name: /overview/i })).toBeVisible();
  await page
    .getByRole("link", { name: /draft for/i })
    .first()
    .click();

  await expect(page.getByRole("heading", { name: /^review$/i })).toBeVisible();
  await expect(page.getByTestId("evidence")).toBeVisible();
  await expect(page.getByTestId("ratings")).toBeVisible();
});

test("a changed rating cannot be approved until a reason is written", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/overview");
  await page
    .getByRole("link", { name: /draft for/i })
    .first()
    .click();

  await page.getByLabel(/progress toward agreed outcomes/i).selectOption("4");

  await expect(page.getByTestId("rationale-required")).toBeVisible();
  await expect(page.getByRole("button", { name: /approve with an override/i })).toBeDisabled();

  await page
    .getByRole("textbox")
    .fill("The ablation was an additional outcome beyond the frozen plan.");
  await expect(page.getByRole("button", { name: /approve with an override/i })).toBeEnabled();
});

test("an approved assessment is published to the student", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/overview");
  await page
    .getByRole("link", { name: /draft for/i })
    .first()
    .click();

  await page.getByRole("button", { name: /approve and publish/i }).click();

  await expect(page.getByTestId("published")).toBeVisible();
});

test("an index that must be withheld reads as not rated, never as zero", async ({ page }) => {
  // ASSESS-04: a blank cell is a zero to whoever reads it.
  await signIn(page, PROF);
  await page.goto("/overview");
  await page
    .getByRole("link", { name: /draft for/i })
    .first()
    .click();

  const index = page.getByTestId("progress-index");
  await expect(index).toBeVisible();
  await expect(index).not.toHaveText("0/100");
});
