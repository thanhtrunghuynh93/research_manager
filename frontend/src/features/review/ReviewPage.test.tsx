/** UI-05 and ASSESS-08: the three panes, and the reason an override has to carry. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ReviewPage } from "@/features/review/pages/ReviewPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const ASSESSMENT = {
  id: "a1",
  student_id: "s1",
  project_id: "pr1",
  period_id: "p1",
  version_no: 1,
  ratings: {
    progress: { rating: 3, rationale: "the agreed outcome was met", evidence_ref_ids: ["e1"] },
    learning: { rating: "unknown", rationale: "nothing settles this", evidence_ref_ids: [] },
    rigor: { rating: 3, rationale: "traceable", evidence_ref_ids: ["e1"] },
    artifacts: { rating: 2, rationale: "partial", evidence_ref_ids: [] },
  },
  effective_ratings: {},
  progress_index: null,
  plan_completion: null,
  coverage_pct: "75.00",
  confidence: "medium",
  confidence_reasons: ["evidence coverage is 75%, below the 90% threshold"],
  narrative: {
    discrepancies: [{ claim: "beat the state of the art", status: "unverifiable" }],
  },
  reason: "",
  model_name: "fake-1",
  prompt_versions: {},
  review_state: "draft",
  published_at: null,
  created_at: "2026-09-21T03:00:00Z",
};

function renderPage(assessment: Record<string, unknown> = ASSESSMENT, approve = vi.fn()) {
  server.use(
    http.get("/api/v1/assessments/a1", () => HttpResponse.json(assessment)),
    http.get("/api/v1/assessments/a1/evidence", () =>
      HttpResponse.json([
        {
          evidence_ref_id: "e1",
          text: "commit a1f3c9e — fixed the judgment parser",
          locator: "/projects/pr1#commit",
          visibility: "project_shared",
          source_version: "a1f3c9e",
          integration_of_earlier_work: false,
        },
      ]),
    ),
    // Who and what this assessment is about. Until these were called, the page said "Review"
    // and nothing else, while carrying all three ids.
    http.get("/api/v1/users/s1", () =>
      HttpResponse.json({ id: "s1", display_name: "An Nguyen", email: "an@example.edu" }),
    ),
    http.get("/api/v1/projects", () =>
      HttpResponse.json({ items: [{ id: "pr1", title: "Retrieval baselines" }] }),
    ),
    http.get("/api/v1/periods", () =>
      HttpResponse.json([{ id: "p1", local_start: "2026-09-14", local_end: "2026-09-20" }]),
    ),
    http.post("/api/v1/assessments/a1/approve", async ({ request }) => {
      approve(await request.json());
      return HttpResponse.json({
        id: "rev1",
        assessment_version_id: "a1",
        state: "approved",
        published_at: "2026-09-22T01:00:00Z",
        created_at: "2026-09-21T03:00:00Z",
      });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/review/a1"]}>
        <Routes>
          <Route path="/review/:assessmentId" element={<ReviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("shows claims, evidence, and the draft together", async () => {
  renderPage();

  expect(await screen.findByTestId("claims")).toHaveTextContent(/beat the state of the art/);
  expect(await screen.findByTestId("evidence")).toHaveTextContent(/judgment parser/);
  expect(screen.getByTestId("ratings")).toHaveTextContent(/the agreed outcome was met/);
});

test("an index that must be withheld reads as not rated, never as zero", async () => {
  renderPage();

  expect(await screen.findByTestId("progress-index")).toHaveTextContent(
    /not rated — insufficient evidence/i,
  );
});

test("confidence carries its reasons rather than standing alone", async () => {
  // As the badge's `title` these were unreachable by touch or keyboard and unannounced by a
  // screen reader, leaving "LOW CONFIDENCE · 2" as all a professor could find out — while
  // deciding whether to approve and publish on the strength of it.
  renderPage();

  expect(await screen.findByTestId("confidence-reasons")).toHaveTextContent(/coverage is 75%/);
  expect(screen.getByTestId("confidence-badge")).not.toHaveAttribute("title");
});

test("approving an unchanged draft needs no reason", async () => {
  const approve = vi.fn();
  renderPage(ASSESSMENT, approve);

  await userEvent.click(await screen.findByRole("button", { name: /approve and publish/i }));

  await waitFor(() => expect(approve).toHaveBeenCalled());
  expect(approve.mock.calls[0]![0]).toMatchObject({ override: null });
});

test("a changed rating cannot be approved until a reason is given", async () => {
  const approve = vi.fn();
  renderPage(ASSESSMENT, approve);

  const select = await screen.findByLabelText(/progress toward agreed outcomes/i);
  await userEvent.selectOptions(select, "4");

  expect(screen.getByTestId("rationale-required")).toBeInTheDocument();
  const button = screen.getByRole("button", { name: /approve with an override/i });
  expect(button).toBeDisabled();
  expect(approve).not.toHaveBeenCalled();
});

test("the recorded reason travels with the override", async () => {
  const approve = vi.fn();
  renderPage(ASSESSMENT, approve);

  await userEvent.selectOptions(await screen.findByLabelText(/progress toward/i), "4");
  await userEvent.type(
    screen.getByRole("textbox"),
    "The ablation was an additional outcome beyond the plan.",
  );
  await userEvent.click(screen.getByRole("button", { name: /approve with an override/i }));

  await waitFor(() => expect(approve).toHaveBeenCalled());
  const payload = approve.mock.calls[0]![0] as { override: unknown; rationale: string };
  expect(payload.rationale).toMatch(/additional outcome/);
  expect(payload.override).toMatchObject({ ratings: { progress: { rating: 4 } } });
});

test("a rating downgraded by validation shows why", async () => {
  renderPage({
    ...ASSESSMENT,
    ratings: {
      ...ASSESSMENT.ratings,
      progress: {
        rating: "unknown",
        rationale: "state of the art, as reported",
        evidence_ref_ids: [],
        validation_notes: ["1 cited evidence id was not in the snapshot and was dropped"],
      },
    },
  });

  expect(await screen.findByText(/not in the snapshot/)).toBeInTheDocument();
});

test("says whose assessment this is, for which project and week", async () => {
  // A professor could approve and publish from a screen headed only "Review". The ids were all
  // in the payload; nothing resolved them, and eight characters of a UUIDv7 are the same eight
  // characters on every row anyway.
  renderPage();

  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("An Nguyen");
  expect(await screen.findByText(/Retrieval baselines/)).toBeInTheDocument();
  expect(screen.getByText(/Sep 14, 2026 – Sep 20, 2026/)).toBeInTheDocument();
});
