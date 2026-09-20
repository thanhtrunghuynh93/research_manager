# QA report — the student role on research.ecomind.dev

**Tested** 18 September 2026, against the live deployment at `https://research.ecomind.dev`.
**As** `an.nguyen@example.edu` (An Nguyen, student, 3 seeded projects).
**With** Playwright/Chromium driving the real UI: sign in through the form, click what a student
can click, read what a student reads. API calls are quoted only as evidence for what a screen
showed, never as a substitute for it.

**Scope** — every student capability in [docs/use_cases.md](docs/use_cases.md) §3 that is marked
🖥️: the week and its obligations, the report editor and its autosave, attachments (file, link,
removal), submission, the released assessment and the correction request, the trajectory, projects
(list, create, edit, leave), past weeks, sign-out, and the role guards on the professor's screens.
The ⚙️ rows were not exercised: they have no screen by design.

14 defects. Three of them lose or misrepresent a student's work.

---

## Summary

| # | What a student sees | Severity |
| --- | --- | --- |
| 1 | Every project still says **REQUIRED** after the week has been submitted | **High** |
| 2 | Reopening a submitted week can show an empty form — and submitting it overwrites the week with blanks | **High** |
| 3 | An attached file says **READING…** forever; the text is never extracted | **High** |
| 4 | No web font loads on any page — blocked by the site's own CSP | Medium |
| 5 | Every time is rendered in Asia/Ho_Chi_Minh whatever the workspace's timezone is | Medium |
| 6 | The assessment screen names the project by a fragment of its UUID | Medium |
| 7 | "a report … is owed from next week" — it is owed the same day | Medium |
| 8 | Leaving a project is irreversible, unconfirmed, and gives no feedback | Medium |
| 9 | The autosave clock and the deadline beside it are in different timezones | Low |
| 10 | Trajectory cards label the rubric with a fragment of its UUID | Low |
| 11 | A past member disappears from the member list entirely | Low |
| 12 | "An assessment appears here once your professor has approved it" — shown under a list of approved assessments | Low |
| 13 | An unknown period id reads "No reporting period has been configured yet" | Low |
| 14 | A link into a professor-only screen drops the student on `/me` with no explanation | Low (known) |

---

## 1 — Every project still says REQUIRED after the week has been submitted

**Severity: High.** This is the reported symptom, and it reproduces on first sign-in with no setup.

`/me` shows the week's state as **Resubmitted** and, directly underneath, a heading **Reports
owed** listing all three projects as **REQUIRED** in the warning colour. Nothing on the student's
only home screen distinguishes a week that is finished from one that has not been started.

Reproduce:

1. Sign in as `an.nguyen@example.edu` and land on `/me`.
2. Read the state under the deadline: `Resubmitted`.
3. Read the list below it: `Retrieval baselines — REQUIRED`, `Calibration under drift — REQUIRED`,
   `Korean river — REQUIRED`.

Evidence — the report is submitted and carries a version:

```
GET /api/v1/periods/{id}/report
{"workflow_state":"resubmitted","first_submitted_at":"2026-09-17T03:54:12Z",
 "current_version_id":"01a0b207-86c4-…"}
```

and every obligation is nevertheless `required`:

```
GET /api/v1/periods/{id}/obligations
[{"project_id":"01a0ad80-2427-…","state":"required"},
 {"project_id":"01a0ad80-2442-…","state":"required"},
 {"project_id":"01a0af97-3f6b-…","state":"required"}]
```

