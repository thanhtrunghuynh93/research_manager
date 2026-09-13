/** UI-01: the professor's week, with every condition named rather than implied. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { OverviewPage } from "@/features/overview/pages/OverviewPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const EMPTY = {
  as_of: "2026-09-21T03:00:00Z",
  current_period: {
    period_id: "p1",
    local_start: "2026-09-14",
    local_end: "2026-09-20",
    meeting_date: "2026-09-21",
    deadline_utc: "2026-09-20T16:59:00Z",
    timezone: "Asia/Ho_Chi_Minh",
  },
  outstanding: { count: 0, as_of: "2026-09-21T03:00:00Z", entries: [], note: "" },
  review_queue: [],
  sync_issues: [],
  stalled_analyses: [],
  ai_budget: {
    analysis_delayed: false,
    warning: false,
    reason: "",
    spent_usd: "0",
    monthly_usd: null,
  },
};

function renderPage(overview: Record<string, unknown> = EMPTY) {
  server.use(http.get("/api/v1/overview", () => HttpResponse.json(overview)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("names the period the professor is looking at, without the deadline", async () => {
  renderPage();

  // The week is what orients the professor here; the deadline is the student's to meet, and it
  // is still shown on their own screen and in the weekly editor (REP-01 is covered there).
  expect(await screen.findByText(/Sep 14, 2026 – Sep 20, 2026/)).toBeInTheDocument();
  expect(screen.queryByTestId("deadline")).not.toBeInTheDocument();
});

test("keeps every section on screen when there is nothing to do", async () => {
  renderPage();

  // A missing section reads as a broken screen; an empty one reads as nothing to do.
  expect(
    await screen.findByText(/Every obligation for this week has been met/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Nothing is waiting for review/)).toBeInTheDocument();
  expect(screen.getByText(/Every connected repository synced recently/)).toBeInTheDocument();
  expect(screen.getByText(/Every analysis completed/)).toBeInTheDocument();
});

test("lists who still owes a report and when the count was true", async () => {
  renderPage({
    ...EMPTY,
    outstanding: {
      count: 1,
      as_of: "2026-09-21T03:00:00Z",
      entries: [{ student_id: "student-1", project_id: "p", project_title: "Baselines" }],
      note: "Counted from the reporting obligations after exemptions and extensions.",
    },
  });

  expect(await screen.findByText(/Baselines/)).toBeInTheDocument();
  expect(screen.getByText(/after exemptions and extensions/)).toBeInTheDocument();
  expect(screen.getByText(/as of/)).toBeInTheDocument();
});

test("labels a quiet repository as a sync problem, not as a quiet week", async () => {
  renderPage({
    ...EMPTY,
    sync_issues: [
      {
        repository_id: "r1",
        full_name: "lab/retrieval",
        state: "failed",
        last_finished_at: null,
        error_summary: "credentials revoked",
      },
    ],
  });

  expect(await screen.findByTestId("freshness-badge")).toHaveTextContent(/failed/i);
  expect(
    screen.getByText(/means the evidence is incomplete, not that no work was done/),
  ).toBeInTheDocument();
});

test("says plainly when a spent budget is holding up analysis", async () => {
  renderPage({
    ...EMPTY,
    ai_budget: {
      analysis_delayed: true,
      warning: false,
      reason: "the workspace AI budget for this month is spent (25 of 25 USD)",
      spent_usd: "25",
      monthly_usd: "25",
    },
  });

  expect(await screen.findByTestId("budget-warning")).toHaveTextContent(/budget/);
});

test("distinguishes an analysis that failed from one the budget stopped", async () => {
  renderPage({
    ...EMPTY,
    stalled_analyses: [
      { run_id: "r1", state: "delayed_budget", reason: "the AI budget for this month is spent" },
      { run_id: "r2", state: "partial", reason: "rate_rubric: provider timeout" },
    ],
  });

  expect(await screen.findByText(/delayed_budget/)).toBeInTheDocument();
  expect(screen.getByText(/provider timeout/)).toBeInTheDocument();
});
