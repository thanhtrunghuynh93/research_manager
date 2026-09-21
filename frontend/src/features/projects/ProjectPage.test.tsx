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

function renderPage(
  me: object = PROF,
  project: object = PROJECT,
  members: object[] = [],
  documents: object[] = [],
) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/projects/p1", () => HttpResponse.json(project)),
    http.get("/api/v1/projects/p1/members", () => HttpResponse.json(members)),
    http.get("/api/v1/projects/p1/milestones", () => HttpResponse.json([])),
    http.get("/api/v1/artifacts", () => HttpResponse.json(documents)),
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

test("a student on the project is offered no professor controls, and no edit they may not make", async () => {
  // Someone else's project: they may read it, and that is all. The status controls and the member
  // picker are the professor's, and the fields form belongs to whoever started it.
  renderPage(STUDENT);

  await screen.findByText("Retrieval baselines");

  expect(screen.queryByTestId("project-status-controls")).not.toBeInTheDocument();
  expect(screen.queryByTestId("add-member")).not.toBeInTheDocument();
  expect(screen.queryByTestId("project-fields")).not.toBeInTheDocument();
});

test("the student who started the project may edit its record but not its standing", async () => {
  renderPage(STUDENT, { ...PROJECT, created_by: STUDENT.id, status: "active" });

  await screen.findByText("Retrieval baselines");

  expect(screen.getByTestId("project-fields")).toBeInTheDocument();
  // AUTH-07 stops short of the project's standing: status and open-to-joining stay the
  // professor's, so the creator never sees the control that would change them.
  expect(screen.queryByTestId("project-status-controls")).not.toBeInTheDocument();
  expect(screen.queryByTestId("open-to-join")).not.toBeInTheDocument();
});

test("a student member is offered the way out, posting to their own membership", async () => {
  const ended: string[] = [];
  renderPage(STUDENT, PROJECT, [
    {
      id: "m1",
      project_id: "p1",
      student_id: STUDENT.id,
      student_name: "An",
      responsibility: "",
      origin: "self_joined",
      joined_on: "2026-09-14",
      left_on: null,
      planned_allocation: null,
      created_at: "2026-09-14T00:00:00Z",
    },
    {
      id: "m2",
      project_id: "p1",
      student_id: "someone-else",
      student_name: "Bao",
      responsibility: "",
      origin: "assigned",
      joined_on: "2026-09-14",
      left_on: null,
      planned_allocation: null,
      created_at: "2026-09-14T00:00:00Z",
    },
  ]);
  server.use(
    http.post("/api/v1/projects/p1/members/:membershipId/end", ({ params }) => {
      ended.push(String(params.membershipId));
      return HttpResponse.json({});
    }),
  );

  const done = await screen.findByTestId("leave-project");
  // The copy is the student's: finishing their part, not abandoning something.
  expect(done).toHaveTextContent(/done this project/i);

  // A student cannot rejoin unless the professor opens the project again, so it asks first.
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await userEvent.click(done);
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(ended).toEqual([]);

  confirm.mockReturnValue(true);
  await userEvent.click(done);
  await new Promise((resolve) => setTimeout(resolve, 50));

  // Their own membership, not the co-member's, which the page also lists.
  expect(ended).toEqual(["m1"]);
  confirm.mockRestore();
});

test("a student who has left sees the record, and is told what is not shown", async () => {
  // Leaving revokes the ongoing work, not the name: their reports and assessments still point at
  // this project. The sections a past member cannot read answer empty rather than forbidden, so
  // rendering them would assert "no milestones yet" to the one reader who cannot know that.
  renderPage(
    STUDENT,
    {
      ...PROJECT,
      status: "active",
      description: "Reproduce and extend the retrieval baselines.",
      viewer_left_on: "2026-09-18",
    },
    [
      {
        id: "m1",
        project_id: "p1",
        student_id: STUDENT.id,
        student_name: "An",
        responsibility: "",
        origin: "assigned",
        joined_on: "2026-08-31",
        left_on: "2026-09-18",
        planned_allocation: null,
        created_at: "2026-08-31T00:00:00Z",
      },
    ],
  );

  // The record is there, named.
  expect(await screen.findByRole("heading", { name: /Retrieval baselines/ })).toBeInTheDocument();
  expect(screen.getByText(/Reproduce and extend the retrieval baselines\./)).toBeInTheDocument();
  expect(screen.getByTestId("left-notice")).toHaveTextContent(/You left this project/);

  // And the working detail is absent rather than shown as empty.
  expect(screen.queryByText(/No milestones yet/i)).not.toBeInTheDocument();
  // Nothing to leave any more.
  expect(screen.queryByTestId("leave-project")).not.toBeInTheDocument();
});

