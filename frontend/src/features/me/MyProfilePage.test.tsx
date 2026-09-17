/**
 * The student's own counterpart to `/students/:id` — the screen `architecture.md` §4.2 has named
 * since the route table was written and which was never built.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { MyProfilePage } from "@/features/me/pages/MyProfilePage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const ME = {
  id: "s1",
  workspace_id: "w1",
  role: "student",
  email: "an@example.edu",
  display_name: "An",
  state: "active",
  created_at: "2026-09-01T00:00:00Z",
};

const ASSESSMENT = {
  id: "a1",
  student_id: "s1",
  project_id: "pr1",
  period_id: "per1",
  progress_index: 79,
  confidence: "high",
  confidence_reasons: [],
  published_at: "2026-09-21T03:00:00Z",
};

function renderPage(assessments: object[] = [ASSESSMENT], trend: object[] = []) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(ME)),
    http.get("/api/v1/assessments", () => HttpResponse.json(assessments)),
    http.get("/api/v1/projects", () =>
      HttpResponse.json({ items: [{ id: "pr1", title: "Baseline evaluation", status: "active" }] }),
    ),
    http.get("/api/v1/trends", () => HttpResponse.json(trend)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MyProfilePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("each released assessment is listed by project and opens in full", async () => {
  renderPage();

  const list = await screen.findByTestId("my-assessments");
  const link = await within(list).findByRole("link", { name: /baseline evaluation/i });

  expect(link).toHaveAttribute("href", "/me/assessments/a1");
});

test("a rubric change is stated rather than smoothed over", async () => {
  // AC-10: a trend read across a change of rubric is not a trend, and that matters as much to the
  // person being assessed as to the person assessing.
  renderPage(
    [ASSESSMENT],
    [
      {
        assessment_id: "a1",
        period_id: "per1",
        progress_index: 70,
        plan_completion: "0.7",
        confidence: "high",
        rubric_version_id: "r1",
        created_at: "2026-09-14T00:00:00Z",
      },
      {
        assessment_id: "a2",
        period_id: "per2",
        progress_index: 79,
        plan_completion: "0.8",
        confidence: "high",
        rubric_version_id: "r2",
        created_at: "2026-09-21T00:00:00Z",
      },
    ],
  );

  expect(await screen.findByTestId("rubric-break")).toBeInTheDocument();
});

test("a student with nothing approved is told so, not shown an empty chart", async () => {
  renderPage([]);

  expect(await screen.findByText(/No assessment has been produced yet/i)).toBeInTheDocument();
});
