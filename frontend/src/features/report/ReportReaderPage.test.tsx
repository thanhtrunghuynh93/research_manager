/**
 * REP-02..05: the read half of the loop, which had no surface at either end.
 *
 * The case that most needs a test is the departed-project entry. `submit_report` carries it into
 * every new version, and the editor's tabs come from the obligations — which a project the student
 * has left is no longer in — so that entry was in the record and on no screen in the product.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ReportReaderPage } from "@/features/report/pages/ReportReaderPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PERIOD = { id: "p1", local_start: "2026-09-14", local_end: "2026-09-20" };

const PROJECTS = [
  { id: "pr1", title: "Calibration under drift", stage: "theory", status: "active" },
  { id: "pr2", title: "Retrieval baselines", stage: "implementation", status: "active" },
];

// Only pr1 is still owed. pr2 is the project the student left — its entry rides along in the
// version and appears in no obligation.
const OBLIGATIONS = [
  { id: "o1", period_id: "p1", project_id: "pr1", student_id: "s1", state: "required" },
];

const entry = (id: string, projectId: string, work: string) => ({
  id,
  report_version_id: "v2",
  project_id: projectId,
  stage: "theory",
  work_performed: work,
  results: "",
  deviations: "",
  next_plan: {},
  questions: "",
  hours: null,
  evidence_refs: [],
  milestone_ids: [],
  experiments: [],
  planned_work_ref: {},
});

const VERSIONS = [
  {
    id: "v1",
    report_id: "r1",
    version_no: 1,
    author_id: "s1",
    submitted_at: "2026-09-17T03:54:00Z",
    timing_status: "on_time",
  },
  {
    id: "v2",
    report_id: "r1",
    version_no: 2,
    author_id: "s1",
    submitted_at: "2026-09-18T11:41:00Z",
    timing_status: "on_time",
  },
];

function renderPage({
  as = "student",
  extra = [] as Parameters<typeof server.use>[number][],
} = {}) {
  const route = as === "prof" ? "/students/s1/reports/p1" : "/report/p1/submitted";
  const path =
    as === "prof" ? "/students/:studentId/reports/:periodId" : "/report/:periodId/submitted";
  server.use(
    ...extra,
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({
        id: "s1",
        display_name: "An Nguyen",
        role: as === "prof" ? "prof" : "student",
      }),
    ),
    http.get("/api/v1/users/s1", () => HttpResponse.json({ id: "s1", display_name: "An Nguyen" })),
    http.get("/api/v1/periods", () => HttpResponse.json([PERIOD])),
    http.get("/api/v1/projects", () => HttpResponse.json({ items: PROJECTS })),
    http.get("/api/v1/periods/p1/obligations", () => HttpResponse.json(OBLIGATIONS)),
    http.get("/api/v1/artifacts", () => HttpResponse.json([])),
    http.get("/api/v1/reports/r1/revisions", () => HttpResponse.json([])),
    http.get("/api/v1/reports/r1/versions", () => HttpResponse.json(VERSIONS)),
    http.get("/api/v1/report-versions/v2", () =>
      HttpResponse.json({
        ...VERSIONS[1],
        entries: [
          entry("e1", "pr1", "Proved the projected bound under convexity."),
          entry("e2", "pr2", "Implemented the corpus loader."),
        ],
      }),
    ),
    http.get("/api/v1/report-versions/v1", () =>
      HttpResponse.json({ ...VERSIONS[0], entries: [entry("e0", "pr1", "The first go.")] }),
    ),
    http.get("/api/v1/periods/p1/report", () =>
      HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "resubmitted",
        draft_content: { entries: { pr1: { work_performed: "NEVER SHOW THIS" } } },
        draft_saved_at: "2026-09-19T01:00:00Z",
        first_submitted_at: "2026-09-17T03:54:00Z",
        current_version_id: "v2",
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={<ReportReaderPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders the submitted text of every entry in the current version", async () => {
  renderPage();

  expect(await screen.findByText(/projected bound under convexity/)).toBeInTheDocument();
  expect(screen.getByText(/Implemented the corpus loader/)).toBeInTheDocument();
});

test("shows the entry for a project the student has left, and says so", async () => {
  // The regression that most needs pinning: this entry is in every version and was on no screen.
  renderPage();

  const departed = await screen.findByTestId("entry-pr2");
  expect(departed).toHaveTextContent(/Retrieval baselines/);
  expect(departed).toHaveTextContent(/Left this project/);
  // The project still owed is not marked as departed.
  expect(screen.getByTestId("entry-pr1")).not.toHaveTextContent(/Left this project/);
});

test("never renders the autosaved draft, only what was submitted", async () => {
  // A professor may read `draft_content`; showing it would make autosave surveillance.
  renderPage({ as: "prof" });

  await screen.findByText(/projected bound under convexity/);
  expect(screen.queryByText(/NEVER SHOW THIS/)).not.toBeInTheDocument();
});

test("an older version can be selected and its own text is shown", async () => {
  renderPage();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: /Version 1/ }));

  expect(await screen.findByText(/The first go\./)).toBeInTheDocument();
});

test("a professor can request a revision, and it names the project", async () => {
  const asked: unknown[] = [];
  renderPage({
    as: "prof",
    extra: [
      http.post("/api/v1/reports/r1/revisions", async ({ request }) => {
        asked.push(await request.json());
        return HttpResponse.json({ id: "rr1" }, { status: 201 });
      }),
    ],
  });
  const user = userEvent.setup();

  const button = await screen.findByTestId("request-revision-pr1");
  // The rule is taught before the round trip, as ReviewPage does for an override's rationale.
  expect(button).toBeDisabled();
  await user.type(screen.getAllByPlaceholderText(/What needs to change/)[0]!, "the ablation table");
  await user.click(button);

  await waitFor(() => expect(asked).toHaveLength(1));
  expect(asked[0]).toMatchObject({ project_id: "pr1", reason: "the ablation table" });
});

test("a student sees the professor's reason and gets no professor controls", async () => {
  renderPage({
    extra: [
      http.get("/api/v1/reports/r1/revisions", () =>
        HttpResponse.json([
          {
            id: "rr1",
            report_id: "r1",
            project_id: "pr1",
            reason: "the ablation table is missing",
            created_at: "2026-09-19T02:00:00Z",
            resolved_in_version_id: null,
          },
        ]),
      ),
    ],
  });

  expect(await screen.findByTestId("revision-reason")).toHaveTextContent(
    /ablation table is missing/,
  );
  expect(screen.queryByTestId("request-revision-pr1")).not.toBeInTheDocument();
  expect(screen.queryByTestId("mark-reviewed")).not.toBeInTheDocument();
});

test("marking the week reviewed is offered to a professor and moves the state", async () => {
  const marked: string[] = [];
  renderPage({
    as: "prof",
    extra: [
      http.post("/api/v1/reports/r1/reviewed", () => {
        marked.push("r1");
        return HttpResponse.json({
          id: "r1",
          student_id: "s1",
          period_id: "p1",
          workflow_state: "reviewed",
          draft_content: {},
          first_submitted_at: "2026-09-17T03:54:00Z",
          current_version_id: "v2",
        });
      }),
    ],
  });
  const user = userEvent.setup();

  await user.click(await screen.findByTestId("mark-reviewed"));

  await waitFor(() => expect(marked).toEqual(["r1"]));
  await waitFor(() => expect(screen.getByTestId("mark-reviewed")).toBeDisabled());
});

test("a week with nothing submitted says so rather than showing an empty report", async () => {
  renderPage({
    extra: [
      http.get("/api/v1/periods/p1/report", () =>
        HttpResponse.json({
          id: "r1",
          student_id: "s1",
          period_id: "p1",
          workflow_state: "draft",
          draft_content: { entries: { pr1: { work_performed: "half typed" } } },
          draft_saved_at: "2026-09-19T01:00:00Z",
          first_submitted_at: null,
          current_version_id: null,
        }),
      ),
    ],
  });

  expect(await screen.findByText(/nothing has been submitted/)).toBeInTheDocument();
  expect(screen.queryByText(/half typed/)).not.toBeInTheDocument();
});