test("a student still on the project sees all of it, and no notice", async () => {
  renderPage(STUDENT, { ...PROJECT, status: "active" }, [
    {
      id: "m1",
      project_id: "p1",
      student_id: STUDENT.id,
      student_name: "An",
      responsibility: "",
      origin: "assigned",
      joined_on: "2026-08-31",
      left_on: null,
      planned_allocation: null,
      created_at: "2026-08-31T00:00:00Z",
    },
  ]);

  await screen.findByRole("heading", { name: /Retrieval baselines/ });
  expect(screen.queryByTestId("left-notice")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /members/i })).toBeInTheDocument();
});

test("the project's related documents are on the page, and a departed member gets none of it", async () => {
  // ADR 0018: documents belong to the project, so everyone on it reads them — and the block they
  // sit in is the one a student who has left is not shown at all.
  renderPage(
    STUDENT,
    { ...PROJECT, status: "active" },
    [
      {
        id: "m1",
        project_id: "p1",
        student_id: STUDENT.id,
        student_name: "An",
        responsibility: "",
        origin: "assigned",
        joined_on: "2026-08-31",
        left_on: null,
        planned_allocation: null,
        created_at: "2026-08-31T00:00:00Z",
      },
    ],
    [
      {
        artifact_id: "a1",
        owner_student_id: STUDENT.id,
        project_id: "p1",
        period_id: null,
        entry_id: null,
        filename: "protocol.md",
        byte_size: 2048,
        extraction_state: "pending",
        created_at: "2026-09-20T00:00:00Z",
      },
    ],
  );

  expect(await screen.findByTestId("project-documents")).toBeInTheDocument();
  expect(await screen.findByText("protocol.md")).toBeInTheDocument();
  // A member may add one.
  expect(screen.getByLabelText(/attach a document/i)).toBeInTheDocument();
});

test("neither milestone completion nor research decisions is on the page", async () => {
  // Both were removed because nothing in the product writes what they showed: `accepted_completion`
  // has no screen that sets it, so completion read 0% as though it were a finding, and decisions
  // are professor-only to record with no screen to record them. The endpoints still answer.
  const asked: string[] = [];
  server.use(
    http.get("/api/v1/projects/p1/progress", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json({
        weighted_completion: "0.5000",
        completed_milestones: 1,
        milestone_count: 2,
        overdue_milestones: 0,
      });
    }),
    http.get("/api/v1/projects/p1/decisions", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json([
        {
          id: "d1",
          decision: "Dropped the BM25 baseline",
          rationale: "Superseded",
          decided_on: "2026-09-01",
        },
      ]);
    }),
  );
  renderPage(PROF, { ...PROJECT, status: "active" });

  await screen.findByRole("heading", { name: /Retrieval baselines/ });
  expect(screen.queryByTestId("project-progress")).not.toBeInTheDocument();
  expect(screen.queryByTestId("decisions")).not.toBeInTheDocument();
  expect(screen.queryByText(/Dropped the BM25 baseline/)).not.toBeInTheDocument();
  // Not fetched either: a panel that is gone should not still cost two requests a view.
  await new Promise((resolve) => setTimeout(resolve, 100));
  expect(asked).toEqual([]);
});

test("a project the student has left is not asked for what it will not show", async () => {
  // Four requests per view, answered and then discarded, is the shape of a screen that decided
  // what to show after deciding what to fetch — and one of them asked for a member list this
  // reader is deliberately not given.
  const asked: string[] = [];
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(STUDENT)),
    http.get("/api/v1/projects/p1", () =>
      HttpResponse.json({ ...PROJECT, status: "active", viewer_left_on: "2026-09-18" }),
    ),
    http.get("/api/v1/projects/p1/members", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json([]);
    }),
    http.get("/api/v1/projects/p1/milestones", ({ request }) => {
      asked.push(new URL(request.url).pathname);
      return HttpResponse.json([]);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/projects/p1"]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await screen.findByTestId("left-notice");
  await new Promise((resolve) => setTimeout(resolve, 100));

  expect(asked).toEqual([]);
});
