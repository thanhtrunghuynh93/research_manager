/** UI-02: obligations, the next deadline, draft state, and one way into the weekly flow. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { StudentHomePage } from "@/features/me/pages/StudentHomePage";
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

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StudentHomePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

type ObligationFixture = {
  id: string;
  period_id: string;
  project_id: string;
  student_id: string;
  state: string;
  excuse_reason?: string;
  submitted?: boolean;
};

function handlers({
  obligations = [
    { id: "o1", period_id: "p1", project_id: "pr1", student_id: "s1", state: "required" },
  ] as ObligationFixture[],
  report = null as unknown,
  reportStatus = 404,
  released = [] as object[],
} = {}) {
  return [
    http.get("/api/v1/periods", () => HttpResponse.json([PERIOD])),
    http.get("/api/v1/periods/p1/obligations", () => HttpResponse.json(obligations)),
    http.get("/api/v1/projects", () =>
      HttpResponse.json({ items: [{ id: "pr1", title: "Baseline evaluation", status: "active" }] }),
    ),
    http.get("/api/v1/periods/p1/report", () =>
      report === null
        ? HttpResponse.json(
            { title: "Not found", status: 404, detail: "report not found" },
            { status: reportStatus },
          )
        : HttpResponse.json(report),
    ),
    // Added with the released-assessment block; individual tests override these.
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({
        id: "s1",
        workspace_id: "w1",
        role: "student",
        email: "an@example.edu",
        display_name: "An",
        state: "active",
        created_at: "2026-09-01T00:00:00Z",
      }),
    ),
    http.get("/api/v1/assessments", () => HttpResponse.json(released)),
  ];
}

test("shows the current week, its deadline, and what is owed", async () => {
  server.use(...handlers());
  renderPage();

  expect(await screen.findByText(/Baseline evaluation/)).toBeInTheDocument();
  // 23:59 on 20 September in the workspace timezone, not the raw UTC instant.
  expect(screen.getByTestId("next-deadline")).toHaveTextContent("23:59");
  expect(screen.getByTestId("next-deadline")).toHaveTextContent("Sep 20, 2026");
});

test("offers to start the package when nothing is drafted yet", async () => {
  server.use(...handlers());
  renderPage();

  const link = await screen.findByRole("link", { name: /start this week|open this week/i });
  expect(link).toHaveAttribute("href", "/report/p1");
});

test("shows the draft state once work is saved", async () => {
  server.use(
    ...handlers({
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "draft",
        draft_content: {},
        draft_saved_at: "2026-09-18T04:00:00Z",
        first_submitted_at: null,
        current_version_id: null,
      },
    }),
  );
  renderPage();

  expect(await screen.findByTestId("report-state")).toHaveTextContent(/draft/i);
});

test("says when a revision was requested", async () => {
  server.use(
    ...handlers({
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "revision_requested",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-20T10:00:00Z",
        current_version_id: "v1",
      },
    }),
  );
  renderPage();

  expect(await screen.findByTestId("report-state")).toHaveTextContent(/revision/i);
});

test("a project whose entry is in reads as submitted, not as still required", async () => {
  // `state` is `required` or `excused` and says whether the project has to be in the package — it
  // never changes on submission. Rendering it alone left a week that had been handed in twice
  // showing every project as REQUIRED in the warning colour.
  server.use(
    ...handlers({
      obligations: [
        {
          id: "o1",
          period_id: "p1",
          project_id: "pr1",
          student_id: "s1",
          state: "required",
          submitted: true,
        },
      ],
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "resubmitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v2",
      },
    }),
  );
  renderPage();

  await screen.findByText(/Baseline evaluation/);
  expect(screen.getByText(/^submitted$/i)).toBeInTheDocument();
  expect(screen.queryByText(/^required$/i)).not.toBeInTheDocument();
});

test("a project still missing its entry reads as required", async () => {
  server.use(
    ...handlers({
      obligations: [
        {
          id: "o1",
          period_id: "p1",
          project_id: "pr1",
          student_id: "s1",
          state: "required",
          submitted: false,
        },
      ],
    }),
  );
  renderPage();

  await screen.findByText(/Baseline evaluation/);
  expect(screen.getByText(/^required$/i)).toBeInTheDocument();
});

test("shows an excused project as excused rather than owed", async () => {
  server.use(
    ...handlers({
      obligations: [
        {
          id: "o1",
          period_id: "p1",
          project_id: "pr1",
          student_id: "s1",
          state: "excused",
          excuse_reason: "Approved leave",
        },
      ],
    }),
  );
  renderPage();

  expect(await screen.findByText(/excused/i)).toBeInTheDocument();
  expect(screen.getByText(/Approved leave/)).toBeInTheDocument();
});

test("the week links on to the whole record, which nothing else does", async () => {
  // This screen no longer carries the released assessments and My progress is not on the menu, so
  // this link is the student's only route to what their professor published. A route nothing
  // links to is a route nobody opens.
  server.use(...handlers());
  renderPage();

  const link = await screen.findByTestId("to-my-progress");

  expect(link).toHaveAttribute("href", "/me/profile");
});

test("a submitted week with a project still owed does not read as finished", async () => {
  // `workflow_state` says only that something was handed in. A week submitted on Monday still
  // read "Submitted" after Wednesday's new project added an entry nobody had written — giving the
  // student no reason to reopen the week. REP-08 calls that obligation unfulfilled.
  server.use(
    ...handlers({
      obligations: [
        {
          id: "o1",
          period_id: "p1",
          project_id: "pr1",
          student_id: "s1",
          state: "required",
          submitted: true,
        },
        {
          id: "o2",
          period_id: "p1",
          project_id: "pr2",
          student_id: "s1",
          state: "required",
          submitted: false,
        },
      ],
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v1",
      },
    }),
  );
  renderPage();

  expect(await screen.findByTestId("report-state")).toHaveTextContent(
    "Submitted — 1 project still owed",
  );
});

test("a week whose every entry is in reads as submitted, with no count", async () => {
  server.use(
    ...handlers({
      obligations: [
        {
          id: "o1",
          period_id: "p1",
          project_id: "pr1",
          student_id: "s1",
          state: "required",
          submitted: true,
        },
      ],
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v1",
      },
    }),
  );
  renderPage();

  expect(await screen.findByTestId("report-state")).toHaveTextContent(/^Submitted$/);
});

test("never says the week is untouched while it is still asking", async () => {
  // The chip defaulted to `not_started` and the link to "Start this week" before the report
  // answered, so a submitted week painted briefly as an untouched one under a correct deadline.
  server.use(
    ...handlers({
      report: {
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v1",
      },
    }),
    http.get("/api/v1/periods/p1/report", async () => {
      await new Promise((resolve) => setTimeout(resolve, 200));
      return HttpResponse.json({
        id: "r1",
        student_id: "s1",
        period_id: "p1",
        workflow_state: "submitted",
        draft_content: {},
        draft_saved_at: null,
        first_submitted_at: "2026-09-17T10:00:00Z",
        current_version_id: "v1",
      });
    }),
  );
  renderPage();

  // The deadline is on screen well before the report answers; the state must not be.
  await screen.findByTestId("next-deadline");
  expect(screen.getByTestId("report-state")).not.toHaveTextContent(/not started/i);
  expect(screen.queryByRole("link", { name: /start this week/i })).not.toBeInTheDocument();

  expect(await screen.findByTestId("report-state")).toHaveTextContent(/submitted/i);
});
