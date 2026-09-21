# QA report — the domain model as implemented, professor and student

**Tested** 21 September 2026, 00:10–01:35 UTC, against the current tree at `8169026`
(branch `docs/domain-model`; the code is identical to `da55dc4` on `main` — the only commit on
top is documentation).

**Where** a throwaway stack built from this tree: compose project `research-management-mock`
(api, worker, postgres, minio, mailpit), migrations at `0025`, deterministic AI gateway, SPA on
the Vite dev server. **Not** the live deployment at `research.ecomind.dev`, which serves a
different build — it still answers `POST /api/v1/artifacts/links`, the route commit `da55dc4`
removed with link evidence. Testing there would have exercised yesterday's code and written test
data into a running deployment.

**As two accounts, and only two**, both created through the product's own doors: `qa.prof.j@example.edu`
(professor, created by `app.cli identity bootstrap`, invitation accepted in the browser) and
`qa.student.j@example.edu` (student, invited by the professor, invitation link read out of
mailpit, accepted in the browser).

**With** Playwright/Chromium driving the real UI for everything that has a screen — sign in, the
workspaces screen, the project list and its create form, the joinable list, the weekly editor —
and the HTTP API for the rules that have no screen: composite foreign keys, obligation derivation,
version immutability, and the role guards. Every API call carries the browser's own session cookie,
so nothing bypasses authorization.

**Scope** — the brief was the *correctness of the domain model*: what the five entities are, what
belongs to what, which relations are plural, and whether the implementation enforces what
[docs/domain_model.md](../docs/domain_model.md), the requirements v0.6 and ADRs 0011–0017 say it
does. 36 checks across workspace, professor, student, project, reporting and assessment.

**Result: 35 of 36 checks pass. One fails, and it is a real disagreement between the code and its
own stated rule.** Three further observations are recorded that are not test failures.

---

## Summary

| # | What it is | Severity |
| --- | --- | --- |
| 1 | **Joining a project on the first day of a reporting week owes that week**, though PROJ-02, ADR 0017, the joinable screen and the function's own docstring all say the next one | **Medium** |
| 2 | Immediately after leaving a workspace, `GET /auth/me` can still name the workspace just left as the one being worked in. The stored state was correct every time it was checked; intermittent, about 2 occurrences in 25 attempts | Low |
| 3 | The evidence box still offers links — "applied to the next file **or link** you attach" — after REP-04 made evidence a file | Low |
| 4 | *Observation:* the professor's assistant answers a student too. It is correctly scoped to their own records, so nothing leaks, but `use_cases.md` §3 says the student has no assistant | Observation |
| 5 | *Observation:* `POST /auth/accept-invitation` is capped at 10 per hour per IP, hardcoded and in-memory. A cohort accepting from one office address would hit it | Observation |

---

## 1 — Joining on the first day of the week owes that week

**Severity: Medium.** A student is told one thing by the screen and held to another by the schedule.

The rule appears in four places, and all four say the same thing:

- **PROJ-02:** "A student joining an existing project owes from the following week, so that joining
  on a Saturday is not a report due that Sunday for a week spent off the project."
- **[ADR 0017](../docs/adr/0017-students-own-their-projects.md) §4:** "A student joining part-way
  through a week owes from the next week."
- **The joinable list, in the student's own screen:** "Joining puts a weekly report for the project
  on your plate **from next week**."
