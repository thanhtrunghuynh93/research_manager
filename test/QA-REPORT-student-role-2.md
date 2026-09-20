# QA report — the student role on research.ecomind.dev, second pass

**Tested** 18 September 2026, against the live deployment at `https://research.ecomind.dev`.
**As** `an.nguyen@example.edu` (An Nguyen, student).
**With** Playwright/Chromium driving the real UI: sign in through the form, click what a student
can click, read what a student reads. API calls are quoted only as evidence for what a screen
showed, never as a substitute for it.

**Scope** — a re-run of the first pass ([QA-REPORT-student-role.md](test/QA-REPORT-student-role.md))
over the same ground: the week and its obligations, the report editor and its autosave, attachments
(file, link, removal, download), submission, the released assessment and the correction request,
the trajectory, projects (list, create, edit, leave), sign-in errors, sign-out, the role guards,
mobile layout, and a light accessibility sweep.

**All 14 defects from the first pass are fixed.** §Verified records each one against the screen
that had it. This pass found 18 new ones, and the first is the reason the report is worth reading
today: **An Nguyen cannot submit a weekly report at all.** Three of the eighteen came in with the
fixes for the old ones — #1 with the departed-project filter, #4 with the version-recovery guard,
#16 with the notice that explains a redirect — so all three are worth a regression test rather than
only a patch.

**Status: all 18 are fixed, and the fixes are deployed.** Every one was re-checked through the
live UI afterwards; the run is in §Verified on the deployment at the end.

**#18 was found after the rest were fixed**, on the deployment, and is in the table below with
them: correcting #1 was what let a submission get far enough to hit it.

One entry, #16, **was reported in error and is corrected in place**: the silent redirect the first
pass recorded is fixed, and this pass repeated the finding because it checked where the browser
landed without reading the page it landed on. What is left there is smaller and real, and is
written up under that number.

---

## Summary

