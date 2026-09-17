/**
 * The project workbench: the two writes that make a project able to produce work.
 *
 * Activation is the one worth a test of its own. A project is created `proposed`, and an obligation
 * derives only from a membership whose project is `active`, so a professor who creates and assigns
 * has done everything that *looks* like the job and produced nothing.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { ProjectPage } from "@/features/projects/pages/ProjectPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PROF = {
  id: "u1",
  workspace_id: "w1",
  role: "prof",
  email: "prof@example.edu",
  display_name: "Prof",
  state: "active",
  created_at: "2026-09-01T00:00:00Z",
};

const STUDENT = { ...PROF, id: "u2", role: "student", email: "an@example.edu" };

const HERE = { ...STUDENT, id: "s1", display_name: "An Nguyen", workspace_id: "w1" };
const ELSEWHERE = { ...STUDENT, id: "s2", display_name: "Other Lab", workspace_id: "w2" };

const PROJECT = {
  id: "p1",
  workspace_id: "w1",
  title: "Retrieval baselines",
  description: "",
  research_questions: [],
  intended_contributions: [],
  stage: "implementation",
  status: "proposed",
  start_on: null,
  target_on: null,
  venue_target: null,
  shared_resources: {},
  ai_restricted: false,
  created_by: "u1",
  created_at: "2026-09-01T00:00:00Z",
};

function renderPage(me: object = PROF, project: object = PROJECT) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/projects/p1", () => HttpResponse.json(project)),
    http.get("/api/v1/projects/p1/members", () => HttpResponse.json([])),
    http.get("/api/v1/projects/p1/milestones", () => HttpResponse.json([])),
    http.get("/api/v1/projects/p1/decisions", () => HttpResponse.json([])),
    http.get("/api/v1/projects/p1/progress", () =>
      HttpResponse.json({
        weighted_completion: null,
        completed_milestones: 0,
        milestone_count: 0,
        overdue_milestones: 0,
      }),
    ),
    http.get("/api/v1/users", () =>
      HttpResponse.json({ items: [HERE, ELSEWHERE], next_cursor: null, limit: 100 }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/p1"]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("activating a proposed project patches it to active", async () => {
  const patched: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.patch("/api/v1/projects/p1", async ({ request }) => {
      patched.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ ...PROJECT, status: "active" });
    }),
  );

  await userEvent.click(await screen.findByTestId("activate-project"));

  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(patched[0]).toEqual({ status: "active" });
});

test("a proposed project says that nothing is owed on it yet", async () => {
  renderPage();

  expect(await screen.findByText(/only for an active project/i)).toBeInTheDocument();
});

test("an active project offers no activate button", async () => {
  renderPage(PROF, { ...PROJECT, status: "active" });

  await screen.findByTestId("project-status-controls");

  expect(screen.queryByTestId("activate-project")).not.toBeInTheDocument();
});

test("the student picker offers only students of the workspace being worked in", async () => {
  // Reads span every workspace the professor belongs to (ADR 0016), but a membership row is
  // written against the anchor's composite foreign key — so a student from elsewhere would fail
  // in the database rather than be refused in words.
  renderPage();

  const picker = await screen.findByLabelText(/student/i);

  expect(picker).toHaveTextContent("An Nguyen");
  expect(picker).not.toHaveTextContent("Other Lab");
});

test("a student viewing the project is offered no write controls", async () => {
  renderPage(STUDENT);

  await screen.findByText("Retrieval baselines");

  expect(screen.queryByTestId("project-status-controls")).not.toBeInTheDocument();
  expect(screen.queryByTestId("add-member")).not.toBeInTheDocument();
});
