/** Every submitted weekly report, by week, with its filters in the address bar (UI-01, REP-05). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

import { ReportsPage } from "@/features/reports/pages/ReportsPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PERIODS = [
  {
    id: "p1",
    workspace_id: "w1",
    local_start: "2026-09-14",
    local_end: "2026-09-20",
    start_utc: "2026-09-13T17:00:00Z",
    end_utc: "2026-09-20T17:00:00Z",
    meeting_date: "2026-09-21",
    deadline_utc: "2026-09-20T16:59:00Z",
    reminder_due_utc: "2026-09-20T17:00:00Z",
  },
  {
    id: "p2",
    workspace_id: "w1",
    local_start: "2026-09-21",
    local_end: "2026-09-27",
    start_utc: "2026-09-20T17:00:00Z",
    end_utc: "2026-09-27T17:00:00Z",
    meeting_date: "2026-09-28",
    deadline_utc: "2026-09-27T16:59:00Z",
    reminder_due_utc: "2026-09-27T17:00:00Z",
  },
  {
    // Opened ahead by the calendar; nothing can be filed against it yet.
    id: "p-future",
    workspace_id: "w1",
    local_start: "2099-01-05",
    local_end: "2099-01-11",
    start_utc: "2099-01-04T17:00:00Z",
    end_utc: "2099-01-11T17:00:00Z",
    meeting_date: "2099-01-12",
    deadline_utc: "2099-01-11T16:59:00Z",
    reminder_due_utc: "2099-01-11T17:00:00Z",
  },
];

function row(overrides: Record<string, unknown> = {}) {
  return {
    report_id: "r1",
    student_id: "s1",
    student_name: "An Nguyen",
    period_id: "p2",
    local_start: "2026-09-21",
    local_end: "2026-09-27",
    deadline_utc: "2026-09-27T16:59:00Z",
    workflow_state: "submitted",
    first_submitted_at: "2026-09-26T03:00:00Z",
    last_submitted_at: "2026-09-26T03:00:00Z",
    version_count: 1,
    late: false,
    projects: [{ project_id: "pr1", title: "Retrieval baselines", assessment: null }] as unknown[],
    ...overrides,
  };
}

const ROWS = [
  row({
    report_id: "r1",
    workflow_state: "resubmitted",
    version_count: 2,
    last_submitted_at: "2026-09-27T03:00:00Z",
    projects: [
      {
        project_id: "pr1",
        title: "Retrieval baselines",
        assessment: { assessment_id: "as1", status: "draft" },
      },
      { project_id: "pr2", title: "Survey chapter", assessment: null },
    ],
  }),
  row({
    report_id: "r2",
    student_id: "s2",
    student_name: "Bao Tran",
    workflow_state: "revision_requested",
    late: true,
    first_submitted_at: "2026-09-28T01:00:00Z",
  }),
  row({
    report_id: "r3",
    period_id: "p1",
    local_start: "2026-09-14",
    local_end: "2026-09-20",
    workflow_state: "reviewed",
  }),
];

type Page = { items: unknown[]; next_cursor: string | null; limit: number };

/** Answers `/reports` from `pages` by cursor, and records every query string it was asked. */
function handlers(pages: Record<string, Page>, asked: URLSearchParams[]) {
  return [
    http.get("/api/v1/reports", ({ request }) => {
      const params = new URL(request.url).searchParams;
      asked.push(params);
      return HttpResponse.json(pages[params.get("cursor") ?? ""] ?? pages[""]);
    }),
    http.get("/api/v1/periods", () => HttpResponse.json(PERIODS)),
    http.get("/api/v1/projects", () =>
      HttpResponse.json({
        items: [
          { id: "pr1", title: "Retrieval baselines" },
          { id: "pr2", title: "Survey chapter" },
        ],
        next_cursor: null,
        limit: 50,
      }),
    ),
    http.get("/api/v1/users", () =>
      HttpResponse.json({
        items: [
          { id: "u1", role: "prof", display_name: "Prof Demo" },
          { id: "s1", role: "student", display_name: "An Nguyen" },
          { id: "s2", role: "student", display_name: "Bao Tran" },
        ],
        next_cursor: null,
        limit: 100,
      }),
    ),
  ];
}

function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