- **The docstring on `memberships_active_in_range`** ([backend/app/projects/repository.py:223](../backend/app/projects/repository.py#L223)):
  "A membership acquired by joining an existing project owes only weeks that **began after** the
  student joined."

The predicate is [repository.py:242](../backend/app/projects/repository.py#L242):

```python
or_(
    ProjectMembership.origin != MembershipOrigin.SELF_JOINED,
    ProjectMembership.joined_on <= local_start,
),
```

`joined_on <= local_start` admits a week that begins **on** the day of the join. "Began after the
student joined" is `local_start > joined_on`. The two differ by exactly one day a week — the first
day — and that is the day this was tested on.

**What happened.** The student joined the professor's open project on Monday 21 September, the
first day of the period 21–27 September. An obligation for that same week was created and is
`required`:

```
 membership                           | origin      | joined_on  | local_start | local_end  | has_obligation | state
 01a0c163-3f31-7384-97b5-969bb3cff9d6 | self_joined | 2026-09-21 | 2026-09-21  | 2026-09-27 | t              | required
```

**Why it matters.** The obligation is what the missed-deadline job reads (REP-08). A student who
joins on a Monday, believing the screen, and does not file by Sunday 23:59 is recorded missing and
emailed about it — the precise outcome ADR 0017 §4 says the rule exists to prevent, arriving by a
different door.

**Which half is wrong is a product decision, not a test result.** Owing the week you joined on its
first day is arguably the more sensible behaviour: the student was on the project for all seven
days. If that is the intent, the requirement, the ADR, the docstring and the student-facing
sentence should say "from the next week *that begins after* you join", and the screen should stop
promising next week. If the stated rule is the intent, the predicate wants `<` rather than `<=`.
Either way the four statements and the code should agree.

**Note on visibility.** This is invisible six days a week. Run the suite on a Tuesday and the join
lands mid-week, `joined_on > local_start` holds, and the check passes.

---

## 2 — The workspace being worked in can read stale just after leaving

**Severity: Low**, because the stored state was right every time and the next read corrects itself.

After `POST /workspaces/{id}/leave` returns 200, `GET /auth/me` occasionally reports the workspace
just left as `workspace_id` — the field that decides where the next write lands. Observed twice:
once in the workspaces spec, once in a dedicated probe that repeated create → leave → read six
times through the same browser client (1 of 6). A second probe of twelve iterations did not
reproduce it.

In every case the database was correct: the `workspace_members` row was gone and `users.workspace_id`
had moved to the remaining workspace. Six sequential command-line repetitions were also correct,
so this is a read-path timing effect rather than a failed write.

```
#0 leave=200 anchor_after=moved
#1 leave=200 anchor_after=moved
#2 leave=200 anchor_after=STILL-ON-LEFT-WORKSPACE
#3 leave=200 anchor_after=moved
```

Worth a look because `users.workspace_id` is not cosmetic: it is where writes land, and for the
duration of the stale read it names a workspace the account no longer belongs to — one whose
records it can no longer read, since reads span memberships. A write issued in that window is the
case to reason about. `expire_on_commit=False` on the session factory
([backend/app/core/db.py:53](../backend/app/core/db.py#L53)) is the first place I would look, but
I did not confirm a mechanism and am not asserting one.

---

## 3 — The evidence box still offers links

**Severity: Low.** REP-04 made evidence a file, and `POST /api/v1/artifacts/links` is gone from
this build. The help text under the evidence claim box was not:

> Your description of what this supports, applied to the next file **or link** you attach.
> Recorded as your claim, not as a finding.

`frontend/src/locales/en/common.json:112`, key `report.attachments.claimNote`. The editor has no
link input — checked: the only controls are the three textareas, the claim box and a file input —
so the sentence describes something the student cannot do.

---

## 4 — Observation: the assistant answers a student

`use_cases.md` §3 says, in bold, "**The student has no assistant.** That is deliberate and recorded
as next-release work". `POST /api/v1/assistant/ask` answers one:

```
scope.role = "student"
answer      = "Unfulfilled reporting obligations for the week of 2026-09-21: 1"
facts[0].rows = [ { student_name: "Student QA Tester", project_title: "QA — …" } ]
```

**Nothing leaked.** Every fact row returned belongs to the caller, which is what the permission
model promises and what the check now pins. The observation is that a surface the use cases
describe as absent is reachable, unscreened, and spends the workspace's model budget on a student's
question. Requirements §2 does allow a student assistant later ("Optional later feature, restricted
to permitted material"), so this may be intent that arrived before its screen — but it should be a
decision rather than a discovery.

Related and benign: `GET /api/v1/users` answers a student with HTTP 200 and exactly one row, their
own. That is the policy working, not a hole; it is listed here only because a reader auditing role
guards will see the 200 and wonder.

---

## 5 — Observation: invitation acceptance is capped at 10 per hour per IP

Found by tripping it: after ten accepted invitations the eleventh returned 429 and the account
could not be activated at all. The limit is hardcoded at
[backend/app/api/middleware.py:40](../backend/app/api/middleware.py#L40) — `"/api/v1/auth/accept-invitation": (3600, 10)`
— and unlike the login limit it has no setting. It is in-memory, so restarting the api clears it.

A lab enrolling a cohort of fifteen in one session, from one office or campus NAT address, hits
this on the eleventh student, and the message they see is "Too many attempts. Wait and try again."
Whether that is the right trade against invitation-token brute force is a product call; it is
recorded because it is invisible until the day it happens and there is no knob to turn.

---

## What held

Every row below was checked end to end in one pass in a fresh workspace. Screen-driven where a
screen exists; otherwise the API, with the browser's own session.

### Workspace — the tenant boundary

| Check | Result |
| --- | --- |
| A student has no workspace administration: listing and creating are refused, the screen is guarded | pass |
| Leaving your only workspace is refused — the anchor has nowhere to go (AUTH-05) | pass |
| A professor creates a second workspace, is taken there, and keeps the first (ADR 0015) | pass |
| Reads span both workspaces; the roll says "Across 2 workspaces" while the student stays anchored where enrolled (ADR 0016) | pass |
| A write lands in the workspace being worked in — a project created while working in the second belongs to the second | pass |
| A workspace somebody belongs to cannot be archived | pass |
| Leaving empties a workspace, and an empty one archives and leaves the list | pass |

### Professor and student

| Check | Result |
| --- | --- |
| The bootstrap invitation activates the professor and lands on the overview | pass |
| The roll holds one professor and says nobody else is enrolled | pass |
| The invitation names the workspace, and the invited student is on the roll *before* accepting (ADR 0015) | pass |
| The student accepts by the emailed link — read from the delivered mail — and lands on their own week | pass |
| A student cannot invite, suspend, move an account, read the professor's record, read the overview, configure the calendar, derive obligations, change a project's standing, or list workspaces (9 attempts, 9 refusals) | pass |
| A student reads their own week and has no route to anyone else's | pass |

### Project

| Check | Result |
| --- | --- |
| A project a professor starts is `proposed`, and closed to joining (PROJ-01) | pass |
| A project a student starts is `active`, with the creator enrolled in the same transaction, `origin = created` | pass |
| The creator may change title and research questions; `status`, `open_to_join` and `ai_restricted` are refused with 403 (AUTH-07) | pass |
| A student may not put anybody on a project, their own included | pass |
| A closed project is unreadable to a non-member, absent from the joinable list, and cannot be joined | pass |
| Opened to joining, it becomes discoverable but stays unreadable: the joinable row carries id, title, stage, status and a member count, and no research questions, contributions, venue or resources (ADR 0017) | pass |
| Joining opens the full record, and the membership records `origin = self_joined` | pass |
| A proposed project owes nothing even with a student assigned to it | pass |

### Reporting

| Check | Result |
| --- | --- |
| The deadline is derived, not stored: week 21–27 Sep, meeting Mon 28 Sep, deadline `2026-09-27T16:59:00Z` — 23:59 the day before the meeting, in `Asia/Ho_Chi_Minh` (REP-01) | pass |
| A project started this week owes this week | pass |
| The week asks three questions — Progress, Challenges, Next steps — and the five-field names are gone from the editor | pass |
| Hours are not asked for anywhere on the editor | pass |
| Evidence is a file: a file input and a claim box, no link input; the link route is gone (405) | pass |
| Submission writes version 1; a resubmission writes version 2 and keeps version 1 readable | pass |
| `first_submitted_at` is frozen across the resubmission (REP-05, AC-13) | pass |
| A package that misses an owed project is refused (REP-02) | pass |
| Once a week has been written, moving the account to another workspace is refused by the schema (AUTH-06) | pass |
| Leaving a project keeps the week already filed, entry included (ADR 0017) | pass |

### Assessment

| Check | Result |
| --- | --- |
| A submitted week produces a draft assessment without anyone asking for it | pass |
| A resubmission supersedes the assessment it replaces, and the superseded row is labelled, not dropped (ASSESS-09) | pass |
| **Only the changed entry is re-assessed** — the entry whose text was unchanged kept its v1 and gained no v2 (AC-17) | pass |
| A draft is invisible to the student, by list and by id, and the student cannot approve it | pass |
| Approving a superseded version is refused with 409 and the reason "a newer assessment has replaced this one; approve that instead" | pass |
| Approval publishes, and only then does the student read it (ASSESS-08) | pass |
| The published figure carries coverage, confidence and the rubric version; the index is present when every dimension is rated and withheld when any is `unknown` (ASSESS-04, ASSESS-06) | pass |

---

## What this pass could not test

Stated plainly, because a report that does not say what it skipped invites the reader to assume it
was covered.

- **Student-to-student confidentiality (AC-02) was not tested.** The brief was two accounts, and
  one student cannot demonstrate that they are kept out of another's report, assessment or
  citations. The checks here prove a student is kept out of the *professor's* material and cannot
  reach professor-only routes. AC-02 needs a third account, and it is the single most valuable
  addition to this suite.
- **Rubric quality was not tested and cannot be**, on this stack: the deterministic gateway rates
  by stated heuristics. What was tested is the contract around the rating — draft, approval,
  supersession, coverage, provenance — not whether a rating is right.
- **No repository evidence.** No GitHub App is configured in mock mode, so REPO-01…08, joint
  attribution and AC-06 are untouched.
- **One week, one timezone, one calendar.** The deadline rule was checked for
  `Asia/Ho_Chi_Minh` with a Monday meeting. Calendar versioning (a meeting day changed while
  periods are already open) was not exercised.
- **The professor's own history.** AUTH-06 was tested with a student; a professor who has written
  supervision material was not moved.
- **Break-glass, backups, and the missed-deadline email itself** were out of scope. The obligation
  the email reads was checked; the send was not.

## Method, and how to run it again

The suite is in [frontend/e2e-domain-model/](../frontend/e2e-domain-model/) — six spec files, a
helpers module and its own Playwright config. It lives under `frontend/` rather than beside this
report because the specs import `@playwright/test`, which only resolves from there. It expects the
mock stack on `:8021` with the SPA on `:8020`, and a professor created by `identity bootstrap`
whose invitation token is passed in:

```bash
scripts/run_mock.sh                       # mock stack + SPA
docker exec research-management-mock-api-1 uv run python -m app.cli identity bootstrap \
    --name "QA Lab" --email qa.prof@example.edu --display-name "Prof QA"

cd frontend
PROF_TOKEN=<the token that command prints> \
    npx playwright test --config=e2e-domain-model/playwright.qa.config.ts
```

Run exactly that way against this build it gives **35 passed, 1 failed**, the failure being
finding 1. The two accounts are named in `e2e-domain-model/qa-helpers.ts`; change the suffix on
both addresses and the workspace name before each fresh run, since the suite builds a world rather
than reusing one.

The specs run serially and share state through a `state.json` they write as they go, because the
order is the point: a week cannot be submitted before a project exists, and an assessment cannot be
approved before a week is submitted. They are written against a **fresh workspace** — the accounts
and workspace names carry a suffix — since several checks are only true of a workspace nobody has
touched ("leaving your only workspace", "the roll holds one professor").

Two harness faults were found and fixed while writing them, both of which had produced false
passes: signing in as a second person inside one test silently kept the first person's session
(`/login` redirects an authenticated visitor, and "Sign out is visible" was already true), and a
draft assessment read before the pipeline settled was one about to be superseded. The sign-in
helper now clears cookies and verifies the identity it got; the assessment check waits for the set
to stop changing. Anyone extending this suite should keep both.
