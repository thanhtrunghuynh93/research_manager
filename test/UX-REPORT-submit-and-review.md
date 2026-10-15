# UX test — student submits, professor reviews

Tested 15 Oct 2026 on a throwaway staging stack built from the working tree (demo data, own database;
production untouched), driven with Playwright/Chromium at 1366px and 390px. Roles: An Nguyen
(student) and the demo professor. The flow works end to end; these are friction points.

## Student: submit a report
| # | Finding | Fix |
|---|---|---|
| S1 | Submit with an empty entry: the error is lowercase raw API text at the very bottom of a long page; no scroll, no focus, nothing marks the offending tab. | Scroll to / focus the first incomplete entry, mark its tab, sentence-case the message. |
| S2 | Tabs never show whether an entry is filled, so with 2+ projects the student cannot see what is left. | Add a to-do / done state to each tab, updated as they type. |
| S3 | After submit, "Submitted as version 1." appears at the bottom, the footer still says "Not saved yet" and the button still says "Submit report". | Banner at the top; footer "Submitted"; button becomes "Resubmit". |
| S4 | On the home page, a project whose revision was requested still reads SUBMITTED, the button says "Open this week", and the professor's reason is only visible inside the editor. | Show "Revision requested" per project, quote the reason on the home card, button "Revise". |
| S5 | The evidence-claim input's placeholder is the same colour as typed text, so it reads like a pre-filled value. | Dim the placeholder. |
| S6 | The Due/Submitted block in the editor header is right-aligned to a narrower column than the form below it. | Align it with the form column. |
| S7 | A late student sees only "Not submitted · write it" in small amber text for last week. | Say "Overdue" and make the row a clear button. |

## Professor: check a report
| # | Finding | Fix |
|---|---|---|
| P1 | The report page has no link to the AI assessment draft, and the review page has no link back to the report. | Cross-link both ways. |
| P2 | Overview "Assessments awaiting review" lists identical rows ("Draft for An Nguyen · Retrieval baselines" x3) with no week. | Show the week, group by student. |
| P3 | Overview "2 of 7 in" counts obligations, not students; "Reports still owed" repeats the grid above it. | Label it ("2 of 7 reports"); drop or merge the duplicate list. |
| P4 | "Request a revision" is a link-styled button, disabled until text is typed, with no visible disabled state; the text box is always open, so the page is mostly empty form. | Collapse the box until clicked; show the disabled state. |
| P5 | "Mark reviewed" is at the very bottom, and a project with no evidence shows no Evidence section at all, so missing evidence is invisible. | Sticky action bar; "No evidence attached" line. |
| P6 | No previous/next report; the professor goes back to the list for every student. | Add "Next report" / "Next needing review". |
| P7 | Reports list defaults to all reports; "Needs review" is an unchecked box. | Default the professor to needs-review. |
| P8 | The review page for 21 Sep says "no report was submitted for this week" while Reports lists that week as submitted (may be demo-seed ordering). | Verify against real data. |

## Fine as is
Mobile at 390px has no horizontal scroll. The editor autosaves and restores the draft; the revision
reason shows in the editor with a flagged tab; the professor's revision request reaches the student;
file upload, download and removal work.
