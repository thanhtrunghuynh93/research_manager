import { test, expect } from "@playwright/test";
import { PROF, STUDENT, signIn, api, asList } from "./qa-helpers";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

// frontend/ is an ES module package, so there is no __dirname here.
const HERE = fileURLToPath(new URL(".", import.meta.url));

const STATE = `${HERE}state.json`;
const read = () => JSON.parse(fs.readFileSync(STATE, "utf8"));
const save = (patch: object) => fs.writeFileSync(STATE, JSON.stringify({ ...read(), ...patch }, null, 2));

test.describe.configure({ mode: "serial" });

test("W1 a student has no workspace administration at all", async ({ page }) => {
  await signIn(page, STUDENT);
  const list = await api(page, "GET", "/workspaces");
  expect(list.status, "a student may not list workspaces").toBe(403);
  const create = await api(page, "POST", "/workspaces", { name: "Student's own lab" });
  expect(create.status, "a student may not create a workspace").toBe(403);
  await page.goto("/workspaces");
  await expect(page, "the role guard keeps the screen away from a student").not.toHaveURL(/\/workspaces/);
});

test("W2 leaving your only workspace is refused", async ({ page }) => {
  await signIn(page, PROF);
  const { workspaceId } = read();
  const left = await api(page, "POST", `/workspaces/${workspaceId}/leave`);
  expect(left.status, "the anchor has nowhere to go").toBeGreaterThanOrEqual(400);
  const me = await api(page, "GET", "/auth/me");
  expect(me.body.workspace_id, "still working in the same workspace").toBe(workspaceId);
});

test("W3 a professor creates a second workspace and is taken there", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/workspaces");
  await page.getByLabel(/^name$/i).fill("QA Lab Two");
  await page.getByRole("button", { name: /^create$/i }).click();
  await expect(page.getByTestId("workspace-list").getByText("QA Lab Two")).toBeVisible({ timeout: 15_000 });

  const list = await api(page, "GET", "/workspaces");
  expect(list.body.length, "belonging is plural for a professor").toBe(2);
  const two = list.body.find((w: any) => w.name === "QA Lab Two");
  expect(two.joined, "creating joins it").toBe(true);
  const me = await api(page, "GET", "/auth/me");
  expect(me.body.workspace_id, "and takes you there — the anchor moved").toBe(two.id);
  save({ workspaceTwoId: two.id });
});

test("W4 reads span both workspaces; the roll says so", async ({ page }) => {
  await signIn(page, PROF);
  const { workspaceId, studentId } = read();
  const users = await api(page, "GET", "/users");
  const emails = users.body.items.map((u: any) => u.email);
  expect(emails, "the student anchored in the other workspace is still read").toContain(STUDENT.email);
  const student = users.body.items.find((u: any) => u.id === studentId);
  expect(student.workspace_id, "and is still anchored where they were enrolled").toBe(workspaceId);
  await page.goto("/people");
  await expect(page.getByText(/across 2 workspaces/i)).toBeVisible();
});

test("W5 a write lands in the workspace being worked in, not the one read from", async ({ page }) => {
  await signIn(page, PROF);
  const { workspaceTwoId } = read();
  const created = await api(page, "POST", "/projects", {
    title: "QA — written while working in Lab Two",
    stage: "implementation",
  });
  expect(created.status).toBe(201);
  expect(created.body.workspace_id, "the write landed in the anchor").toBe(workspaceTwoId);
  save({ labTwoProjectId: created.body.id });
});

test("W6 a student who has written nothing can be moved; the move is by the professor", async ({ page }) => {
  await signIn(page, PROF);
  const { studentId, workspaceId, workspaceTwoId } = read();
  const moved = await api(page, "POST", `/users/${studentId}/workspace`, { workspace_id: workspaceTwoId });
  expect(moved.status, "no history yet, so the four history keys refuse nothing").toBe(200);
  const after = await api(page, "GET", `/users/${studentId}`);
  expect(after.body.workspace_id).toBe(workspaceTwoId);

  const back = await api(page, "POST", `/users/${studentId}/workspace`, { workspace_id: workspaceId });
  expect(back.status).toBe(200);
  const restored = await api(page, "GET", `/users/${studentId}`);
  expect(restored.body.workspace_id, "returned to the workspace they were enrolled into").toBe(workspaceId);
});

test("W7 a workspace somebody belongs to cannot be archived", async ({ page }) => {
  await signIn(page, PROF);
  const { workspaceId } = read();
  const archived = await api(page, "POST", `/workspaces/${workspaceId}/archive`);
  expect(archived.status, "two active accounts belong to it").toBeGreaterThanOrEqual(400);
});

test("W8 leaving empties a workspace, and an empty one archives", async ({ page }) => {
  await signIn(page, PROF);
  const { workspaceId, workspaceTwoId } = read();
  const left = await api(page, "POST", `/workspaces/${workspaceTwoId}/leave`);
  expect(left.status, "a second membership may be given up").toBe(200);
  const me = await api(page, "GET", "/auth/me");
  expect(me.body.workspace_id, "the anchor fell back to the workspace still belonged to").toBe(workspaceId);

  const archived = await api(page, "POST", `/workspaces/${workspaceTwoId}/archive`);
  expect(archived.status, "nobody belongs to it now").toBe(200);
  const list = await api(page, "GET", "/workspaces");
  const names = list.body.map((w: any) => w.name);
  expect(names, "and it leaves the list").not.toContain("QA Lab Two");
});
