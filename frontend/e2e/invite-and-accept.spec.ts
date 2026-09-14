/**
 * AUTH-01 end to end: a professor enrols someone, and that someone gets in.
 *
 * The two halves were built separately and only meet on a running stack. The professor's half is
 * the roll at `/people`; the invitee's half is `/accept-invitation`, which is the only screen in
 * the product a person reaches with no session. Between them sits a token that must survive being
 * issued, emailed, and spent exactly once.
 *
 * The last two tests are the other direction — removal (ADR 0011) — because an enrolment flow that
 * cannot be undone is only half a roll, and because "the account is closed" has to mean the person
 * can no longer sign in, not merely that a badge changed colour.
 */
import { expect, test } from "@playwright/test";

import { PROF, signIn, tokenPath } from "./helpers";

test.describe.configure({ mode: "serial" });

// Unique per run: an address that already has an account is refused, so a rerun against the same
// stack would otherwise fail on the invitation rather than on anything it means to test.
const STAMP = Date.now();
const INVITEE = {
  email: `e2e-invitee-${STAMP}@example.edu`,
  password: "a long enough e2e password",
  name: "E2E Invitee",
};
const RECOVERED_PASSWORD = "the recovered e2e password";

let acceptPath: string;

test("the professor invites a student from the roll", async ({ page, request }) => {
  await signIn(page, PROF);
  await page.goto("/people");

  await page.getByLabel(/^email$/i).fill(INVITEE.email);
  await page.getByLabel(/name \(optional\)/i).fill(INVITEE.name);
  await page.getByRole("button", { name: /send invitation/i }).click();

  await expect(page.getByRole("status")).toContainText(INVITEE.email);
  // Invited, not yet active: the account exists but has no password.
  await expect(page.getByTestId("students")).toContainText(INVITEE.email);
  await expect(page.getByTestId("students")).toContainText(/invited/i);

  // The email is the channel the token travels on, so that is where the link is read from.
  acceptPath = await tokenPath(request, INVITEE.email, "accept-invitation");
  expect(acceptPath).toContain("/accept-invitation?token=");
});

test("the invitation link sets a password and signs the new account in", async ({ page }) => {
  await page.goto(acceptPath);

  await page.getByLabel(/your name/i).fill(INVITEE.name);
  await page.getByLabel(/^password$/i).fill(INVITEE.password);
  await page.getByLabel(/password again/i).fill(INVITEE.password);
  await page.getByRole("button", { name: /set password and continue/i }).click();

  // Accepting starts the session, so the student lands on their own home already signed in.
  await expect(page).toHaveURL(/\/me$/);
  await expect(page.getByTestId("greeting")).toContainText(INVITEE.name);
  // UI-02 belongs to the student; the professor's pages are not offered to them.
  await expect(page.getByRole("link", { name: /people/i })).toHaveCount(0);
});

test("the same link cannot be spent twice", async ({ page }) => {
  await page.goto(acceptPath);

  await page.getByLabel(/^password$/i).fill("a different long password");
  await page.getByLabel(/password again/i).fill("a different long password");
  await page.getByRole("button", { name: /set password and continue/i }).click();

  await expect(page.getByRole("alert")).toContainText(/invalid, used, or expired/i);
});

test("the password chosen at acceptance is the one that signs in", async ({ page }) => {
  await signIn(page, INVITEE);

  await expect(page).toHaveURL(/\/me$/);
});

test("a link carrying no token offers no form", async ({ page }) => {
  await page.goto("/accept-invitation");

  await expect(page.getByRole("alert")).toContainText(/no invitation token/i);
  await expect(page.getByLabel(/^password$/i)).toHaveCount(0);
});

test("the student recovers a forgotten password by email", async ({ page, request }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: /forgot your password/i }).click();
  await page.getByLabel(/your email/i).fill(INVITEE.email);
  await page.getByRole("button", { name: /send a recovery link/i }).click();
  await expect(page.getByRole("status")).toContainText(/if that address has an account/i);

  await page.goto(await tokenPath(request, INVITEE.email, "reset-password"));
  await page.getByLabel(/new password/i).fill(RECOVERED_PASSWORD);
  await page.getByLabel(/password again/i).fill(RECOVERED_PASSWORD);
  await page.getByRole("button", { name: /save password/i }).click();

  // A reset does not sign anyone in: it may have been requested from another device.
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("status")).toContainText(/your password is set/i);

  await signIn(page, { email: INVITEE.email, password: RECOVERED_PASSWORD });
  await expect(page).toHaveURL(/\/me$/);
});

test("an address with no account is answered the same way, and emailed nothing", async ({
  page,
  request,
}) => {
  const unknown = `e2e-nobody-${STAMP}@example.edu`;
  await page.goto("/login");
  await page.getByRole("button", { name: /forgot your password/i }).click();
  await page.getByLabel(/your email/i).fill(unknown);
  await page.getByRole("button", { name: /send a recovery link/i }).click();

  // AUTH-01: the answer must not enumerate accounts, and no mail may contradict it.
  await expect(page.getByRole("status")).toContainText(/if that address has an account/i);
  await expect(tokenPath(request, unknown, "reset-password", 3)).rejects.toThrow(
    /no reset-password link/i,
  );
});

test("the professor removes the student, and the row says so", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/people");

  const row = page.getByTestId("students").getByRole("listitem").filter({
    hasText: INVITEE.email,
  });
  await row.getByRole("button", { name: /remove from workspace/i }).click();

  // ADR 0011: the destructive act names its consequence before it happens.
  await expect(row).toContainText(/cannot be undone/i);
  await row.getByRole("button", { name: /^remove$/i }).click();

  await expect(row).toContainText(/closed/i);
  await expect(row.getByRole("button", { name: /restore access/i })).toBeVisible();
});

test("a removed student can no longer sign in", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(INVITEE.email);
  await page.getByLabel(/password/i).fill(RECOVERED_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});
