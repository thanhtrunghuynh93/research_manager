/**
 * ADR 0018: a project's documents belong to the project.
 *
 * The distinction the whole feature rests on is what a file is *not* attached to — a week's
 * evidence carries a period, a project document carries none — so the first test here is the one
 * that would catch the two being confused.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { ProjectDocuments } from "@/features/projects/components/ProjectDocuments";
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

const document = (over: Record<string, unknown> = {}) => ({
  artifact_id: "a1",
  owner_student_id: "s1",
  project_id: "p1",
  period_id: null,
  entry_id: null,
  filename: "protocol.md",
  byte_size: 2048,
  extraction_state: "pending",
  created_at: "2026-09-20T00:00:00Z",
  ...over,
});

function renderPanel(rows: unknown[] = [document()], canAttach = true, me: object = ME) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/artifacts", () => HttpResponse.json(rows)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectDocuments projectId="p1" canAttach={canAttach} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a week's evidence is not a project document, however the API answers", async () => {
  // `GET /artifacts?project_id=` returns everything the caller may see for the project, which for
  // a student includes their own report evidence on it. Only the ones attached to no week belong
  // in this panel.
  renderPanel([
    document(),
    document({ artifact_id: "a2", filename: "week-3-run-log.md", period_id: "per1" }),
    document({ artifact_id: "a3", filename: "submitted-figure.png", entry_id: "e1" }),
  ]);

  expect(await screen.findByText("protocol.md")).toBeInTheDocument();
  expect(screen.queryByText("week-3-run-log.md")).not.toBeInTheDocument();
  expect(screen.queryByText("submitted-figure.png")).not.toBeInTheDocument();
});

test("remove is offered only for the file you attached", async () => {
  renderPanel([
    document(),
    document({ artifact_id: "a2", owner_student_id: "s2", filename: "theirs.pdf" }),
  ]);

  await screen.findByText("protocol.md");
  const rows = screen.getAllByRole("listitem");
  // The API refuses removal by anyone else, so offering the button would be offering a refusal.
  expect(within(rows[0]!).getByTestId("remove-document")).toBeInTheDocument();
  expect(within(rows[1]!).queryByTestId("remove-document")).not.toBeInTheDocument();
});

test("a reader who cannot attach is offered no way to", async () => {
  renderPanel([document()], false);

  await screen.findByText("protocol.md");
  expect(screen.queryByLabelText(/attach a document/i)).not.toBeInTheDocument();
});

test("attaching sends no period, which is what keeps it the project's", async () => {
  const posted: Record<string, unknown>[] = [];
  class SilentXHR {
    static latest: SilentXHR | undefined;
    upload = new EventTarget();
    listeners = new EventTarget();
    status = 200;
    constructor() {
      SilentXHR.latest = this;
    }
    open() {}
    setRequestHeader() {}
    addEventListener(name: string, handler: EventListener) {
      this.listeners.addEventListener(name, handler);
    }
    send() {
      this.listeners.dispatchEvent(new Event("load"));
    }
  }
  vi.stubGlobal("XMLHttpRequest", SilentXHR);
  try {
    server.use(
      http.post("/api/v1/artifacts/uploads", async ({ request }) => {
        posted.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(
          {
            artifact_id: "a9",
            version_no: 1,
            url: "http://store/put",
            expires_in: 60,
            headers: {},
          },
          { status: 201 },
        );
      }),
      http.post("/api/v1/artifacts/a9/confirm", () =>
        HttpResponse.json(document({ artifact_id: "a9" })),
      ),
    );
    renderPanel([]);
    await screen.findByText(/nothing attached yet/i);

    await userEvent.upload(
      screen.getByLabelText(/attach a document/i),
      new File(["# protocol"], "protocol.md", { type: "text/markdown" }),
    );

    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toMatchObject({ project_id: "p1", filename: "protocol.md" });
    expect(posted[0]).not.toHaveProperty("period_id");
    expect(posted[0]).not.toHaveProperty("entry_id");
  } finally {
    vi.unstubAllGlobals();
  }
});
