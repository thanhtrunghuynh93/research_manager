import { test, expect } from "@playwright/test";
import { PROF, STUDENT, PASSWORD, signIn, tokenPath, api, asList } from "./qa-helpers";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

// frontend/ is an ES module package, so there is no __dirname here.
const HERE = fileURLToPath(new URL(".", import.meta.url));

const STATE = `${HERE}state.json`;
const save = (patch: object) => {
  const cur = fs.existsSync(STATE) ? JSON.parse(fs.readFileSync(STATE, "utf8")) : {};
  fs.writeFileSync(STATE, JSON.stringify({ ...cur, ...patch }, null, 2));
};

test.describe.configure({ mode: "serial" });

test("A1 the professor accepts the bootstrap invitation and lands in the workspace", async ({ page }) => {
  const token = process.env.PROF_TOKEN;
  if (token) {
    await page.goto(`/accept-invitation?token=${token}`);
    await page.getByLabel(/your name/i).fill(PROF.name);
    await page.getByLabel(/^password$/i).fill(PASSWORD);
    await page.getByLabel(/password again/i).fill(PASSWORD);
    await page.getByRole("button", { name: /set password and continue/i }).click();
  } else {
    await signIn(page, PROF);
  }
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible({ timeout: 15_000 });
  // A professor's home is the overview (UI-01).
  await expect(page).toHaveURL(/\/overview/);

  const me = await api(page, "GET", "/auth/me");
  expect(me.status).toBe(200);
  expect(me.body.role).toBe("prof");
  save({ profId: me.body.id, workspaceId: me.body.workspace_id });
});

test("A2 the roll holds one professor and nobody else", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/people");
  await expect(page.getByRole("heading", { name: /people/i })).toBeVisible();
  await expect(page.getByText(PROF.email)).toBeVisible();
  await expect(page.getByText(/nobody has been enrolled yet/i)).toBeVisible();
});

test("A3 the professor invites a student, and the invitation names a workspace", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/people");
  await page.getByLabel(/^email$/i).fill(STUDENT.email);
  await page.getByLabel(/name \(optional\)/i).fill(STUDENT.name);
  await page.getByRole("button", { name: /send invitation/i }).click();
  await expect(page.getByText(new RegExp(`invitation sent to ${STUDENT.email}`, "i"))).toBeVisible({
    timeout: 15_000,
  });

  // ADR 0015: the membership is written at invitation, not at acceptance — so an invited
  // account is already on the roll and already occupies the workspace.
  const users = await api(page, "GET", "/users");
  const invited = asList(users).find((u: any) => u.email === STUDENT.email);
  expect(invited, "the invited student is on the roll before accepting").toBeTruthy();
  expect(invited.state).toBe("invited");
  const state = JSON.parse(fs.readFileSync(STATE, "utf8"));
  expect(invited.workspace_id, "invited into the inviting professor's workspace").toBe(state.workspaceId);
  save({ studentId: invited.id });
});

test("A4 the student accepts by the emailed link and lands on their own week", async ({ page, request }) => {
  const path = await tokenPath(request, STUDENT.email, "accept-invitation");
  await page.goto(path);
  await page.getByLabel(/^password$/i).fill(PASSWORD);
  await page.getByLabel(/password again/i).fill(PASSWORD);
  await page.getByRole("button", { name: /set password and continue/i }).click();
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible({ timeout: 15_000 });
  await expect(page).toHaveURL(/\/me/);

  const me = await api(page, "GET", "/auth/me");
  expect(me.body.role).toBe("student");
  const state = JSON.parse(fs.readFileSync(STATE, "utf8"));
  expect(me.body.workspace_id).toBe(state.workspaceId);
});
