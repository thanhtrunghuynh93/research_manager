/** REP-02/REP-03/REP-04: one weekly package, a tab per project entry, autosave, one submit. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ReportEditorPage } from "@/features/report/pages/ReportEditorPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PERIOD = {
  id: "p1",
  local_start: "2026-09-14",
  local_end: "2026-09-20",
  start_utc: "2026-09-13T17:00:00Z",
  end_utc: "2026-09-20T17:00:00Z",
  meeting_date: "2026-09-21",
  deadline_utc: "2026-09-20T16:59:00Z",
  reminder_due_utc: "2026-09-20T17:00:00Z",
};

const PROJECTS = [
  { id: "pr1", title: "Baseline evaluation", stage: "implementation", status: "active" },
  { id: "pr2", title: "Theory of the estimator", stage: "theory", status: "active" },
];

const OBLIGATIONS = [
  { id: "o1", period_id: "p1", project_id: "pr1", student_id: "s1", state: "required" },
  { id: "o2", period_id: "p1", project_id: "pr2", student_id: "s1", state: "required" },
];

function renderPage(extra: Parameters<typeof server.use>[number][] = []) {
  server.use(
    // First: within one `use` call msw matches in order, so a test's own handler has to come
    // before the defaults it is replacing.
    ...extra,
    http.get("/api/v1/periods", () => HttpResponse.json([PERIOD])),
    http.get("/api/v1/periods/p1/obligations", () => HttpResponse.json(OBLIGATIONS)),
    http.get("/api/v1/projects", () => HttpResponse.json({ items: PROJECTS })),
    // The editor reads its attachments back from the server rather than remembering them, so a
    // reloaded page shows the files that are actually in the bucket.
    http.get("/api/v1/artifacts", () => HttpResponse.json([])),
    http.get("/api/v1/periods/p1/report", () =>
      HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "draft",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: null,
        current_version_id: null,
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/report/p1"]}>
        <Routes>
          <Route path="/report/:periodId" element={<ReportEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("shows one tab per required project", async () => {
  renderPage();

  expect(await screen.findByRole("tab", { name: /Baseline evaluation/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /Theory of the estimator/ })).toBeInTheDocument();
});

test("autosaves the draft after typing stops", async () => {
  const saved: unknown[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", async ({ request }) => {
      saved.push(await request.json());
      return HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "draft",
        draft_content: {},
        draft_saved_at: "2026-09-18T04:00:00Z",
        first_submitted_at: null,
        current_version_id: null,
      });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Implemented the data loader");

  await waitFor(() => expect(saved.length).toBeGreaterThan(0), { timeout: 4000 });
  expect(await screen.findByTestId("autosave-indicator")).toHaveTextContent(/saved/i);
});

test("submits one package for every required project with an idempotency key", async () => {
  const submissions: { body: unknown; key: string | null }[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", async ({ request }) => {
      submissions.push({
        body: await request.json(),
        key: request.headers.get("Idempotency-Key"),
      });
      return HttpResponse.json({
        id: "v1",
        report_id: "r1",
        version_no: 1,
        author_id: "s1",
        submitted_at: "2026-09-20T10:00:00Z",
        timing_status: "on_time",
        entries: [],
      });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Loader done");
  await user.click(screen.getByRole("tab", { name: /Theory of the estimator/ }));
  await user.type(screen.getByLabelText(/work performed/i), "Proved the bound");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => expect(submissions).toHaveLength(1));
  const body = submissions[0]!.body as { entries: { project_id: string }[] };
  expect(body.entries.map((entry) => entry.project_id).sort()).toEqual(["pr1", "pr2"]);
  expect(submissions[0]!.key).toBeTruthy();
});

test("names the projects the package is missing, rather than repeating the rule", async () => {
  // The API says which ones; rendering `detail` alone told a student whose tabs were all full
  // that the package was incomplete and left them to work out which project it meant.
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", () =>
      HttpResponse.json(
        {
          title: "Validation failed",
          status: 422,
          detail: "the package is missing an entry for every required project",
          missing_project_ids: ["pr2"],
        },
        { status: 422 },
      ),
    ),
  ]);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: /submit/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Theory of the estimator");
});

test("falls back to what the API said when it names no project", async () => {
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", () =>
      HttpResponse.json(
        { title: "Validation failed", status: 422, detail: "the package is empty" },
        { status: 422 },
      ),
    ),
  ]);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: /submit/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/the package is empty/i);
});

test("shows the deadline for the week being reported", async () => {
  renderPage();

  expect(await screen.findByTestId("deadline")).toHaveTextContent("23:59");
});

// ---------------------------------------------------------------- what must not be lost or doubled

test("opening the editor without typing saves nothing", async () => {
  // The hook baselined on `{}` before the draft loaded, so every visit PATCHed 1.5 s later —
  // creating a report in DRAFT and flipping the student off "not started".
  const saved: unknown[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", async ({ request }) => {
      saved.push(await request.json());
      return HttpResponse.json({});
    }),
  ]);

  await screen.findByLabelText(/work performed/i);
  await new Promise((resolve) => setTimeout(resolve, 2500));

  expect(saved).toEqual([]);
});

test("an edit made just before navigating away is still saved", async () => {
  // The effect cleanup cancelled the pending timer, so an edit within the debounce window was
  // dropped with no error and the indicator's last word was "saved".
  const saved: { entries: Record<string, { work_performed: string }> }[] = [];
  const { unmount } = renderPage([
    http.patch("/api/v1/periods/p1/report/draft", async ({ request }) => {
      const body = (await request.json()) as { content: (typeof saved)[number] };
      saved.push(body.content);
      return HttpResponse.json({});
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Two paragraphs of work");
  unmount();

  await waitFor(() => expect(saved.length).toBeGreaterThan(0));
  expect(saved[0]!.entries.pr1!.work_performed).toBe("Two paragraphs of work");
});

test("a double click on submit creates one version, not two", async () => {
  const submissions: (string | null)[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", async () => {
      // A real round-trip: the flush is awaited before the submit, and the button stayed
      // enabled throughout it because `submit.isPending` was still false.
      await new Promise((resolve) => setTimeout(resolve, 150));
      return HttpResponse.json({});
    }),
    http.post("/api/v1/periods/p1/report/submit", async ({ request }) => {
      submissions.push(request.headers.get("Idempotency-Key"));
      return HttpResponse.json({
        id: "v1",
        report_id: "r1",
        version_no: 1,
        author_id: "s1",
        submitted_at: "2026-09-20T10:00:00Z",
        timing_status: "on_time",
        entries: [],
      });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Loader done");
  const button = screen.getByRole("button", { name: /submit/i });
  await Promise.all([user.click(button), user.click(button)]);

  await waitFor(() => expect(submissions.length).toBeGreaterThan(0));
  expect(submissions).toHaveLength(1);
});

test("a retried submission carries the same idempotency key", async () => {
  // The key was minted inside mutationFn, so a retry looked like a new submission to the server.
  const keys: (string | null)[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", async ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key"));
      return keys.length === 1
        ? HttpResponse.json({ title: "Server error", status: 500, detail: "oops" }, { status: 500 })
        : HttpResponse.json({
            id: "v1",
            report_id: "r1",
            version_no: 1,
            author_id: "s1",
            submitted_at: "2026-09-20T10:00:00Z",
            timing_status: "on_time",
            entries: [],
          });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Loader done");
  await user.click(screen.getByRole("button", { name: /submit/i }));
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => expect(keys).toHaveLength(2));
  expect(keys[0]).toBe(keys[1]);
});

test("waits for the projects before deciding each entry's stage", async () => {
  // `stageOf` falls back to "implementation", drafts are seeded once, and the stage is not shown
  // in the form — so a slow /projects response filed a theory project as implementation with
  // nothing on screen to correct.
  const submissions: { entries: { project_id: string; stage: string }[] }[] = [];
  renderPage([
    http.get("/api/v1/projects", async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
      return HttpResponse.json({ items: PROJECTS });
    }),
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", async ({ request }) => {
      submissions.push((await request.json()) as (typeof submissions)[number]);
      return HttpResponse.json({
        id: "v1",
        report_id: "r1",
        version_no: 1,
        author_id: "s1",
        submitted_at: "2026-09-20T10:00:00Z",
        timing_status: "on_time",
        entries: [],
      });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Loader done");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => expect(submissions).toHaveLength(1));
  const stages = Object.fromEntries(
    submissions[0]!.entries.map((entry) => [entry.project_id, entry.stage]),
  );
  expect(stages).toEqual({ pr1: "implementation", pr2: "theory" });
});

test("the attachments already on an entry are read back from the server", async () => {
  // They used to live in component state, so reopening the week showed an empty list over files
  // that were sitting in object storage (REP-04).
  renderPage();
  // Registered after the defaults so it wins: msw takes the first matching handler.
  server.use(
    http.get("/api/v1/artifacts", ({ request }) => {
      const url = new URL(request.url);
      if (url.searchParams.get("project_id") !== "pr1") return HttpResponse.json([]);
      return HttpResponse.json([
        {
          artifact_id: "a1",
          owner_student_id: "s1",
          project_id: "pr1",
          period_id: "p1",
          entry_id: null,
          kind: "upload",
          filename: "week3.pptx",
          supported_claim: "the deck behind the recall number",
          source_url: null,
          version_no: 1,
          byte_size: 33797,
          content_type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          extraction_state: "ok",
          extraction_note: "",
          uploaded: true,
          created_at: "2026-09-15T02:00:00Z",
        },
      ]);
    }),
  );

  await userEvent.click(await screen.findByRole("tab", { name: /Baseline evaluation/ }));

  expect(await screen.findByText("week3.pptx")).toBeInTheDocument();
});

test("a week already submitted reopens with what was submitted, not with empty boxes", async () => {
  // The editor recovered the autosaved draft and nothing else. A report submitted without one —
  // the seed does exactly this — reopened as blank fields over a version that had content, and
  // pressing Submit wrote that blankness over the record as a new current version.
  renderPage([
    http.get("/api/v1/periods/p1/report", () =>
      HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v1",
      }),
    ),
    http.get("/api/v1/report-versions/v1", () =>
      HttpResponse.json({
        id: "v1",
        report_id: "r1",
        version_no: 1,
        author_id: "s1",
        submitted_at: "2026-09-17T10:00:00Z",
        timing_status: "on_time",
        entries: [
          {
            id: "e1",
            report_version_id: "v1",
            project_id: "pr1",
            stage: "implementation",
            milestone_ids: [],
            planned_work_ref: {},
            work_performed: "Reproduced the published split sizes.",
            results: "nDCG within 0.01 of the paper.",
            experiments: [],
            deviations: "",
            next_plan: { outcomes: ["Run the ablation"] },
            questions: "",
            evidence_refs: [],
            hours: null,
            content_changed_in_version_id: "v1",
          },
        ],
      }),
    ),
  ]);

  expect(
    await screen.findByDisplayValue("Reproduced the published split sizes."),
  ).toBeInTheDocument();
  expect(screen.getByDisplayValue("nDCG within 0.01 of the paper.")).toBeInTheDocument();
  // `next_plan` goes out as `{ outcomes: [text] }` and has to come back as the text.
  expect(screen.getByDisplayValue("Run the ablation")).toBeInTheDocument();
  // And the screen says the week is already in, which is what makes resubmitting a decision.
  expect(screen.getByTestId("already-submitted")).toBeInTheDocument();
});

test("a period that is not one of theirs says so, rather than loading for ever", async () => {
  // The loading guard waits for the drafts, the drafts wait for the obligations, and an
  // inaccessible period 404s them — so the screen never reached the message written for this.
  renderPage([
    http.get("/api/v1/periods/p1/obligations", () =>
      HttpResponse.json(
        { title: "Not found", status: 404, detail: "period not found" },
        { status: 404 },
      ),
    ),
  ]);

  expect(await screen.findByText(/does not exist, or is not one of yours/i)).toBeInTheDocument();
});

test("the next-week plan goes out in the shape a baseline is frozen from", async () => {
  // It went out as `{ outcomes: [text] }`, and the baseline is frozen from
  // `items[].planned_outcome` — so every plan a student typed was dropped on its way to PROJ-04.
  const submissions: { entries: { project_id: string; next_plan: unknown }[] }[] = [];
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", async ({ request }) => {
      submissions.push((await request.json()) as (typeof submissions)[number]);
      return HttpResponse.json({
        id: "v1",
        report_id: "r1",
        version_no: 1,
        author_id: "s1",
        submitted_at: "2026-09-20T10:00:00Z",
        timing_status: "on_time",
        entries: [],
      });
    }),
  ]);
  const user = userEvent.setup();

  await user.type(await screen.findByLabelText(/work performed/i), "Loader done");
  await user.type(screen.getByLabelText(/next-week plan/i), "Fit the seasonal term");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => expect(submissions).toHaveLength(1));
  const sent = submissions[0]!.entries.find((entry) => entry.project_id === "pr1")!;
  expect(sent.next_plan).toEqual({ items: [{ planned_outcome: "Fit the seasonal term" }] });
  // An entry with no plan sends no plan, rather than an item with an empty outcome in it.
  const other = submissions[0]!.entries.find((entry) => entry.project_id === "pr2")!;
  expect(other.next_plan).toEqual({});
});

test("each tab says whether its entry is already in the package", async () => {
  // Nothing distinguished the one project a student still owed from the three they had written,
  // which is the same defect `/me` had and the reason a week could look finished while it was not.
  renderPage([
    http.get("/api/v1/periods/p1/obligations", () =>
      HttpResponse.json([
        { ...OBLIGATIONS[0], submitted: true },
        { ...OBLIGATIONS[1], submitted: false },
      ]),
    ),
    http.get("/api/v1/periods/p1/report", () =>
      HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: null,
      }),
    ),
  ]);

  expect(await screen.findByTestId("tab-state-pr1")).toHaveTextContent(/submitted/i);
  expect(screen.getByTestId("tab-state-pr2")).toHaveTextContent(/required/i);
  // And the header says the week is in but not finished, which "Submitted …" alone did not.
  expect(screen.getByTestId("still-owed")).toHaveTextContent("1 project");
});

test("the tabs are a keyboard tab strip, not three buttons wearing the role", async () => {
  // `role="tab"` with no panel, no `aria-controls` and every tab in the tab order: a screen
  // reader was told "tab 1 of 2" and offered nowhere to go.
  renderPage();
  const user = userEvent.setup();

  const first = await screen.findByRole("tab", { name: /Baseline evaluation/ });
  const second = screen.getByRole("tab", { name: /Theory of the estimator/ });
  expect(first).toHaveAttribute("aria-controls", "entry-panel-pr1");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "entry-panel-pr1");
  expect(first).toHaveAttribute("tabindex", "0");
  expect(second).toHaveAttribute("tabindex", "-1");

  first.focus();
  await user.keyboard("{ArrowRight}");

  expect(second).toHaveFocus();
  expect(second).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tabpanel")).toHaveAttribute("id", "entry-panel-pr2");
});

test("shows a validation failure as a sentence instead of blanking the page", async () => {
  // QA pass 3, defect #1. FastAPI answers its own validation errors with an array of objects under
  // `detail`, where every other refusal in this API carries a string. React renders an array by
  // rendering each of its children, so rendering that here was React error #31 — and the router's
  // error boundary replaced the whole application, navigation included, with a blank error page.
  // A student reached it by typing a negative number in the optional Hours box and pressing the
  // one button on the screen.
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", () =>
      HttpResponse.json(
        {
          detail: [
            {
              type: "greater_than_equal",
              loc: ["body", "entries", 0, "hours"],
              msg: "Input should be greater than or equal to 0",
              input: -1,
              ctx: { ge: 0 },
            },
          ],
        },
        { status: 422 },
      ),
    ),
  ]);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: /submit/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "entries[0].hours: Input should be greater than or equal to 0",
  );
  // The editor is still there to correct the entry in, which is the whole point.
  expect(screen.getByRole("button", { name: /submit/i })).toBeInTheDocument();
});
