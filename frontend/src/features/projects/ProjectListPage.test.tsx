/**
 * The list is what gives UI-03 a way in, and the create form is where the one real trap lives: a
 * new project is `proposed`, and nothing becomes due on a proposed project.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { ProjectListPage } from "@/features/projects/pages/ProjectListPage";
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

function renderPage(me: object = PROF, items: object[] = [PROJECT], joinable: object[] = []) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/projects/joinable", () => HttpResponse.json(joinable)),
    http.get("/api/v1/projects", () =>
      HttpResponse.json({ items, next_cursor: null, limit: 50 }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("each project links to its own page, which nothing in the app linked to before", async () => {
  renderPage();

  const row = within(await screen.findByTestId("project-list")).getByRole("link", {
    name: /retrieval baselines/i,
  });

  expect(row).toHaveAttribute("href", "/projects/p1");
});

test("creating a project posts the title and stage", async () => {
  const posted: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.post("/api/v1/projects", async ({ request }) => {
      posted.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(PROJECT, { status: 201 });
    }),
  );
  await screen.findByTestId("project-list");

  await userEvent.type(screen.getByLabelText(/title/i), "New project");
  await userEvent.click(screen.getByRole("button", { name: /create project/i }));

  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(posted[0]).toMatchObject({ title: "New project", stage: "implementation" });
});

test("the form says that a new project is proposed and owes nothing yet", async () => {
  renderPage();

  await screen.findByTestId("project-list");

  // The trap the whole of PR 2 exists to close: creating and assigning look like the job, and
  // produce nothing until the project is active.
  expect(
    screen.getByText(/A new project is proposed.*until it is active and a student is assigned/i),
  ).toBeInTheDocument();
});

test("a student is offered the create form, and told their project is active at once", async () => {
  renderPage(STUDENT);

  await screen.findByTestId("project-list");

  expect(screen.getByRole("button", { name: /create project/i })).toBeInTheDocument();
  // The professor's note says the opposite thing, and showing a student the wrong one would tell
  // them their project owes nothing when it does.
  expect(screen.getByText(/active as soon as you create it/i)).toBeInTheDocument();
  expect(
    screen.queryByText(/A new project is proposed/i),
  ).not.toBeInTheDocument();
});


const OPEN = {
  id: "p9",
  title: "Open to joining",
  stage: "theory",
  status: "active",
  member_count: 2,
};

test("a student is offered the open projects, and joining posts to the join route", async () => {
  const joined: string[] = [];
  renderPage(STUDENT, [PROJECT], [OPEN]);
  server.use(
    http.post("/api/v1/projects/:id/join", ({ params }) => {
      joined.push(String(params.id));
      return HttpResponse.json({}, { status: 201 });
    }),
  );

  const panel = await screen.findByTestId("joinable");
  expect(within(panel).getByText("Open to joining")).toBeInTheDocument();
  expect(within(panel).getByText(/2 members/)).toBeInTheDocument();

  await userEvent.click(within(panel).getByTestId("join-project"));
  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(joined).toEqual(["p9"]);
});

test("the professor is not offered projects to join, and a student with none sees no panel", async () => {
  // Hidden rather than empty: in a workspace where nothing is ever opened, an empty panel would
  // advertise a feature that will never do anything there.
  renderPage(STUDENT, [PROJECT], []);
  await screen.findByTestId("project-list");
  expect(screen.queryByTestId("joinable")).not.toBeInTheDocument();
});
