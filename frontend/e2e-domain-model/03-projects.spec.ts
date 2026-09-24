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

test("P1 a project a professor starts is proposed", async ({ page }) => {
  await signIn(page, PROF);
  await page.goto("/projects");
  await page.getByLabel(/^title$/i).fill("QA — the professor's project");
  await page.getByLabel(/^stage$/i).selectOption("implementation");
  await page.getByRole("button", { name: /create project/i }).click();
  await expect(page.getByTestId("project-list").getByText("QA — the professor's project")).toBeVisible({
    timeout: 15_000,
  });
  // The screen says it, and the record agrees.
  await expect(page.getByText(/a new project is proposed/i)).toBeVisible();

  const list = await api(page, "GET", "/projects");
  const mine = asList(list).find((p) => p.title === "QA — the professor's project");
  expect(mine.status, "activation records a second party's assent").toBe("proposed");
  expect(mine.open_to_join, "closed by default — opening one is a disclosure decision").toBe(false);
  save({ profProjectId: mine.id });
});

test("P2 a project a student starts is active, and they are on it", async ({ page }) => {
  await signIn(page, STUDENT);
  await page.goto("/projects");
  await page.getByLabel(/^title$/i).fill("QA — the student's own project");
  await page.getByLabel(/^stage$/i).selectOption("literature_review");
  await page.getByRole("button", { name: /create project/i }).click();
  await expect(page.getByTestId("project-list").getByText("QA — the student's own project")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/your project is active as soon as you create it/i)).toBeVisible();

  const list = await api(page, "GET", "/projects");
  const mine = asList(list).find((p) => p.title === "QA — the student's own project");
  expect(mine.status, "no second party, so nothing to assent to").toBe("active");
  const members = await api(page, "GET", `/projects/${mine.id}/members`);
  const ids = asList(members).map((m) => m.student_id);
  expect(ids, "the creator is enrolled in the same transaction").toContain(read().studentId);
  const origin = asList(members).find((m) => m.student_id === read().studentId).origin;
  expect(origin, "created with the project, which owes the week it lands in").toBe("created");
  save({ studentProjectId: mine.id });
});

test("P3 the creator may change the record and not its standing", async ({ page }) => {
  await signIn(page, STUDENT);
  const { studentProjectId } = read();
  const record = await api(page, "PATCH", `/projects/${studentProjectId}`, {
    title: "QA — the student's own project (retitled)",
    research_questions: ["Does the creator keep the record?"],
  });
  expect(record.status, "title and research questions are what the work is").toBe(200);

  for (const [field, value] of [["status", "paused"], ["open_to_join", true], ["ai_restricted", true]] as const) {
    const attempt = await api(page, "PATCH", `/projects/${studentProjectId}`, { [field]: value });
    expect(attempt.status, `${field} is a supervision decision`).toBe(403);
  }
  const after = await api(page, "GET", `/projects/${studentProjectId}`);
  expect(after.body.status).toBe("active");
  expect(after.body.open_to_join).toBe(false);
});

test("P4 a student may not put anybody on a project, their own included", async ({ page }) => {
  await signIn(page, STUDENT);
  const { studentProjectId, profId } = read();
  const assign = await api(page, "POST", `/projects/${studentProjectId}/members`, { student_id: profId });
  expect(assign.status, "a student speaks for themselves and no other account").toBe(403);
});

test("P5 a membership is the whole grant: a closed project is unreadable", async ({ page }) => {
  await signIn(page, STUDENT);
  const { profProjectId } = read();
  const direct = await api(page, "GET", `/projects/${profProjectId}`);
  expect(direct.status, "not a member, so not visible").toBeGreaterThanOrEqual(400);
  const joinable = await api(page, "GET", "/projects/joinable");
  const titles = asList(joinable).map((p) => p.title);
  expect(titles, "closed to joining by default").not.toContain("QA — the professor's project");
  const join = await api(page, "POST", `/projects/${profProjectId}/join`, {});
  expect(join.status, "and cannot be joined while closed").toBeGreaterThanOrEqual(400);
});

test("P6 the professor opens it; discovery is a narrower read than membership", async ({ page }) => {
  await signIn(page, PROF);
  const { profProjectId } = read();
  const opened = await api(page, "PATCH", `/projects/${profProjectId}`, {
    open_to_join: true,
    status: "active",
    research_questions: ["Is the joinable read narrow?"],
    venue_target: "QA Symposium",
  });
  expect(opened.status).toBe(200);

  await signIn(page, STUDENT);
  const joinable = await api(page, "GET", "/projects/joinable");
  const row = asList(joinable).find((p) => p.id === profProjectId);
  expect(row, "now discoverable").toBeTruthy();
  expect(Object.keys(row).sort(), "title, stage, status and a member count — not the research").toEqual(
    expect.not.arrayContaining(["research_questions", "intended_contributions", "venue_target", "shared_resources"]),
  );
  expect(row.member_count, "a count, not the member list").toBeDefined();
  // Still not readable in full until joined.
  const before = await api(page, "GET", `/projects/${profProjectId}`);
  expect(before.status, "discoverable is not readable").toBeGreaterThanOrEqual(400);
});

test("P7 the student joins, and the project opens up", async ({ page }) => {
  await signIn(page, STUDENT);
  const { profProjectId } = read();
  await page.goto("/projects");
  await page.getByTestId("joinable").getByTestId("join-project").first().click();
  await expect(page.getByTestId("project-list").getByText("QA — the professor's project")).toBeVisible({
    timeout: 15_000,
  });

  const full = await api(page, "GET", `/projects/${profProjectId}`);
  expect(full.status, "membership is the grant").toBe(200);
  expect(full.body.research_questions, "now the research reads too").toContain("Is the joinable read narrow?");
  const members = await api(page, "GET", `/projects/${profProjectId}/members`);
  const mine = asList(members).find((m) => m.student_id === read().studentId);
  expect(mine.origin, "joining is its own origin, and it owes from next week").toBe("self_joined");
});
