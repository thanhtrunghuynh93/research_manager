# QA report — the student role on research.ecomind.dev, third pass

**Tested** 18 September 2026, 11:35–12:05 UTC, against the live deployment at
`https://research.ecomind.dev` (api/worker/caddy rebuilt 11:25 UTC, which is newer than the build
the second pass verified against).
**As** `an.nguyen@example.edu` (An Nguyen, student).
**With** Playwright/Chromium driving the real UI: sign in through the form, click what a student
can click, read what a student reads. API calls are quoted only as evidence for what a screen
showed, never as a substitute for it.

**Scope** — the brief was the student role generally and **report browse and submit** in
particular, so the weekly package got the weight: opening the week, every tab, the draft and its
autosave, evidence (file, claim, link, download, removal), submission and resubmission, what the
editor says about what is on the record, out-of-range and empty input, other and malformed
reporting periods. Around it, the same ground as the earlier passes: `/me`, projects, the released
assessment and correction request, sign-in and sign-out, the role guards, mobile and a light
accessibility sweep.

**This pass found 10 defects, 2 of them serious.** The first is the one to read: **any validation
error the API raises on the report screens blanks the entire application** — not the form, the
whole page, nav included, with no way out but a manual reload. A student reaches it by typing a
negative number in the optional Hours box and pressing the only button on the screen. The second is
that **a student can no longer create a project unless they fill in the field the form itself
labels "Optional"**; leaving the Git repository box empty returns HTTP 500.

Both are regressions against the second pass, which recorded project creation as working and found
no crash of this kind. Both are in code that is currently uncommitted in the working tree.

