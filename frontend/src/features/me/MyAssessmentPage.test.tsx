/**
 * The screen the professor's "publish to the student" has always named, and the three things it
 * must not do.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { MyAssessmentPage } from "@/features/me/pages/MyAssessmentPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const ASSESSMENT = {
  id: "a1",
  student_id: "s1",
  project_id: "p1",
  period_id: "per1",
  progress_index: 79,
  plan_completion: "0.75",
  confidence: "high",
  confidence_reasons: [],
  coverage_pct: 80,
  narrative: "",
  review_state: "approved",
  published_at: "2026-09-21T03:00:00Z",
  version_no: 1,
  ratings: {
    progress: { rating: 3, rationale: "Steady week." },
    learning: { rating: 4, rationale: "Read widely." },
    rigor: { rating: "unknown", rationale: "" },
    artifacts: { rating: 2, rationale: "One notebook." },
  },
  effective_ratings: {},
};

function renderPage(assessment: object | null = ASSESSMENT, feedback: object[] = []) {
  server.use(
    http.get("/api/v1/assessments/a1", () =>
      assessment
        ? HttpResponse.json(assessment)
        : HttpResponse.json({ title: "Not found" }, { status: 404 }),
    ),
    http.get("/api/v1/assessments/a1/feedback", () => HttpResponse.json(feedback)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/me/assessments/a1"]}>
        <Routes>
          <Route path="/me/assessments/:assessmentId" element={<MyAssessmentPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("the ratings and their rationales are shown as they stand", async () => {
  renderPage();

  const ratings = await screen.findByTestId("my-ratings");

  expect(ratings).toHaveTextContent("Steady week.");
  expect(ratings).toHaveTextContent("Read widely.");
});

test("an unrated dimension reads as unknown, never as zero", async () => {
  renderPage();

  const ratings = await screen.findByTestId("my-ratings");

  // "rigor" is `unknown`: a withheld rating and a rating of 0 are different claims.
  expect(ratings).not.toHaveTextContent(/\b0\b/);
});

test("the page never asks for the evidence snapshot", async () => {
  // `GET /assessments/{id}/evidence` would answer for a student, but its items carry their own
  // visibility and the service does not filter them. Not calling it is the whole mitigation, so
  // this handler fails the test rather than returning anything.
  let asked = false;
  renderPage();
  server.use(
    http.get("/api/v1/assessments/a1/evidence", () => {
      asked = true;
      return HttpResponse.json([]);
    }),
  );

  await screen.findByTestId("my-ratings");

  expect(asked).toBe(false);
});

test("no review state is shown, so nothing implies a draft exists", async () => {
  renderPage();

  await screen.findByTestId("my-ratings");

  expect(screen.queryByText(/approved/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/draft/i)).not.toBeInTheDocument();
  expect(screen.getByTestId("released-at")).toBeInTheDocument();
});

test("a correction request posts the student's account of it", async () => {
  const posted: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.post("/api/v1/assessments/a1/corrections", async ({ request }) => {
      posted.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ id: "f1" }, { status: 201 });
    }),
  );
  await screen.findByTestId("my-ratings");

  await userEvent.type(screen.getByLabelText(/ask for a correction/i), "The notebook was merged.");
  await userEvent.click(screen.getByRole("button", { name: /send correction request/i }));

  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(posted[0]).toEqual({ body: "The notebook was merged." });
});

test("an assessment the student may not read says only that, never why", async () => {
  renderPage(null);

  expect(await screen.findByText(/not available to you/i)).toBeInTheDocument();
});