function renderPage(
  pages: Record<string, Page> = { "": { items: ROWS, next_cursor: null, limit: 50 } },
  entry = "/reports",
) {
  const asked: URLSearchParams[] = [];
  server.use(...handlers(pages, asked));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route
            path="/reports"
            element={
              <>
                <ReportsPage />
                <Location />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return asked;
}

test("groups the reports by week, newest first, with what each row needs at a glance", async () => {
  renderPage();

  const weeks = await screen.findAllByTestId("report-week");
  expect(weeks).toHaveLength(2);
  expect(within(weeks[0]!).getByRole("heading")).toHaveTextContent("Sep 21, 2026 – Sep 27, 2026");
  expect(within(weeks[1]!).getByRole("heading")).toHaveTextContent("Sep 14, 2026 – Sep 20, 2026");

  const [an, bao] = within(weeks[0]!).getAllByTestId("report-row");
  expect(within(an!).getByRole("link", { name: "An Nguyen" })).toHaveAttribute(
    "href",
    "/students/s1",
  );
  expect(an).toHaveTextContent("Retrieval baselines");
  expect(an).toHaveTextContent("Survey chapter");
  // In the workspace's zone: 03:00 UTC is 10:00 in Asia/Ho_Chi_Minh.
  expect(an).toHaveTextContent(/Submitted Sep 26, 2026, 10:00/);
  expect(an).toHaveTextContent("2 versions");
  expect(within(an!).getByTestId("report-state-chip")).toHaveTextContent("Resubmitted");
  expect(within(an!).queryByTestId("late-chip")).not.toBeInTheDocument();
  // One assessment, on the project that has one.
  const assessment = within(an!).getByTestId("assessment-link");
  expect(assessment).toHaveAttribute("href", "/review/as1");
  expect(assessment).toHaveTextContent("Assessment · Draft");
  expect(within(an!).getByTestId("open-report")).toHaveAttribute("href", "/students/s1/reports/p2");

  expect(within(bao!).getByTestId("late-chip")).toHaveTextContent("Late");
  expect(within(bao!).getByTestId("report-state-chip")).toHaveTextContent("Revision requested");
  expect(bao).not.toHaveTextContent(/versions?\b/);
  expect(within(bao!).queryByTestId("assessment-link")).not.toBeInTheDocument();

  expect(within(weeks[1]!).getByTestId("report-state-chip")).toHaveTextContent("Reviewed");
});

test("each filter goes into the address bar and onto the request", async () => {
  const asked = renderPage();
  await screen.findAllByTestId("report-row");
  // The week choices are weeks that have begun, newest first.
  const weekOptions = within(screen.getByRole("combobox", { name: "Week" }))
    .getAllByRole("option")
    .map((option) => option.getAttribute("value"));
  expect(weekOptions).toEqual(["", "p2", "p1"]);
  // Students only: the professor's own account is on the roll and has no reports.
  expect(
    within(screen.getByRole("combobox", { name: "Student" })).queryByText("Prof Demo"),
  ).not.toBeInTheDocument();

  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Week" }), "p1");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Student" }), "s2");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Project" }), "pr2");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "State" }), "reviewed");
  await userEvent.click(screen.getByRole("checkbox", { name: "Needs review" }));

  await waitFor(() =>
    expect(screen.getByTestId("location")).toHaveTextContent(
      "?week=p1&student=s2&project=pr2&state=reviewed&review=1",
    ),
  );
  await waitFor(() => {
    const last = asked[asked.length - 1]!;
    expect(last.get("period_id")).toBe("p1");
    expect(last.get("student_id")).toBe("s2");
    expect(last.get("project_id")).toBe("pr2");
    expect(last.get("state")).toBe("reviewed");
    expect(last.get("needs_review")).toBe("true");
  });

  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^$/));
});

test("a bookmarked view asks for what its address says", async () => {
  const asked = renderPage(undefined, "/reports?student=s1&review=1");

  await screen.findAllByTestId("report-row");

  expect(asked[0]!.get("student_id")).toBe("s1");
  expect(asked[0]!.get("needs_review")).toBe("true");
  expect(screen.getByRole("combobox", { name: "Student" })).toHaveValue("s1");
  expect(screen.getByRole("checkbox", { name: "Needs review" })).toBeChecked();
});

test("loads the next page on request, and stops offering when there is none", async () => {
  const asked = renderPage({
    "": { items: [ROWS[0]], next_cursor: "c1", limit: 50 },
    c1: { items: [ROWS[2]], next_cursor: null, limit: 50 },
  });

  await screen.findAllByTestId("report-row");
  expect(screen.getAllByTestId("report-row")).toHaveLength(1);

  await userEvent.click(screen.getByRole("button", { name: "Load more" }));

  await waitFor(() => expect(screen.getAllByTestId("report-row")).toHaveLength(2));
  expect(asked[asked.length - 1]!.get("cursor")).toBe("c1");
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

test("an empty workspace and an empty filter say different things", async () => {
  renderPage({ "": { items: [], next_cursor: null, limit: 50 } });
  expect(await screen.findByTestId("reports-empty")).toHaveTextContent(
    "No report has been submitted yet.",
  );
});

test("a filter that matches nothing says so, rather than that nothing exists", async () => {
  renderPage({ "": { items: [], next_cursor: null, limit: 50 } }, "/reports?state=reviewed");
  expect(await screen.findByTestId("reports-empty")).toHaveTextContent(
    "No submitted report matches these filters.",
  );
});