**Re-checked from the earlier passes and still fixed:** submitting after leaving a project
(pass 2 #1, re-verified with seven departed projects), the resubmission carrying a departed
project's entry (#2), the plan shape (#3), the unknown-period message (#4), the week named on an
assessment (#6), link validation (#7), download offered only on files (#8), `/me` owing counts (#9),
the attachment claim (#10, #11), the tab strip's ARIA **and now its arrow keys** (#14), no fetches
on a project the student has left (#15), the autosave timezone (#17), and version numbering (#18).

---

## Summary

| # | What a student sees | Severity |
| --- | --- | --- |
| 1 | **A validation error blanks the whole app** — "Unexpected Application Error!", no nav, reload is the only way back. Three student-reachable triggers found | **High** |
| 2 | **A project cannot be created with the "Optional" repository field left blank** — HTTP 500. Clearing it on an existing project fails the same way | **High** |
| 3 | An entry with every box empty submits, and the week reads **Submitted** | Medium |
| 4 | The editor names the **first** submission time for ever — it said "Submitted Sep 17" in the same breath as "Submitted as version 16" | Medium |
| 5 | The Hours box publishes limits it does not enforce, and enforces one the server does not have | Medium |
| 6 | A link that cannot be fetched reports the internal exception class: `(HTTPStatusError)` | Low |
| 7 | Removing a link says a **file** is being deleted, and calls a link with no path just "link" | Low |
| 8 | `/me/profile` still hides the low-confidence reasons in a hover tooltip | Low |
| 9 | A correction request of three spaces is accepted and filed | Low |
| 10 | **A submitted report can never be read back** — the editor shows the draft, there is no history, and one entry of every version is invisible | Low |

---

## 1 — A validation error from the API blanks the entire application

**Severity: High.** The student loses the whole screen, including the navigation, and only a manual
reload brings it back. Nothing on the page explains what happened or what to do.

Reproduce, from a signed-in student:

1. Open the week (`/me` → **Open this week**).
2. In **Hours (optional)** on any tab, type `-1`.
3. Press **Submit report**.

The page becomes:

> **Unexpected Application Error!**
> Minified React error #31; visit https://reactjs.org/docs/error-decoder.html?invariant=31&args[]=object%20with%20keys%20%7Btype%2C%20loc%2C%20msg%2C%20input%2C%20ctx%7D …

`<main>` is gone (`document.querySelectorAll('main').length === 0`), and so is the header nav —
there is no link left to click. The draft is safe, because autosave had already stored it, but the
student has no way to learn that.

**Two other routes to the same screen, both reachable by a student:**

- **A malformed reporting period in the URL.** `GET /report/not-a-uuid` → the path parameter fails
  to parse → same blank error page. A *well-formed* unknown id is handled properly
  ("That reporting week does not exist, or is not one of yours."), and `/me/assessments/not-a-uuid`
  is handled properly too ("This assessment is not available to you."), so this route is the odd
  one out.
- **A link longer than 2000 characters** in **Or a link** → `POST /api/v1/artifacts/links` → 422 →
  same blank error page.

**Why.** The API answers with two different error shapes on the same endpoints. The application's
own errors are RFC 9457 with a string `detail`:

```json
{"type":"about:blank","title":"Validation failed","status":422,
 "detail":"the package is missing an entry for every required project"}
```

FastAPI's request-validation errors are not, and `detail` is an array of objects:

```json
{"detail":[{"type":"greater_than_equal","loc":["body","entries",0,"hours"],
            "msg":"Input should be greater than or equal to 0","input":-5,"ctx":{"ge":0}}]}
```

[client.ts:12](frontend/src/api/client.ts#L12) types `Problem.detail` as `string`, and
[ReportEditorPage.tsx:211](frontend/src/features/report/pages/ReportEditorPage.tsx#L211) renders it
straight into the tree:

```tsx
{missing ? t("report.missingEntries", { projects: missing }) : problem.detail}
```

React renders an array as a list of children, each child here is an object, and that is React error
#31 — which the route's error boundary turns into the blank page. `Attachments.tsx` puts the same
value through `setError` at [lines 118, 133, 158 and 216](frontend/src/features/report/components/Attachments.tsx#L118),
which is the long-link route.

The fix is one place: normalise the problem in `client.ts` so `detail` is always a string before it
reaches a component. Every screen that renders `problem.detail` is exposed until then, not only
these three.

## 2 — A project cannot be created unless the optional repository field is filled in

**Severity: High.** This is the student's own "Start a project" form, and the common case — a
student starting a project before there is a repository — fails outright.

Reproduce: `/projects` → **Start a project** → type a title → leave **Git repository** empty →
**Create project**. The screen answers:

> An unexpected error occurred.

`POST /api/v1/projects` → **500**, `request_id: "-"`. Isolating the field, with everything else
held constant:

| Body | Result |
| --- | --- |
| `{title, stage}` — `repo_url` absent | **201** |
| `+ description: ""` | **201** |
| `+ research_questions: []` | **201** |
| `+ repo_url: null` | **500** |
| `+ repo_url: ""` | **500** |
| `+ repo_url: "https://github.com/example/qa3"` | **201** |

So the project is created only when the optional field carries a value. The form always sends the
key, so from the UI the field is effectively required.

The same shape breaks editing: on **Korean river**, clearing **Git repository** and pressing
**Save** gives `PATCH /api/v1/projects/{id}` → 500 and the same "An unexpected error occurred."
A repository URL, once set, cannot be removed.

The server log names it exactly:

```
File "pydantic/_internal/_validators.py", line 340, in max_length_validator
    raise TypeError(f"Unable to apply constraint 'max_length' to supplied value {x}")
TypeError: Unable to apply constraint 'max_length' to supplied value None
```

[schemas.py:41](backend/app/projects/schemas.py#L41):

```python
RepoUrl = Annotated[str | None, AfterValidator(normalize_repo_url), Field(max_length=500)]
```

`normalize_repo_url` turns blank and `None` into `None` — deliberately, and the docstring explains
why — and then `max_length` is applied to that `None` and raises. It is used by `ProjectIn`
([line 97](backend/app/projects/schemas.py#L97)) and `ProjectPatch`
([line 111](backend/app/projects/schemas.py#L111)), which is why create and edit fail together.

Two things are worth fixing, not one: the constraint order, and the fact that a `TypeError` inside
request validation reaches the client as a 500 with `request_id: "-"` instead of being caught.

## 3 — An entry with every box empty submits, and the week reads Submitted

**Severity: Medium.**

On the **Calibration under drift** tab, clear **Work performed**, **Results and research learning**,
**Deviations and blockers**, **Next-week plan**, **Questions** and **Hours** — every field on the
tab — and press **Submit report**. The answer is:

> Submitted as version 10.

Nothing warns that the entry is empty, and nothing marks it afterwards. The record that results:

```json
{"version_no": 10,
 "entries": [{"project_id": "01a0ad80-2442…", "work_performed": "", "results": "", "hours": null}, …]}
```

and the obligation reads `state=required, submitted=true`. The tab reads **SUBMITTED**, `/me` reads
**Resubmitted**, and nothing anywhere distinguishes this week from one with work in it. A student
can satisfy the week's obligation on every project by pressing one button, and the screens that a
professor and a student both read will agree that the week was reported.

Whether an empty entry should be refused or merely called out is a product decision, but silently
counting it as a report is not defensible from either side.

## 4 — The editor keeps naming the first submission, whatever is actually on the record

**Severity: Medium.**

Above the tabs, the editor prints:

> Submitted Sep 17, 2026, 10:54 GMT+7 — sending again replaces it

It printed exactly that at 18:59 GMT+7 on 18 September, immediately after printing:

> Submitted as version 16.

The record at that moment:

```
first_submitted_at = 2026-09-17T03:54:12Z      (Sep 17, 10:54 GMT+7 — what the screen shows)
current version    = 16, submitted_at 2026-09-18T11:59:13Z   (Sep 18, 18:59 GMT+7)
```

[ReportEditorPage.tsx:159](frontend/src/features/report/pages/ReportEditorPage.tsx#L159) reads
`report.data.first_submitted_at` into the `alreadySubmitted` string. The page already fetches the
current version, so `submitted_at` is in hand.

This matters near a deadline: the sentence a student reads to check that this week's work went in
names a time that can be days old, and the word it uses — "Submitted" — is the one `/me` reserves
for a week that has *not* been sent again (`/me` says **Resubmitted** for the same report).

## 5 — The Hours box publishes limits it does not enforce, and enforces one the server has not got

**Severity: Medium.** This is what makes #1 easy to reach.

The control is `<input type="number" min="0" max="168" step="0.5">`. Nothing gates the submission
on it, so a value the browser has already marked invalid is sent anyway:

| Typed | `checkValidity()` | What happens on Submit |
| --- | --- | --- |
| `-5`, `-1` | false | 422 → **the blank error page of #1** |
| `200`, `1e5` | false | 422 → **the blank error page of #1** |
| `3.75` | **false** | accepted by the server — `hours` has no step constraint |
| `abc` | n/a | the field silently empties as it is typed |

So the field rejects `3.75` in the browser — a student logging 3 h 45 min sees an invalid control —
for a value the API stores happily, and accepts `-5` and `200`, which the API refuses. The
constraint is in the wrong place at both ends. Refusing the submission in the browser, with a
message beside the field, would close #5 and remove one of the three routes into #1.

## 6 — A failed link fetch reports the internal exception class

**Severity: Low.**

Attaching `https://example.org/qa3-note` (which 404s) puts this on the evidence row:

> the link could not be fetched (HTTPStatusError)

`HTTPStatusError` is httpx's class name. A student cannot act on it, and it says nothing that
"the site returned 404" would not say better. A link that resolves is handled properly —
`https://example.com/` came back **TEXT EXTRACTED**.

## 7 — Removing a link says a file is being deleted

**Severity: Low.**

The confirmation for a link is the file one, unchanged:

> Remove link? **The file and its extracted text are deleted**, and it stops being searchable.

Two problems in one sentence. Nothing is deleted but the reference — the page at the other end is
not the student's to delete — and the name is "link" because `https://example.com/` has no path
segment to take a name from. A link with a path fares better: `https://example.org/qa3-note` gave
*"Remove qa3-note?"*. The file wording is right for files: *"Remove qa3-probe.md? The file and its
extracted text are deleted…"*.

## 8 — `/me/profile` still hides the low-confidence reasons in a tooltip

**Severity: Low.** Recorded as fixed in the second pass; it was fixed in one of the two places.

The assessment **detail** page is now right — the reasons are on the page as text:

> LOW CONFIDENCE · 2
> no report was submitted for this week
> no plan baseline was in effect, so commitment completion is unavailable

The **list** on `/me/profile` is not:

```html
<span title="no report was submitted for this week
no plan baseline was in effect, so commitment completion is unavailable"
      class="chip uppercase chip-bad cursor-help">Low confidence · 2</span>
```

A hover tooltip is unreadable on a touch screen and unreachable from the keyboard, and "· 2" does
not say what the 2 are. The information is one click away on the detail page, which is why this is
Low rather than Medium.

## 9 — A correction request of three spaces is accepted and filed

**Severity: Low.**

In **Ask for a correction**, typing three spaces and pressing **Send correction request** gives
`201` and files the request against the assessment. The API's `minLength: 1` counts whitespace.

With the box genuinely empty the button stays enabled and clicking it does nothing at all — no
request, no message. Two small fixes: trim before validating, and disable the button when the
trimmed value is empty so the control is never dead.

## 10 — A submitted report can never be read back

**Severity: Low as a defect, but it is the gap behind the brief's "browse".**

There is no screen on which a student can read what they submitted:

- The editor always shows the **draft**, never the submitted version. Where the two differ, the
  screen shows the one that is not on the record.
- There is **no version history**. Sixteen versions exist for this week; the editor mentions a
  number only in the flash message after a submission.
- **One entry of every version is invisible.** Version 16 carries four entries; the editor shows
  three tabs. The fourth is `Retrieval baselines`, the project An Nguyen left, carried forward by
  the fix for pass 2 #2 — correctly kept on the record, and unreachable from any student screen.

That last one contradicts a promise the product makes in writing. The project page for a project
the student has left says:

> You left this project on Sep 18, 2026. **The record stays readable because your reports and
> assessments refer to it**; its milestones, decisions and members are no longer shown.

The assessments are readable. The reports are not.

---

## What worked

- **Submitting, and submitting again.** Sixteen versions across the session, every one `201`, the
  version number reported on screen each time, `/me` and the tabs agreeing afterwards.
- **Submitting after leaving projects** — pass 2's blocker. Re-tested with **seven** departed
  projects on the account: **Submitted as version 11**, no phantom obligations, tabs back to three.
- **The draft and its autosave.** Debounced, honest (`Not saved yet` → `Saved 18:39:10 GMT+7`, with
  the zone), recovered across reloads, and kept intact when the student navigates away mid-sentence
  — text typed and abandoned within a second was still in the draft afterwards.
- **Submit is guarded against a double-click.** The button disables for the whole request; a real
  `dblclick` posts once. (Three clicks dispatched in the same tick do get two versions through, but
  that is not something a hand can do.)
- **Evidence.** Upload with browser-side hashing, the claim recorded on the row it belongs to and
  the box cleared afterwards, a resolving link extracted, a signed download that delivered the file
  byte-for-byte, and removal that confirms by name. All test attachments removed cleanly.
- **The assessment.** The week is named in the heading, the release time is given, the ratings carry
  their evidence counts, and the correction request posts and appears in the thread.
- **Leaving a project.** Confirms by name, explains that rejoining needs the professor, and the
  project page afterwards explains the state in a sentence.
- **Access control.** `/overview`, `/people`, `/review`, `/calendar`, `/assistant`, `/settings` and
  a project's milestones all refused, each landing on `/me` **with the path it turned the reader
  away from named on screen**. Setting a project's status was refused with *"only the professor may
  change: status"*.
- **Error states on unknown ids.** A well-formed unknown period and both unknown and malformed
  assessment ids all say something useful. (A malformed *period* id is #1.)
- **Sign-in, sign-out and rate limiting.** A wrong password says *"invalid email or password"* with
  the form intact; sign-out returns to `/login` and `/me` bounces back to it. Repeated sign-ins are
  rate-limited and say so plainly — *"Too many attempts. Wait and try again."* — which is correct
  behaviour and was the cause of several flaky runs in this session, not a defect.
- **Mobile.** At 390 × 844, `/me`, the report editor, `/projects` and `/me/profile` all had
  `scrollWidth == innerWidth` and no element past the viewport.
- **Accessibility basics.** `lang="en"`, one `h1`, `header`/`nav`/`main` landmarks, every control in
  `main` labelled, one `tabpanel` with `aria-controls` from the tab — and the tab strip now moves
  with **arrow keys** and hands focus on to the panel with Tab, which closes pass 2 #14 fully.
- **No uncaught page errors** on any screen except the three in #1.

## Not covered

- **Late and missed submissions.** The deadline for the open week is 20 September; there is no
  student screen that moves it, and this pass did not reach past the UI to force one. The
  `timing_status: "on_time"` path is all that was exercised.
- **Past weeks.** 14–20 September is still the first period in the calendar, so `PastWeeks` on `/me`
  has nothing to render and the plan carry-over has no previous week to read. Both still want
  re-testing after 21 September, as the second pass said.
- **Joining an open project.** `GET /projects/joinable` still returns `[]`, and the panel is hidden
  when empty, so neither it nor `POST /projects/{id}/join` could be driven from the UI.
- **Accepting an invitation and resetting a password.** Both need a token from an email, and this
  pass ran against the deployment rather than the mock stack's mailpit.
- **A professor's view of what this student submitted.** Testing was confined to the student role,
  so whether the empty entry of #3 looks empty on the review screen is untested.

## Test residue on the deployment

Created while testing, and not removable through the student UI (there is no `DELETE /projects`, by
design):

- **Five projects, `QA-3 test residue 1 (ignore)` … `5`.** Created while isolating #2, renamed to
  say so, and **left** through the product's own "Done this project" button, so none of them owes a
  weekly report. Only a professor can archive them.
- **Report versions 6–16** on the week of 14–20 September. Version 16 is current and was written
  deliberately at the end of the run to **restore the report's content**: the three owed projects
  carry the text they had before this pass, the empty entry of #3 is gone, hours are back to their
  original values, and the carried-forward `Retrieval baselines` entry is intact. Versions 1–5 are
  the earlier passes'.
- **One correction request of three spaces** on assessment `01a0ad80-2ce4-…`, from #9. A student
  cannot withdraw it.
- The second pass's residue is untouched: `QA3 seasonality probe`, `QA probe project (edited)`, and
  the earlier correction request.

Everything else was cleaned up: the two probe attachments (`qa3-probe.md` and two links) were
removed through the UI and `GET /artifacts` for that project returns `[]`.