**Cause.** `ObligationState` has exactly two values — `REQUIRED` and `EXCUSED`
([backend/app/reporting/models.py:35](backend/app/reporting/models.py#L35)). It answers *does this
project have to be in the package*, not *has it been*. Submitting never changes it, and nothing is
wrong with that; what is wrong is that
[StudentHomePage.tsx](frontend/src/features/me/pages/StudentHomePage.tsx) renders that flag under
the heading `me.obligations` = **"Reports owed"**, in `text-warn`, as though it were a to-do list.

The fulfilment computation this screen needs already exists and is already correct about a
partially submitted package: `unfulfilled_entries`
([backend/app/reporting/service.py:624](backend/app/reporting/service.py#L624)) — *"an obligation
is unfulfilled when no package has been submitted or a required project entry is missing, with no
recorded exemption and no extension still running"* (REP-08). It is reachable today only through
`GET /overview`, which is professor-only, and through the assistant, which a student does not have.
So the professor's screen can tell the difference and the student's cannot.

**Suggested fix.** Carry fulfilment to the student — either as a field on the obligation payload
(`fulfilled: bool`, computed by `unfulfilled_entries`, which the fact layer already filters to the
caller's own rows) or as a student-reachable route. Then `/me` can render *Submitted* / *Owed*
instead of *Required* / *Excused*, and the warning colour can mean something.

---

## 2 — Reopening a submitted week can show an empty form, and resubmitting overwrites it with blanks

**Severity: High — silent loss of a student's submitted work.**

The report editor recovers the **autosaved draft** and nothing else:

```tsx
// frontend/src/features/report/pages/ReportEditorPage.tsx
const saved = (report.data?.draft_content as { entries?: Drafts })?.entries ?? {};
for (const obligation of required) {
  initial[obligation.project_id] = saved[obligation.project_id] ?? emptyEntry(...);
}
```

Nothing reads `current_version_id`, and `GET /report-versions/{id}` — which answers for a student,
verified 200 — is called by no screen in the app.

So when a report has been submitted but no draft is stored, the student opens their week to five
empty boxes and an enabled **Submit report** button. That is not a hypothetical state: `seed.py`
calls `reporting_service.submit_report` directly and never saves a draft, so every seeded report is
in it, and so was An Nguyen's at the start of this session (`draft_content: {}`,
`workflow_state: resubmitted`).

The second half is the damaging one. `submit_report`
([backend/app/reporting/service.py:357](backend/app/reporting/service.py#L357)) checks that the
package covers every required project and validates **nothing about the content** — no field is
required to be non-empty. A student who reopens a submitted week, sees blanks, and presses Submit
writes a new current version in which every entry is empty.

That has already happened on this deployment. Version 2, submitted 2026-09-18T01:00:32Z, reads:

```
GET /api/v1/report-versions/01a0b207-86c4-…
"version_no": 2, "entries":[
  {"project_id":"01a0ad80-2427-…","work_performed":"","results":"","deviations":"",
   "next_plan":{},"questions":"","hours":null}, … ×3 ]
```

Three entries, every text field empty, on a report whose `first_submitted_at` is the day before.
History is retained — `version_no` increments and nothing is deleted — but `current_version_id`
now points at the blank one, and that is what the professor and the assessment pipeline read.

**Suggested fixes**, in order of how much they buy:

- Seed the editor from the last submitted version when there is no draft. The endpoint exists.
- Refuse a submission in which every field of every entry is empty, or warn before sending one.
- Say on the screen that the week has already been submitted, and when. Right now a submitted week
  and an untouched one are pixel-identical.

---

## 3 — An attached file is never read: "READING…" forever

**Severity: High.** Attaching evidence is half of REP-04, and the half that makes it searchable and
citable never completes.

Reproduce: open `/report/{current period}`, attach any file, wait.

Two files, attached ten minutes apart, polled for three minutes each:

```
01:21:48 probe2.md=pending probe.md=pending link=ok
01:22:08 probe2.md=pending probe.md=pending link=ok
  … unchanged through …
01:24:08 probe2.md=pending probe.md=pending link=ok
```

`probe.md` was still `pending` nine minutes after its `confirm` returned 200. The badge reads
**READING…** the whole time — the panel's polling works correctly, there is simply never anything
new to show.

A **link** attached in the same panel reaches `ok` immediately, because links are fetched inside
the request. Only the deferred path is affected — `defer_extraction` →
`reporting.tasks.extract_artifact`, introduced by fae2f68 ("a job reads it seconds later").

Worth noting for whoever picks this up: `GET /api/readyz` reports
`{"worker":"ok","database":"ok","object_storage":"ok","smtp":"ok"}`, so whatever is wrong is not
visible to the readiness check, and `defer_extraction` deliberately swallows a failed enqueue —
*"a job that was never queued is a file that reads late rather than an upload that was lost"*. The
student is told nothing either way.

The bytes are safe: `GET /artifacts/{id}/download` returns a working signed URL and the file
downloads intact. What is lost is the extracted text, so the attachment never reaches the evidence
index or an assessment snapshot.

---

## 4 — No web font loads, on any page

**Severity: Medium.** Every page renders in fallback fonts.

`index.html` links `fonts.googleapis.com`, and the response header is:

```
content-security-policy: default-src 'self'; img-src 'self' data: blob:;
  style-src 'self' 'unsafe-inline'; connect-src 'self' https://objects.research.ecomind.dev;
  frame-ancestors 'none'
```

No `font-src`, and `style-src` does not allow the Google Fonts origin. The browser reports it on
every page load:

> Loading the stylesheet 'https://fonts.googleapis.com/css2?family=Newsreader…' violates the
> following Content Security Policy directive: "style-src 'self' 'unsafe-inline'".

`document.fonts` is empty; `<h1>` computes to `Newsreader, Georgia, serif` and paints as Georgia.
Newsreader, IBM Plex Sans and IBM Plex Mono are never delivered.

Either add `https://fonts.googleapis.com` to `style-src` and `https://fonts.gstatic.com` to
`font-src`, or self-host the three families and drop the external link. Self-hosting also removes
the `preconnect` round-trip the page currently pays for nothing.

---

## 5 — Every timestamp is rendered in Asia/Ho_Chi_Minh regardless of the workspace

**Severity: Medium.** A workspace in another timezone shows every deadline in Vietnam time.

[frontend/src/lib/dates.ts](frontend/src/lib/dates.ts) opens with *"Dates are stored in UTC and
displayed in the workspace timezone (requirements REP-01). The workspace timezone arrives with the
session"*. It does not:

- `GET /api/v1/auth/me` returns `id, workspace_id, role, email, display_name, state,
  deactivated_at, created_at` — no timezone.
- `formatInstant(iso, timeZone = DEFAULT_TIMEZONE, …)` takes the parameter, and **all eleven**
  call sites across the app pass one argument. `DEFAULT_TIMEZONE` is `"Asia/Ho_Chi_Minh"`.
- A student cannot fetch it themselves: `GET /workspaces/{id}` is professor-only.

So the workspace timezone a professor sets on `/workspaces` changes the deadline the backend
computes but not the deadline any screen displays. The deadline on `/me` reads
`Sep 20, 2026, 23:59 GMT+7` for every workspace in the deployment.

Fix: return `timezone` on the session and thread it through `formatInstant`.

---

## 6 — The assessment screen names the project by a fragment of its UUID

**Severity: Medium.** `/me/assessments/:id` — the destination of "Published to the student" —
is headed:

> **Week on project 01a0ad80**

[MyAssessmentPage.tsx](frontend/src/features/me/pages/MyAssessmentPage.tsx) renders
`t("myAssessment.for", { project: String(data.project_id).slice(0, 8) })` and never looks the title
up. `/me/profile`, one click earlier, resolves the same project to **Retrieval baselines** from the
already-cached `useProjects()`. Worse, the fragment is not even distinguishing: every seeded id
begins `01a0ad80`, so two assessments on two different projects are headed identically.

The page otherwise reads well — ratings, the per-dimension rationale, the confidence badge, the
released-at stamp and the correction form all render correctly, and the correction request itself
works (see below).

---

## 7 — "a report for it is owed from next week" — it is owed the same day

**Severity: Medium.** The note under **Start a project** on `/projects` says:

> Your project is active as soon as you create it, and you are on it — so a report for it is owed
> **from next week**.

Commit 21a0a72 changed exactly that: *"A membership acquired by starting a project now owes the
week it lands in, where before it owed from the next one"*, and *"a student who starts a project
late on a Sunday now owes a report by 23:59 that night"*. The copy was not updated with it.

Verified in the browser: An Nguyen had 3 obligations for the current week, created a project
through the form, and the current week's obligations became 4 immediately, including the new
project. The report editor grew a fourth tab, for a week that had already been submitted.

The same sentence appears on the joinable panel (`projects.joinableNote`), where it *is* correct —
joining still owes from the following week. That is what makes the wrong one hard to spot.

This matters more than ordinary stale copy: it tells a student a deadline that is not their
deadline, on the screen where they take the action that creates it.

---

## 8 — Leaving a project is irreversible, unconfirmed, and gives no feedback

**Severity: Medium.**

**Done this project** on `/projects/:id` ends the membership on the first click. There is no
confirmation step, and a student cannot undo it: rejoining requires the professor to have set
`open_to_join`. By contrast, removing a single attachment *does* confirm — *"Remove probe.md? The
file and its extracted text are deleted…"* — so the app asks before the small irreversible thing
and not before the large one.

Afterwards the screen barely moves. It stays on the project, the heading and description are
unchanged, no message appears, and the only sign it worked is that **Members** now reads *"Nobody
is assigned to this project."* The button itself disappears, which is the clearest feedback there
is, and it is easy to miss below the fold.

The obligation for the current week correctly survives the departure, matching the "from next week"
wording on the button's own note — but the student is then left with a report tab for a project
they have just left and no explanation of why it is still there.

---

## 9 — The autosave clock and the deadline beside it are in different timezones

**Severity: Low**, but it is on the screen where the time is the point.

On `/report/:periodId`, the footer reads `Saved 1:07:13 AM` while the header reads
`Due by Sep 20, 2026, 23:59 GMT+7`. `AutosaveIndicator` uses `savedAt.toLocaleTimeString()` — the
*browser's* zone — while every other timestamp goes through `formatInstant`. A student abroad sees
their save in local time and their deadline in workspace time, side by side, unlabelled.

Folds into #5: once the session carries the workspace timezone, format this through the same
helper.

---

## 10 — Trajectory cards label the rubric with a fragment of its UUID

**Severity: Low.** On `/me/profile`, each trajectory card carries `rubric 01a0ad80`
([Trajectory.tsx](frontend/src/features/assessments/components/Trajectory.tsx),
`(point.rubric_version_id ?? "").slice(0, 8)`).

The component's own docstring explains why the label is there — *"a change of rubric is a change of
the measure, and a trend read across one is not a trend"* — which is exactly why it should say
something a student can act on: a rubric name and version, or at minimum "rubric A / rubric B"
within the card set. A truncated UUID conveys only "these two differ", and only if the student
notices the first eight characters changed.

---

## 11 — A past member disappears from the member list entirely

**Severity: Low.** After An Nguyen left the QA project, `GET /projects/{id}/members` returned `[]`
and the screen read *"Nobody is assigned to this project."*

Both the policy and the docs say otherwise. `membership_visible_to` is documented *"UI-03: members
of a project see who else works on it, **including past members**"*, and use_cases §8.4 lists the
member list "including past members" among what a project membership reveals. The gap is in the
caller: `list_members(..., include_past: bool = False)` supports it and **no frontend code passes
`include_past` anywhere**. So PROJ-02's "keep the row" is preserved in the database and invisible
in the product — a project's history of who worked on it cannot be read from any screen.

---

## 12 — An empty-state note shown under a non-empty list

**Severity: Low.** `/me/profile` lists one approved assessment and then, immediately below it,
prints *"An assessment appears here once your professor has approved it."*
[MyProfilePage.tsx](frontend/src/features/me/pages/MyProfilePage.tsx) renders `me.releasedNote`
unconditionally, outside the `released.length === 0` branch that guards the real empty state a few
lines above.

---

## 13 — An unknown period id reads as "no reporting period has been configured"

**Severity: Low.** `/report/01a0ad80-0000-7000-8000-000000000000` returns 404 from the API and the
screen says *"No reporting period has been configured yet."* — the message for a workspace whose
calendar has never been set up. A student following a stale link is told the system is unconfigured
rather than that the week does not exist.

---

## 14 — A link into a professor-only screen drops the student on `/me`, silently

**Severity: Low; already recorded** in use_cases §1, and confirmed here rather than discovered.
`/overview`, `/people`, `/workspaces`, `/assistant`, `/students/:id`, `/review/:id` and any
unrecognised path all redirect a student to `/me` with nothing said. The click is lost and the
screen gives no reason. Noted because §1 predicts it will happen in normal use — the member names
on `/projects/:id` point at `/students/:id`, which a student cannot open — and because it is the
one defect in this list the documentation already knows about.

---

## What worked

Worth recording, because most of the student's loop is sound:

- **Sign in, sign out, session expiry.** A wrong password says *"invalid email or password"*; the
  rate limiter returns 429 and the form says so; sign-out clears the session and a subsequent
  `/me` correctly bounces to `/login`.
- **Autosave.** Debounced, visible, and honest about its state. Switching tabs preserves per-project
  drafts, a reload recovers them, and merely opening the editor does not create a draft.
- **Submission.** Version numbering, the completeness check across required projects, and the
  "Submitted as version 3" confirmation all behave as specified.
- **Attachments.** Upload (browser-hashed, straight to object storage, checksum confirmed), link
  attachment with real fetch-and-extract, removal with a confirmation naming the file, and working
  signed download links. Only the deferred text extraction is broken (#3).
- **The correction request.** Posts, clears the box, appears in the thread as *"Your correction
  request"* with a timestamp, and survives a reload.
- **Creating and editing a project.** `POST` and `PATCH` both work from the student's own screen,
  the repo-URL field validates, and a student correctly gets no edit form on a project they did not
  create.
- **Access control.** Every professor-only screen refused; `GET /assessments/{id}/evidence` is
  never requested, as `MyAssessmentPage.test.tsx` requires.
- **Mobile layout.** At 390 × 844 all three student screens fit with no horizontal overflow and no
  element extending past the viewport.

---

## Test residue on the deployment

Created while testing, and not removable through the student UI:

- **Report version 3** for An Nguyen, week of 14–20 Sep, whose three entries read
  `QA v3 work performed for tab N` / `QA v3 results N`. Version 2 (all blank, the subject of #2)
  and version 1 are intact behind it.
- **Project "QA probe project (edited)"**, created and then left. It has no members; An Nguyen
  retains access as its creator, which is AUTH-07 working as designed.
- **A correction request** on assessment `01a0ad80-2ce4-…`, text beginning *"QA correction
  request: the rigor rating…"*.
- **Drafts** on the current week's report reflecting the above.

The three test attachments (`probe.md`, `probe2.md`, and a link to example.com) were deleted at the
end of the run; no seeded attachment was touched.