| # | What a student sees | Severity |
| --- | --- | --- |
| 1 | After leaving a project, **submitting any week fails** — "the package is missing an entry for every required project", naming projects the screen no longer shows | **High — blocker** |
| 2 | A resubmission drops the entry for a project left mid-week out of the current version | **High (latent behind #1)** |
| 3 | The next-week plan a student types is written in a shape nothing reads — the plan baseline never carries | Medium |
| 4 | `/report/{unknown period}` hangs on **Loading…** for ever | Medium |
| 5 | The reasons an assessment is low-confidence are a hover tooltip and a bare "· 2" | Medium |
| 6 | A released assessment never says **which week** it assesses | Medium |
| 7 | The link box accepts any string and creates a permanently broken attachment, silently | Medium |
| 8 | **Download** on a link attachment throws and does nothing | Medium |
| 9 | `/me` reads **Submitted** for a week that still has a project marked REQUIRED | Medium |
| 10 | "What does this show?" is recorded and then never shown again | Low |
| 11 | The claim box is shared by the panel and applies only to the next attachment | Low |
| 12 | The failed-submission message does not name the projects, though the API returns them | Low |
| 13 | `/me` flashes **Not started / Start this week** on a submitted week | Low |
| 14 | The editor's tabs are `role="tab"` with no panel, no `aria-controls`, no arrow keys | Low |
| 15 | A project the student has left fetches members, milestones, decisions and progress, and renders none | Low |
| 16 | ~~A link into a professor-only screen drops the student on `/me` with no explanation~~ — **reported in error**; it explains itself, but the explanation then repeats on every reload | Low |
| 17 | The autosave clock carries no timezone beside a deadline that does | Low |
| 18 | **A report whose current version is not its latest can never be submitted again** — found while verifying the fix for #1, which was all that had been hiding it | **High** |

---

## 1 — After leaving a project, the student can no longer submit any week

**Severity: High. This is a blocker: there is no way round it from any student screen.**

Leaving a project is documented, on the button's own note, as taking the current week with it:

> This ends your part in it. The project stops appearing in your week, **including this one**, what
> you have already submitted stays on the record…

The obligation list agrees. `GET /periods/{id}/obligations` returns three rows for An Nguyen — the
two projects they are on and the one they started during the session — and the editor renders
exactly those three tabs. The two projects they left (`Retrieval baselines`, `QA probe project (edited)`,
both `viewer_left_on: 2026-09-18`) are gone from both.

The submission endpoint disagrees. Fill the three tabs, press **Submit report**, and the screen
prints, in the error colour:

> the package is missing an entry for every required project

Reproduce:

1. Sign in as `an.nguyen@example.edu`, open `/me`, click **Open this week**.
2. Write something in a tab — or leave the entry the editor recovered from the submitted version.
3. Press **Submit report**. `POST /periods/{id}/report/submit` → **422**, and the error prints
   under the form.

Evidence — the same three entries the screen offered, refused by name:

```
POST /api/v1/periods/01a0ad80-2559-.../report/submit
{"entries":[{"project_id":"01a0ad80-2442-…"},{"project_id":"01a0af97-3f6b-…"},
            {"project_id":"01a0b2d9-0ff8-…"}]}

422 {"title":"Validation failed",
     "detail":"the package is missing an entry for every required project",
     "missing_project_ids":["01a0ad80-2427-7698-948f-aa1410695f0b",
                            "01a0b212-0dd1-7318-97b9-c8b6df1b1fb1"]}
```

Both ids are projects they have left. Neither appears on `/me`, on `/report/{id}`, or in the
obligations payload; `/projects` shows both stamped **LEFT SEP 18, 2026**. A student cannot put an
entry on a project they are not on, and cannot rejoin — rejoining needs the professor to open the
project, which is what the confirmation dialog warns about. **The week is unsubmittable for ever.**

**Cause.** The fix that hid the departed project from the week was applied in two of the three
places that ask, and not in the third. `list_obligations` now filters through
`_obligations_still_owed` → `projects_service.memberships_still_owing`
([backend/app/reporting/service.py:227](backend/app/reporting/service.py#L227)), and
`unfulfilled_entries` filters the same way
([backend/app/reporting/service.py:669](backend/app/reporting/service.py#L669)) so the professor's
outstanding list agrees. `submit_report` still reads the raw table:

```python
# backend/app/reporting/service.py:417
obligations = await repository.list_obligations(
    session, scope, period_id, student_id=report.student_id
)
submitted = {UUID(str(entry["project_id"])) for entry in entries}
_check_package_is_complete(obligations, submitted)
```

`_obligations_still_owed`'s own docstring states the rule it is there to apply — *"an obligation
derived before someone left is still sitting in the table"* — and that is precisely the row
`_check_package_is_complete` is now requiring an entry for.

**Suggested fix.** Have `submit_report` derive its obligations through `_obligations_still_owed`,
so the completeness check is computed from the same set the editor renders tabs from. One line, and
it makes the three callers consistent by construction rather than by three copies of the filter.

There is a second, smaller instance of the same split at
[backend/app/reporting/service.py:1097](backend/app/reporting/service.py#L1097): `_open_report`
will create a report for a period whose only obligations belong to memberships that have ended.

---

## 2 — A resubmission drops the entry for a project left mid-week

**Severity: High, and currently invisible because #1 stops the submission that would cause it.
Whoever fixes #1 has to decide this at the same time.**

`submit_report` writes exactly the entries in the payload
([backend/app/reporting/service.py:446](backend/app/reporting/service.py#L446)); `previous_entries`
is read only to carry `content_changed_in_version_id` forward for an unchanged entry, never to
carry the entry itself. The editor builds its payload from `Object.values(drafts)`
([ReportEditorPage.tsx:108](frontend/src/features/report/pages/ReportEditorPage.tsx#L108)), and
`drafts` is keyed by the current required obligations
([ReportEditorPage.tsx:64](frontend/src/features/report/pages/ReportEditorPage.tsx#L64)).

So once #1 is fixed, the first resubmission after leaving a project writes a current version with
that project's entry absent. On this deployment, version 1 carries a real entry for
`Retrieval baselines`:

```
GET /api/v1/report-versions/01a0ad80-2938-…
{"version_no":1,"entries":[
  {"project_id":"01a0ad80-2427-…","work_performed":"Implemented the corpus loader and wired the
   BM25 baseline through the shared evaluation harness…","results":"BM25 reaches nDCG@10 = 0.412…"},
  {"project_id":"01a0ad80-2442-…", …}]}
```

That entry is the week's record of work that was actually done, and it is what the professor and
the assessment pipeline read through `current_version_id`. Version 1 survives in history, but the
current version would no longer mention the project — which is the opposite of what the button
promises: *"what you have already submitted stays on the record"*.

**Suggested fix.** Carry forward, into the new version, any entry on the previous current version
whose project is no longer an obligation. It is the only reading that keeps the button's copy true,
and it costs nothing at the point of submission — `previous_entries` is already in hand.

---

## 3 — The next-week plan a student types is stored in a shape nothing reads

**Severity: Medium.** Two shapes for `next_plan` are in use, and the one the app writes is not the
one the app reads.

The editor sends (`ReportEditorPage.tsx:114`):

```tsx
next_plan: draft.next_plan_text ? { outcomes: [draft.next_plan_text] } : {},
```

The plan carry-over that turns last week's plan into this week's baseline reads the other
(`service.py:369`):

```python
items = entry.next_plan.get("items") if isinstance(entry.next_plan, dict) else None
…
return [item for item in items if isinstance(item, dict) and item.get("planned_outcome")], entry.id
```

`_carried_plan` is the only place the backend looks *inside* `next_plan` — everywhere
else it is passed through whole — and it feeds
`freeze_baselines` → `projects_service.freeze_baseline` — PROJ-04, *"at the start of a period, fix
the plan each membership will be assessed against"*. A plan typed into the app therefore never
becomes a baseline, and the assessment that follows says so in the student's own words. The
released assessment on An Nguyen's screen carries:

```
GET /api/v1/assessments/01a0ad80-2ce4-…
"confidence": "low",
"confidence_reasons": ["no report was submitted for this week",
                       "no plan baseline was in effect, so commitment completion is unavailable"]
```

The same mismatch runs the other way in the editor. `draftOfEntry`
([entry.ts:39](frontend/src/features/report/entry.ts#L39)) recovers a submitted entry's plan by
reading `next_plan.outcomes` only, so an entry stored in the `items` shape — which is what the
seed writes, and what `_carried_plan` requires — reopens with **NEXT-WEEK PLAN** empty. Given #2's
behaviour that emptiness is then what gets submitted. Version 1 on this deployment is in exactly
that shape:

```
"next_plan": {"items": [{"weight": 1, "planned_outcome": "Run the hybrid fusion baseline"}]}
```

**Suggested fix.** Pick one shape and write it down. `{items: [{planned_outcome, weight}]}` is the
one the backend, the seed and `test_pipeline.py` already use, and it is the one that carries a
weight, which PROJ-04 needs; `{outcomes: […]}` appears only in the client and in the two API tests
that were written against it (`tests/api/test_reports.py:55`,
`tests/module/reporting/test_submission.py:79`). Whichever is chosen, `draftOfEntry` and
`_carried_plan` should be reading the same key, and a round-trip test through both would have
caught this.

I could not exercise the carry-over end to end from the browser: the week of 14–20 Sep is the first
period in the calendar, so there is no previous week for a baseline to come from yet. It will start
mattering on 21 September.

---

## 4 — An unknown or inaccessible period hangs on "Loading…"

**Severity: Medium.** The first pass reported this screen saying the wrong thing; it now says
nothing at all, indefinitely.

`/report/01a0ad80-0000-7000-8000-000000000000`, sampled at 3 s, 10 s and 20 s, reads **Loading…**
every time. The API has already answered:

```
404 GET /api/v1/periods/01a0ad80-0000-…/obligations
404 GET /api/v1/periods/01a0ad80-0000-…/report
404 GET /api/v1/periods/01a0ad80-0000-…/obligations   (one retry, then it gives up)
```

`ReportEditorPage` has the right message and cannot reach it. The loading guard requires
`drafts !== null` ([ReportEditorPage.tsx:88](frontend/src/features/report/pages/ReportEditorPage.tsx#L88)),
`drafts` is only set when `obligations.data` is present
([ReportEditorPage.tsx:64](frontend/src/features/report/pages/ReportEditorPage.tsx#L64)), and
`obligations` errored — so the `!period` branch that would print `report.unknownPeriod` is never
evaluated. The two sibling screens both handle this correctly: `/me/assessments/{bad id}` says
*"This assessment is not available to you."* and `/projects/{bad id}` says *"This project could not
be loaded."*

**Suggested fix.** Handle the error state before the loading state — `if (obligations.isError ||
report.isError)` → the unknown-period message.

---

## 5 — The reasons an assessment is low-confidence are hidden in a tooltip

**Severity: Medium.** `/me/assessments/{id}` shows the progress index as a figure and, beside it, a
red chip reading:

> **LOW CONFIDENCE · 2**

The "2" is a count of reasons, and the reasons are a `title` attribute
([Badges.tsx:53](frontend/src/components/evidence/Badges.tsx#L53)) — a hover tooltip, which does
not exist on a touch device and is not announced as content by a screen reader. The reasons in this
case are the two most useful sentences on the screen:

```
"confidence_reasons": ["no report was submitted for this week",
                       "no plan baseline was in effect, so commitment completion is unavailable"]
```

The component's own docstring sets the standard it is failing — *"ASSESS-06: a level is meaningless
without the rules that produced it, so they are the tooltip"* — and UI-01 asks for the limits of
the evidence to be *visible* beside whatever rests on them. A bare "· 2" is the number of things
being withheld.

On the professor's review screen a tooltip is defensible: they can re-run the analysis and open the
snapshot. On the student's copy this is the whole explanation of why their number is qualified, and
it is the one screen where they cannot ask the system anything else.

**Suggested fix.** On this page, render the reasons as a list under the chip. The page has room —
it is a two-column panel with the index on the left and the chip alone on the right.

---

## 6 — A released assessment never says which week it is for

**Severity: Medium.** The heading is:

> **Week on project Retrieval baselines**

The project title is right — that was the first pass's #6 and it is fixed — but the assessment is
*weekly* (AC-01: one per project per period) and the week is never named. `period_id` is on the
payload the page already has:

```
GET /api/v1/assessments/01a0ad80-2ce4-…
"period_id": "01a0ad80-2559-76f0-a6e9-d333a57947d1", …
```

and `usePeriods` is already loaded on three other student screens, so the dates are one lookup
away. As written, two assessments on the same project — the normal case after a fortnight — carry
byte-identical headings, and the list on `/me/profile` distinguishes them only by the date they
were *released*, which is not the week they are about. The correction form sits under that heading:
a student contesting a rating has nothing on screen naming the week they are contesting.

**Suggested fix.** `Week of 14–20 Sep on Retrieval baselines`, from `period_id`. The eyebrow above
it already reads RELEASED ASSESSMENT, so the word "Week" is carrying no other weight.

---

## 7 — The link box accepts any string, and creates a broken attachment silently

**Severity: Medium.**

Type `not a url` into **OR A LINK** and press **Add link**. The request succeeds:

```
201 POST /api/v1/artifacts/links
```

and the row appears in the evidence list as a clickable link to `not a url`, badged **COULD NOT BE
READ**. Nothing tells the student what went wrong. The reason exists, and is another hover
tooltip:

```
GET /api/v1/artifacts?period_id=…&project_id=…
{"kind":"link","filename":"not a url","source_url":"not a url","extraction_state":"failed",
 "extraction_note":"only http and https links can be fetched; this one uses the missing scheme"}
```

Three things are wrong and they compound. `attachLink`
([Attachments.tsx:119](frontend/src/features/report/components/Attachments.tsx#L119)) checks only
`link.trim()`, so a typo is never caught in the browser. The API accepts it rather than refusing
it, so the mistake becomes a row. And `extraction_note` — the only text that explains it — is in a
`title`, so on a phone the student's evidence list has an item that reads COULD NOT BE READ with no
way to find out why.

The contrast with the rest of the app is sharp: the **GIT REPOSITORY** field on the project form
rejects `nonsense` in the browser with no request sent, and a failed upload prints
`attachment-error` in the error colour.

**Suggested fix.** Validate the scheme in the field, the way the repo-URL field does, and show
`extraction_note` as text on a failed row rather than as a tooltip. The note's wording wants a look
too: *"this one uses the missing scheme"* reads as a bug even when it is describing one.

---

## 8 — "Download" on a link attachment throws and does nothing

**Severity: Medium.** Every row in the evidence list gets a **Download** button
([Attachments.tsx:169](frontend/src/features/report/components/Attachments.tsx#L169)), including a
link, which has no stored bytes. Clicking it on a link row:

```
404 GET /api/v1/artifacts/{id}/download
[pageerror] this artifact has no stored version
```

The URL does not change, no message appears, and nothing else on the screen moves. `openArtifact`
([queries.ts:175](frontend/src/features/report/queries.ts#L175)) is two statements with no
`catch`, and the call site `void`s the rejected promise, so the failure reaches the browser console
and stops there. From the student's side the button is simply dead.

The same component already knows the difference — it renders a link's row as an `<a>` to
`source_url` *because* a link has no filename worth showing, with the comment *"A file has none,
and that is how the two are told apart."* The button is the one place that distinction was not
applied.

**Suggested fix.** Render **Download** only when `source_url` is null, and give `openArtifact` a
`catch` that sets the panel's existing `error` state, so any other download failure is visible too.

---

## 9 — `/me` reads "Submitted" for a week that is not finished

**Severity: Medium.** The state under the deadline is the report's workflow state
([StudentHomePage.tsx:51](frontend/src/features/me/pages/StudentHomePage.tsx#L51)), and directly
under it the per-project list says otherwise:

```
DUE BY   Sep 20, 2026, 23:59 GMT+7
Submitted                                    [Open this week]

Projects this week
Calibration under drift      SUBMITTED
Korean river                 REQUIRED
```

The per-project column is the first pass's #1 and it is fixed and correct. But the figure a student
reads first now says the week is done while a required project has no entry — REP-08's definition
of an unfulfilled obligation. `workflow_state` is a property of the report ("something has been
submitted"), not of the package ("everything owed is in"), and this screen presents it as the
latter. A student who submitted on Monday and joined a project on Wednesday sees **Submitted** and
has no reason to open the week again.

The editor repeats it: the header says *"Submitted Sep 17, 2026, 10:54 GMT+7 — sending again
replaces it"* with no hint that one of its three tabs has never been sent, and the tabs themselves
are styled identically whether or not the entry exists.

**Suggested fix.** Derive the headline state from the obligations that are already on the screen:
submitted only when every required obligation has `submitted: true`, otherwise something like
*Submitted — 1 project still owed*. The same count could tone the tabs in the editor.

---

## 10 — "What does this show?" is recorded and then never shown

**Severity: Low.** The claim box is labelled **WHAT DOES THIS SHOW?** with the note *"Your
description of what this supports. Recorded as your claim, not as a finding."* It is recorded:

```
{"filename":"qa2-probe.md","supported_claim":"QA2: the RMSE table", …}
```

and it appears on no screen afterwards. The evidence list shows filename, extraction badge,
Download and Remove. A student cannot check what they claimed, correct a claim, or notice they
attached a file with an empty one — which is what the PDF already on this week's Korean river entry
has (`"supported_claim": ""`).

Given the note's care about the difference between a claim and a finding, the claim being
write-only is an odd place for the feature to stop.

---

## 11 — The claim box is shared by the panel and applies only to the next attachment

**Severity: Low**, and it is what makes #10 hard to notice. `claim` is one piece of state for the
whole panel, cleared after each successful attach. So typing a claim and then attaching two files
gives the first one the claim and the second one nothing, with no indication either way; and
typing a claim and then pressing **Add link** attaches the claim to the link.

**Suggested fix.** Either move the claim into a per-row edit (which also answers #10), or label it
as applying to the next attachment.

---

## 12 — The failed-submission message does not name the projects

**Severity: Low**, but it is the message standing between a student and #1. The API returns the
answer and the screen discards it:

```
422 {"detail":"the package is missing an entry for every required project",
     "missing_project_ids":["01a0ad80-2427-…","01a0b212-0dd1-…"]}
```

The editor renders `problem.detail` alone. The sentence is also ambiguous in the direction that
matters: *"missing an entry for every required project"* reads as *all of them are missing*, when
it means *one is required for each*. A student whose three tabs are full is told, in effect, that
none of them count.

**Suggested fix.** Resolve `missing_project_ids` to titles through the `useProjects` data the page
already holds, and reword to *"no entry for: X, Y"*. Had it done so, #1 would have been obvious on
the screen instead of in the network tab.

---

## 13 — `/me` flashes "Not started / Start this week" on a submitted week

**Severity: Low.** Sampling the state chip and the call-to-action every 50 ms through a fresh load
of `/me` catches two distinct renders:

```
["Not started | Start this week",
 "Submitted   | Open this week"]
```

The chip defaults to `not_started` before `useReport` resolves
([StudentHomePage.tsx:51](frontend/src/features/me/pages/StudentHomePage.tsx#L51)) and the button
label switches on `report.data` being present, so a submitted week paints briefly as an untouched
one. The deadline above it is already correct at that point, which makes the panel look settled.

**Suggested fix.** Render the chip and the button label as a placeholder while `report.isPending`,
rather than as the negative answer.

---

## 14 — The editor's tabs are ARIA tabs with nothing on the other end

**Severity: Low (accessibility).** The tab strip declares itself:

```js
{ tabs: [ {txt: "Calibration under drift", controls: null, id: "", tabindex: 0},
          {txt: "Korean river",            controls: null, id: "", tabindex: 0},
          {txt: "QA3 seasonality probe",   controls: null, id: "", tabindex: 0} ],
  panels: 0 }
```

`role="tablist"` with three `role="tab"` children, no `role="tabpanel"` anywhere, no
`aria-controls`, and every tab in the tab order with no arrow-key handling. A screen-reader user is
told they are on "tab 1 of 3" and given no panel to move to; a keyboard user tabs through all three
instead of arrowing between them, which is what the pattern promises. `aria-selected` is set
correctly, which is the part that makes the rest look deliberate.

**Suggested fix.** Either complete the pattern — wrap the form in a `role="tabpanel"` with
`aria-labelledby`, add `aria-controls`, roving `tabindex` and Left/Right handling — or drop to
plain buttons with `aria-pressed`, which is honest about what they are.

---

## 15 — A project the student has left fetches four things it does not render

**Severity: Low.** `/projects/{a project I left}` renders the title, the description, and:

> You left this project on Sep 18, 2026. The record stays readable because your reports and
> assessments refer to it; its milestones, decisions and members are no longer shown.

That copy is good — it is the first pass's #8 and #11 answered together. But the page still issues:

```
200 GET /api/v1/projects/{id}/members?include_past=true
200 GET /api/v1/projects/{id}/milestones
200 GET /api/v1/projects/{id}/decisions
200 GET /api/v1/projects/{id}/progress
```

and shows none of it. Four requests per view for data the page has decided not to display — and
`?include_past=true` on a member list that is deliberately withheld.

Worth noting alongside it: the withheld member list is the one thing here that disagrees with the
documentation. UI-03 is *"members of a project see who else works on it, including past members"*,
and use_cases §8.4 lists the member list *"including past members"* among what a membership
reveals. A past member seeing nothing may well be the right call, but it is a change of policy and
the two documents still say the old one.

**Suggested fix.** Gate the four queries on `viewer_left_on` being null — `enabled:` on each hook —
and settle the UI-03 wording either way.

---

## 16 — Correction: the redirect does explain itself, and then cannot stop

**This entry was reported in error and is corrected here.** The first pass's #14 said a student
following a link into a professor-only screen arrives at `/me` with nothing said, and this pass
repeated it. It is fixed, and was fixed before this pass ran: I checked where the browser landed
and never read the page it landed on.

`RequireAuth` and `HomeRedirect` now carry `turnedAwayFrom` in the redirect's history state and
`AppShell` renders it. `/overview`, `/students/{id}` and an unrecognised path each produce, above
the week:

> /overview is not a page your account can open, so this is your own home instead.

**What is wrong is how long it lasts.** The message lives in the history entry rather than in the
click, and nothing consumes it, so pressing reload on `/me` shows it again — and again on every
reload after that:

```
goto /overview        → /me   "/overview is not a page your account can open…"
reload                → /me   "/overview is not a page your account can open…"
reload                → /me   "/overview is not a page your account can open…"
```

In-app navigation clears it correctly (to `/projects` and back to `/me`: gone), so this only bites
a reader who refreshes the page they were sent to — which is a reasonable thing to do when a click
has just taken you somewhere you did not ask for.

**Suggested fix.** Consume the state when the notice is shown: snapshot it, then
`navigate(pathname, { replace: true, state: null })`. The message belongs to the click.

---

## 17 — The autosave clock carries no timezone beside a deadline that does

**Severity: Low.** The footer of the editor now reads `Saved 11:44:34`, in the workspace zone —
the first pass's #9 is fixed, and the two clocks on the screen finally agree. What is left is that
one of them is labelled and the other is not: `Due by Sep 20, 2026, 23:59 GMT+7` above,
`Saved 11:44:34` below. A student abroad has no way to tell which zone the save is in, and the
zone is the thing that was wrong before.

**Suggested fix.** Either append the zone to the saved stamp, or drop `GMT+7` from the deadline and
state the workspace zone once on the screen.

---

## 18 — A report whose current version is not its latest can never be submitted again

**Severity: High.** Found on the deployment while verifying the fix for #1, and only reachable once
that fix was in: #1 refused every submission before this could be reached.

With the departed-project check corrected, the same submission fails differently:

```
POST /api/v1/periods/01a0ad80-2559-…/report/submit
409 {"title":"Conflict","detail":"that record already exists"}

api log: unique violation surfaced as a conflict: duplicate key value violates
         unique constraint "uq_report_versions_report_id_version_no"
```

The report's versions, at the time:

```
 version_no | is_current
          1 | t
          2 | f
          3 | f
```

`current_version_id` pointed at version 1 while versions 2 and 3 existed — the two the first pass
created. `_next_version_no` derives the next number from the **current** version rather than from
the highest one the report has ever had, so it computed `1 + 1 = 2`, which the table already held.

The two are normally the same, which is why this held up in every test: only a report whose current
version has been moved backwards — a restore, a rollback, a correction applied by hand — reaches
it. Once it does, the week is unsubmittable for good, and the only thing the student sees is *"that
record already exists"*, which describes the row rather than anything they did.

REP-05 also settles which of the two readings is right: *"a resubmission adds one and never
replaces history"*, so the sequence belongs to the history, not to whichever version is being read
today.

**Fix applied.** `_next_version_no` now returns `max(version_no) + 1` over the report's versions,
through a new `repository.highest_version_no`. Regression test:
`test_the_version_number_counts_from_the_history_not_from_the_current_version`, which rolls a
report back to its first version and submits again.

---

## Verified: the 14 defects from the first pass

Each re-tested through the screen that had it.

| First pass | Now |
| --- | --- |
| 1 — every project reads REQUIRED after submission | **Fixed.** `/me` has a **Projects this week** list reading `SUBMITTED` (green) / `REQUIRED` (amber) per project, from a new `submitted` flag on the obligation payload computed by the same code as the professor's outstanding list. See #9 for the headline state above it. |
| 2 — reopening a submitted week shows an empty form | **Fixed, both halves.** The editor fetches `GET /report-versions/{current}` and seeds from it when no draft exists — the submitted entry for Calibration under drift came back word for word over an empty `draft_content`. And `_check_package_says_something` refuses an all-empty package server-side. (That guard is unreachable on this account: the completeness check of #1 runs first.) |
| 3 — attachments stuck on READING… | **Fixed.** Extraction now runs when the week is submitted, and the badge says so: **READ WHEN YOU SUBMIT** rather than a spinner over a job nothing was running. The PDF already on this week's Korean river entry reads **TEXT EXTRACTED**. |
| 4 — no web font loads, blocked by CSP | **Fixed.** `style-src` now allows `https://fonts.googleapis.com` and `font-src` `https://fonts.gstatic.com`; `document.fonts` reports Newsreader, IBM Plex Sans and IBM Plex Mono all `loaded`, and no CSP violation is logged on any page. |
| 5 — every time rendered in Asia/Ho_Chi_Minh | **Fixed.** `useTimezone()` reads the reporting calendar — `GET /calendar`, which answers for a student — and is threaded through every `formatInstant` call on the student's screens. GMT+7 is now correct rather than hardcoded: this workspace's calendar is `"timezone": "Asia/Ho_Chi_Minh"`. |
| 6 — assessment headed by a UUID fragment | **Fixed.** "Week on project **Retrieval baselines**". See #6 for the half that is still missing: which week. |
| 7 — "a report … is owed from next week" | **Fixed, and verified against behaviour.** The note now reads *"a report for it is owed for this week, from now"*, and creating `QA3 seasonality probe` through the form took the current week's obligations from two to three immediately, with a third tab in the editor. |
| 8 — leaving a project is unconfirmed and silent | **Fixed.** The button carries a note explaining what ending the membership does; clicking it asks *"Leave QA3 seasonality probe? You cannot rejoin unless your professor opens the project again."*; dismissing it leaves the membership intact; and the project's own page afterwards explains the state in a sentence. |
| 9 — autosave clock in a different zone from the deadline | **Fixed** via `formatTimeOfDay`. See #17 for the label. |
| 10 — trajectory labels the rubric by UUID fragment | **Fixed.** The card reads `rubric A`. |
| 11 — a past member disappears from the member list | **Fixed.** `?include_past=true` is passed, and `/projects` stamps a project the student has left **LEFT SEP 18, 2026** beside its status. |
| 12 — empty-state note under a non-empty list | **Fixed.** The note is inside the empty branch; `/me/profile` with one released assessment shows the row and no note. |
| 13 — unknown period reads "no reporting period configured" | **Fixed in the copy, replaced by #4** — the screen no longer says the wrong thing because it no longer says anything. |
| 14 — professor-only link drops the student on `/me` | **Fixed**, and this report said otherwise before checking: the redirect now carries the path it turned the reader away from and the shell prints it. See #16 for the correction and for what is still wrong with it. |

---

## What worked

- **Sign in and out.** A wrong password says *"invalid email or password"* with the form intact;
  sign-out returns to `/login` and a subsequent `/me` bounces straight back to it.
- **Autosave.** Debounced, honest about its state (`Not saved yet` → `Saved 11:44:34`), recovers
  across a reload, and does not create a draft merely because the editor was opened.
- **Attachments.** Browser-side SHA-256, a direct PUT to object storage, checksum-verified confirm,
  a signed download that delivers the file (`TRIAD_Rx_ECIR2027.pdf`, 2.4 MB), and a removal
  that confirms by name — *"Remove qa2-probe.md? The file and its extracted text are deleted, and
  it stops being searchable."*
- **The correction request.** Posts, clears the box, and appears in the thread as *"Your correction
  request"* with a timestamp.
- **Creating and editing a project.** `POST` and `PATCH` both work from the student's screen; the
  repo-URL field rejects `nonsense` in the browser with no request sent; a student gets no edit form
  on a project they did not create.
- **Error states on unknown ids.** `/me/assessments/{bad}` and `/projects/{bad}` both say something
  useful. `/report/{bad}` is #4.
- **Access control.** Every professor-only screen refused. `GET /assessments/{id}/evidence` was
  never requested.
- **Mobile.** At 390 × 844 all four student screens fit with `scrollWidth == innerWidth` and no
  element extending past the viewport; the editor's tab strip wraps to two rows and the evidence
  panel stacks.
- **Accessibility basics.** `lang="en"`, one `h1` per screen, `header`/`nav`/`main` landmarks,
  every form control reachable by its label, the icon-only theme toggle labelled *"Switch to
  light"*, visible focus rings. The exception is #14.

The dark default is deliberate and documented in
[frontend/src/lib/theme.ts](frontend/src/lib/theme.ts) — *"the default is a decision about this
product rather than a reading of the operating system"* — so a fresh browser with
`prefers-color-scheme: light` opening dark is not recorded as a defect. The toggle works and the
choice persists.

## Not covered

- **Joining an open project.** `GET /projects/joinable` returns `[]` — no project in this workspace
  has `open_to_join` set — and the panel is deliberately hidden when empty, so neither the panel nor
  `POST /projects/{id}/join` could be exercised from the UI.
- **Past weeks.** The week of 14–20 Sep is the first period in the calendar, so the `PastWeeks`
  list on `/me` has nothing to render and the plan carry-over of #3 has no previous week to read.
  Both want re-testing after 21 September.
- **Accepting an invitation and resetting a password.** Both need a token from an email.
- The ⚙️ rows of use_cases §3 (task progress, developer identities, contributions, evidence search)
  have no screen by design.

## Verified on the deployment, after the fixes

Rebuilt and released on 18 September 2026 at 10:21Z (`api`, `worker` and `caddy` — the SPA is built
into the caddy image). Preflight clean, pre-deploy backup taken, `alembic upgrade head` a no-op:
none of these fixes changes the schema. Then the same Playwright driver, over the same screens:

| # | What the live site does now |
| --- | --- |
| 1 | `Submit report` → **Submitted as version 5**, `201`. The two departed projects no longer block it. |
| 2 | Version 5 carries **four** entries for a package covering three obligations: the fourth is `Retrieval baselines`, the project An Nguyen left, with its original text and plan intact. |
| 3 | A plan typed in the editor is stored as `{"items":[{"planned_outcome":"…"}]}` — the shape `_carried_plan` reads. |
| 4 | An unknown period id reaches the message instead of loading for ever. |
| 5 | Both confidence reasons are on the page as text, under the badge. |
| 6 | The heading reads **Sep 14, 2026 – Sep 20, 2026 on Retrieval baselines**. |
| 7 | `not a url` → *"That is not a web address. A link has to start with http:// or https://."*, and no `POST /artifacts/links` is made. |
| 8 | One Download button for one file row; a link row offers none. |
| 9 | `/me` reads **Submitted — 2 projects still owed**, and each tab carries `SUBMITTED` or `REQUIRED`. |
| 10 | A file attached with a claim shows it on its row. |
| 12 | (Covered by #1 no longer failing; the named-projects path is unit-tested.) |
| 14 | One `tabpanel`, and the first tab's `aria-controls` names it. |
| 15 | Opening a project the student has left issues **no** members / milestones / decisions / progress requests. |
| 16 | The turned-away notice appears once and is gone after a reload. |
| 17 | `Saved 17:24:56 GMT+7`. |
| 18 | Versions run 1–5 with 5 current; no unique-constraint conflict. |

No uncaught page errors on any screen during the run.

## Test residue on the deployment

Created while testing, and not removable through the student UI:

- **Project `QA3 seasonality probe`** — active, An Nguyen the only member, repo
  `https://github.com/example/qa3`. Left in place deliberately: leaving it would have added a third
  ghost obligation of the kind #1 is about.
- **A draft** on the week of 14–20 Sep carrying entries for Calibration under drift (recovered from
  version 1, unchanged) and Korean river (`QA-2 work performed…`, 6 hours).
- **Report versions 4 and 5**, written while verifying the fixes. Version 5 is current and holds
  four entries: the three projects owed this week, plus the carried-forward `Retrieval baselines`
  entry described under #2. Versions 1–3 are intact behind it — 2 and 3 are the first pass's, and
  the reason #18 was reachable at all was that `current_version_id` had been pointed back at
  version 1 while they existed. The first pass's other residue is still present: the project
  `QA probe project (edited)`, left on 18 September, and the correction request on assessment
  `01a0ad80-2ce4-…`.
- The two probe attachments (`qa2-probe.md`, and the `not a url` link) were both deleted through
  the UI at the end of the run. `TRIAD_Rx_ECIR2027.pdf` on Korean river, which predates this pass,
  was not touched.
