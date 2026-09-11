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
    http.get("/api/v1/periods", () => HttpResponse.json([PERIOD])),
    http.get("/api/v1/periods/p1/obligations", () => HttpResponse.json(OBLIGATIONS)),
    http.get("/api/v1/projects", () => HttpResponse.json({ items: PROJECTS })),
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
    ...extra,
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

test("reports what the API says when the package is incomplete", async () => {
  renderPage([
    http.patch("/api/v1/periods/p1/report/draft", () => HttpResponse.json({})),
    http.post("/api/v1/periods/p1/report/submit", () =>
      HttpResponse.json(
        {
          title: "Validation failed",
          status: 422,
          detail: "the package is missing an entry for every required project",
        },
        { status: 422 },
      ),
    ),
  ]);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: /submit/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/missing an entry/i);
});

test("shows the deadline for the week being reported", async () => {
  renderPage();

  expect(await screen.findByTestId("deadline")).toHaveTextContent("23:59");
});
