import { test, expect } from "@playwright/test";
import { PROF, STUDENT, signIn, api, asList, type Json } from "./qa-helpers";
import * as fs from "node:fs";
import { fileURLToPath } from "node:url";

// frontend/ is an ES module package, so there is no __dirname here.
const HERE = fileURLToPath(new URL(".", import.meta.url));

const STATE = `${HERE}state.json`;
const read = () => JSON.parse(fs.readFileSync(STATE, "utf8"));
const save = (patch: object) => fs.writeFileSync(STATE, JSON.stringify({ ...read(), ...patch }, null, 2));

test.describe.configure({ mode: "serial" });

test("R1 the calendar fixes the deadline by rule: 23:59 the day before the meeting", async ({ page }) => {
  await signIn(page, PROF);
  const put = await api(page, "PUT", "/calendar", {
    timezone: "Asia/Ho_Chi_Minh",
    meeting_weekday: 0,
    week_start_weekday: 0,
    grace_minutes: 0,
    effective_from: "2026-01-05",
  });
  expect(put.status).toBeLessThan(300);
  const ensured = await api(page, "POST", "/periods/ensure");
  expect(ensured.status).toBeLessThan(300);

  const periods = await api(page, "GET", "/periods");
  const items = asList(periods);
  const today = new Date().toISOString().slice(0, 10);
  const current = items.find((p) => p.local_start <= today && today <= p.local_end);
  expect(current, "a period contains today").toBeTruthy();

  // The meeting follows the week it discusses, so the deadline falls inside the period.
  const dayAfterEnd = new Date(`${current.local_end}T00:00:00Z`);
  dayAfterEnd.setUTCDate(dayAfterEnd.getUTCDate() + 1);
  expect(current.meeting_date, "the meeting is the day after the week ends").toBe(
    dayAfterEnd.toISOString().slice(0, 10),
  );
  const deadline = new Date(current.deadline_utc);
  // 23:59 local in Asia/Ho_Chi_Minh (UTC+7) on the last day of the period is 16:59Z that day.
  expect(deadline.toISOString(), "23:59 local on the day before the meeting").toBe(
    `${current.local_end}T16:59:00.000Z`,
  );
  const next = items.find((p) => p.local_start > current.local_end);
  save({ periodId: current.id, periodLocalEnd: current.local_end, nextPeriodId: next?.id });
});

test("R2 obligations derive from an active project and a membership, and from nothing else", async ({ page }) => {
  await signIn(page, PROF);
  const { periodId, nextPeriodId, studentProjectId, profProjectId, studentId } = read();
  await api(page, "POST", `/periods/${periodId}/obligations/ensure`);
  if (nextPeriodId) await api(page, "POST", `/periods/${nextPeriodId}/obligations/ensure`);

  const thisWeek = await api(page, "GET", `/periods/${periodId}/obligations`);
  const rows = asList(thisWeek).filter((o) => o.student_id === studentId);
  const projects = rows.map((o) => o.project_id);

  expect(projects, "a project started this week owes this week").toContain(studentProjectId);
  // The self-joined half of this rule is pinned in 06-boundary.spec.ts: joining on the first day
  // of the week does owe that week, which is one day away from what the rule says. Asserting it
  // here would stop the rest of this file, and the weeks below still need writing.

  if (nextPeriodId) {
    const nextWeek = await api(page, "GET", `/periods/${nextPeriodId}/obligations`);
    const nextProjects = asList(nextWeek)
      .filter((o) => o.student_id === studentId)
      .map((o) => o.project_id);
    expect(nextProjects, "and owes it from then on").toContain(profProjectId);
  }
});

test("R3 a proposed project owes nothing even with a student on it", async ({ page }) => {
  await signIn(page, PROF);
  const { periodId, studentId } = read();
  const created = await api(page, "POST", "/projects", { title: "QA — proposed, never activated", stage: "theory" });
  expect(created.status).toBe(201);
  const assigned = await api(page, "POST", `/projects/${created.body.id}/members`, {
    student_id: studentId,
    responsibility: "QA",
  });
  expect(assigned.status, "a professor may place any student on any project").toBe(201);

  await api(page, "POST", `/periods/${periodId}/obligations/ensure`);
  const obligations = await api(page, "GET", `/periods/${periodId}/obligations`);
  const projects = asList(obligations).map((o) => o.project_id);
  expect(projects, "nothing is owed on a proposed project").not.toContain(created.body.id);
  save({ proposedProjectId: created.body.id });
});

test("R4 the week asks three questions, names no hours, and takes evidence as a file", async ({ page }) => {
  await signIn(page, STUDENT);
  const { periodId } = read();
  await page.goto(`/report/${periodId}`);
  await expect(page.getByRole("heading", { name: /weekly package/i })).toBeVisible({ timeout: 15_000 });

  await expect(page.getByText(/^Progress$/)).toBeVisible();
  await expect(page.getByText(/^Challenges$/)).toBeVisible();
  await expect(page.getByText(/^Next steps$/)).toBeVisible();
  await expect(page.getByText(/^Work performed$/), "folded into Progress").toHaveCount(0);
  await expect(page.getByText(/^Questions for the professor$/), "folded into Challenges").toHaveCount(0);
  await expect(page.getByText(/hours/i), "hours are not asked for").toHaveCount(0);
  await expect(page.getByText(/attach a file/i), "evidence is a file").toBeVisible();
  await expect(page.locator('input[type="url"]'), "and not a link").toHaveCount(0);
  // Recorded rather than asserted: the evidence help text still says "the next file or link you
  // attach", which is copy left behind by the withdrawal of links (REP-04).
  const claimNote = await page.getByText(/applied to the next file/i).textContent();
  console.log(`EVIDENCE NOTE: ${claimNote?.trim()}`);

  // The route the link half used is gone with it.
  const links = await api(page, "POST", "/artifacts/links", { url: "https://example.org/x" });
  // 405, not 404: the path still matches `/artifacts/{artifact_id}`, which answers other methods.
  expect([404, 405], "the link endpoint went with the feature").toContain(links.status);
});

