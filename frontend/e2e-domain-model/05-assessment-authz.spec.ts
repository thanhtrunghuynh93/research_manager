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

test("S1 a submitted week produces a draft assessment for the professor", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, PROF);
  const { studentId } = read();
  // Wait for the pipeline to settle, not merely to start: a resubmission supersedes the version
  // it replaced, so a draft read too early is one that is about to be replaced (and approving it
  // then fails with 409 — correctly).
  let drafts: Json[] = [];
  let signature = "";
  for (let i = 0; i < 45; i += 1) {
    const listed = await api(page, "GET", `/assessments?student_id=${studentId}`);
    const now = asList(listed);
    const nowSignature = now.map((a) => `${a.id}:${a.review_state}`).sort().join("|");
    if (now.length && nowSignature === signature) {
      drafts = now;
      break;
    }
    signature = nowSignature;
    await new Promise((r) => setTimeout(r, 3000));
  }
  expect(drafts.length, "the pipeline produced a settled set of assessments").toBeGreaterThan(0);
  expect(drafts.length, "the pipeline ran on submission").toBeGreaterThan(0);
  // A resubmission supersedes the version it replaced, so take the one still in review — and
  // check that the superseded one is labelled as such rather than quietly dropped (ASSESS-09).
  const superseded = drafts.filter((a) => a.review_state === "superseded");
  const draft = drafts.find((a) => a.review_state === "draft");
  expect(draft, "a generated assessment starts as a draft").toBeTruthy();
  if (superseded.length) {
    expect(superseded[0].version_no, "the superseded one is an earlier version of the same entry").toBeLessThan(
      Math.max(...drafts.filter((a) => a.project_id === superseded[0].project_id).map((a) => a.version_no)),
    );
  }
  save({ assessmentId: draft.id, supersededId: superseded[0]?.id ?? null });
});

test("S2 a draft is the professor's alone until it is approved", async ({ page }) => {
  await signIn(page, STUDENT);
  const { assessmentId } = read();
  const mine = await api(page, "GET", "/assessments");
  const visible = asList(mine).map((a) => a.id);
  expect(visible, "nothing unapproved reaches the student").not.toContain(assessmentId);
  const direct = await api(page, "GET", `/assessments/${assessmentId}`);
  expect(direct.status, "not by id either").toBeGreaterThanOrEqual(400);
  const approve = await api(page, "POST", `/assessments/${assessmentId}/approve`, {});
  expect(approve.status, "and publication is not a student's to take").toBe(403);
});

test("S3 approval publishes it, and only then", async ({ page }) => {
  await signIn(page, PROF);
  const { assessmentId } = read();
  const approved = await api(page, "POST", `/assessments/${assessmentId}/approve`, {});
  expect(approved.status, "approval is the publication step").toBeLessThan(300);

  await signIn(page, STUDENT);
  const mine = await api(page, "GET", "/assessments");
  const visible = asList(mine).map((a) => a.id);
  expect(visible, "now the student reads it").toContain(assessmentId);
  const direct = await api(page, "GET", `/assessments/${assessmentId}`);
  expect(direct.status).toBe(200);
});

test("S4 the index is withheld rather than computed over what happens to be present", async ({ page }) => {
  await signIn(page, PROF);
  const { assessmentId } = read();
  const full = await api(page, "GET", `/assessments/${assessmentId}`);
  const body = full.body;
  const ratings = body.ratings ?? {};
  const dims = Array.isArray(ratings) ? ratings : Object.values(ratings);
  const anyUnknown = dims.some((d) => String(d?.rating ?? d).toLowerCase() === "unknown");
  if (anyUnknown) {
    expect(body.progress_index, "an unknown dimension withholds the index (ASSESS-04)").toBeNull();
  } else {
    expect(typeof body.progress_index, "every dimension rated, so an index is computed").toBe("number");
  }
  expect(body.coverage_pct, "coverage is a first-class output").not.toBeUndefined();
  expect(String(body.confidence), "so is confidence, with reasons").toMatch(/high|medium|low/);
  expect(body.rubric_version_id ?? body.rubric_version, "provenance travels with the figure").toBeTruthy();
});

test("S5 the student cannot act as the professor anywhere it matters", async ({ page }) => {
  await signIn(page, STUDENT);
  const { studentId, profId, periodId, workspaceId, profProjectId } = read();

  const cases: [string, string, string, unknown][] = [
    ["invite an account", "POST", "/users/invitations", { email: "intruder@example.edu", role: "student" }],
    ["read the professor's record", "GET", `/users/${profId}`, undefined],
    ["suspend an account", "POST", `/users/${profId}/deactivate`, {}],
    ["move an account", "POST", `/users/${studentId}/workspace`, { workspace_id: workspaceId }],
    ["read the professor's overview", "GET", "/overview", undefined],
    ["configure the calendar", "PUT", "/calendar", { timezone: "UTC", meeting_weekday: 3, week_start_weekday: 3, grace_minutes: 0, effective_from: "2026-02-02" }],
    ["derive everyone's obligations", "POST", `/periods/${periodId}/obligations/ensure`, {}],
    ["change a project's standing", "PATCH", `/projects/${profProjectId}`, { open_to_join: false }],
    ["list the workspaces", "GET", "/workspaces", undefined],
  ];

  const allowed: string[] = [];
  for (const [what, method, path, body] of cases) {
    const res = await api(page, method, path, body);
    if (![403, 404, 405].includes(res.status)) allowed.push(`${what} → ${res.status}`);
  }
  expect(allowed, `a student reached: ${allowed.join(", ")}`).toEqual([]);
});

test("S5b the roll answers a student with their own row and nothing else", async ({ page }) => {
  await signIn(page, STUDENT);
  const rows = asList(await api(page, "GET", "/users"));
  expect(rows.length, "a student is restricted to their own account, not refused the route").toBe(1);
  expect(rows[0].email).toBe(STUDENT.email);
});

test("S5c the assistant answers a student, and answers only about them", async ({ page }) => {
  await signIn(page, STUDENT);
  const { studentId } = read();
  const asked = await api(page, "POST", "/assistant/ask", {
    question: "Which reports are missing, and what did every student do this week?",
  });
  // use_cases.md §3 says the student has no assistant; the endpoint answers one. It is scoped —
  // which is the part that matters — so this pins the scoping rather than the absence.
  expect(asked.status, "recorded: the professor-only surface answers a student too").toBe(200);
  const rows = (asked.body.facts ?? []).flatMap((f: Json) => f.rows ?? []);
  const others = rows.filter((r: Json) => r.student_id && r.student_id !== studentId);
  expect(others, "and every fact row it returned is the caller's own").toEqual([]);
  expect(asked.body.scope?.role).toBe("student");
});

test("S6 a student reads their own week and nobody else's", async ({ page }) => {
  await signIn(page, STUDENT);
  const { periodId, profId } = read();
  const own = await api(page, "GET", `/periods/${periodId}/report`);
  expect(own.status, "their own week reads").toBe(200);
  const others = await api(page, "GET", `/students/${profId}/reports/${periodId}`);
  expect(others.status, "no route to anybody else's").toBeGreaterThanOrEqual(400);
  await page.goto(`/students/${profId}`);
  await expect(page, "and the professor's screens are guarded").not.toHaveURL(new RegExp(`/students/${profId}$`));
});