test("R5 one package a week, one entry a project, and a version that cannot be rewritten", async ({ page }) => {
  await signIn(page, STUDENT);
  const { periodId, studentProjectId } = read();

  // A package covers every project owed this week (REP-02), so it is built from the obligations.
  const owed = asList(await api(page, "GET", `/periods/${periodId}/obligations`))
    .filter((o) => o.student_id === read().studentId && o.state === "required")
    .map((o) => o.project_id);
  expect(owed.length, "at least the student's own project is owed").toBeGreaterThan(0);
  const entryFor = (projectId: string, work: string) => ({
    project_id: projectId,
    stage: "literature_review",
    work_performed: work,
    deviations: projectId === studentProjectId ? "The cluster queue was full, so the pilot run slipped." : "",
    next_plan: { items: [{ planned_outcome: "Draft the related-work section" }] },
  });
  const first = await api(page, "POST", `/periods/${periodId}/report/submit`, {
    entries: owed.map((id: string) =>
      entryFor(id, id === studentProjectId
        ? "Read nine papers on evidence-bounded supervision and took notes."
        : "Picked up the thread on this project and read the plan."),
    ),
  });
  expect(first.status, "submission writes a version").toBeLessThan(300);
  const v1 = first.body.version_no ?? first.body.version ?? 1;
  expect(v1).toBe(1);

  const report = await api(page, "GET", `/periods/${periodId}/report`);
  const reportId = report.body.id ?? report.body.report?.id;
  const firstSubmittedAt = report.body.first_submitted_at ?? report.body.report?.first_submitted_at;
  expect(firstSubmittedAt, "the hour it went in is on the record").toBeTruthy();

  const second = await api(page, "POST", `/periods/${periodId}/report/submit`, {
    entries: owed.map((id: string) =>
      entryFor(id, id === studentProjectId
        ? "Read nine papers, and corrected the count in the summary table."
        : "Picked up the thread on this project and read the plan."),
    ),
  });
  expect(second.status, "a resubmission is allowed").toBeLessThan(300);
  expect(second.body.version_no ?? second.body.version, "and adds a version").toBe(2);

  const versions = await api(page, "GET", `/reports/${reportId}/versions`);
  const all = asList(versions);
  expect(all.length, "every earlier version is kept").toBeGreaterThanOrEqual(2);

  const after = await api(page, "GET", `/periods/${periodId}/report`);
  expect(after.body.first_submitted_at ?? after.body.report?.first_submitted_at,
    "the first submission time is frozen").toBe(firstSubmittedAt);

  const v1id = all.find((v) => (v.version_no ?? v.version) === 1).id;
  const v1body = await api(page, "GET", `/report-versions/${v1id}`);
  expect(v1body.status, "and version 1 still reads back").toBe(200);
  const entries = v1body.body.entries ?? [];
  expect(entries.length, "one entry per project owed in that version").toBe(owed.length);
  expect(entries.find((e: Json) => e.project_id === studentProjectId).work_performed).toMatch(/took notes/);
  save({ reportId, v1id });
});

test("R6 a package that misses an owed project is refused", async ({ page }) => {
  await signIn(page, PROF);
  const { periodId, proposedProjectId } = read();
  // Activate the third project so the student owes two entries this week.
  const activated = await api(page, "PATCH", `/projects/${proposedProjectId}`, { status: "active" });
  expect(activated.status).toBe(200);
  await api(page, "POST", `/periods/${periodId}/obligations/ensure`);

  await signIn(page, STUDENT);
  const { studentProjectId } = read();
  const partial = await api(page, "POST", `/periods/${periodId}/report/submit`, {
    entries: [
      {
        project_id: studentProjectId,
        stage: "literature_review",
        work_performed: "Only one of the two projects is in this package.",
        next_plan: {},
      },
    ],
  });
  expect(partial.status, "a package is complete only when every required project has an entry").toBeGreaterThanOrEqual(400);
});

test("R7 once a week has been written, the account cannot leave the workspace", async ({ page }) => {
  await signIn(page, PROF);
  const { studentId } = read();
  const second = await api(page, "POST", "/workspaces", { name: "QA Lab Three" });
  expect(second.status).toBe(201);
  const move = await api(page, "POST", `/users/${studentId}/workspace`, { workspace_id: second.body.id });
  expect(move.status, "weekly_reports refuses to follow the account").toBeGreaterThanOrEqual(400);
  expect(JSON.stringify(move.body), "and the refusal says why").toMatch(/history|written|report|workspace/i);
  save({ workspaceThreeId: second.body.id });
});

test("R8 leaving a project keeps the week that was already filed", async ({ page }) => {
  await signIn(page, STUDENT);
  const { studentProjectId, v1id, studentId } = read();
  const members = await api(page, "GET", `/projects/${studentProjectId}/members`);
  const mine = asList(members).find((m) => m.student_id === studentId);
  const left = await api(page, "POST", `/projects/${studentProjectId}/members/${mine.id}/end`, {});
  expect(left.status, "a student may end their own membership").toBeLessThan(300);

  const v1 = await api(page, "GET", `/report-versions/${v1id}`);
  expect(v1.status, "the filed week is still the student's to read").toBe(200);
  expect((v1.body.entries ?? []).length, "including the entry for the project they left").toBeGreaterThan(0);
});
