/** Reading feedback (ADR 0026): the list, the page, markdown, and files as downloads. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { FeedbackListPage } from "@/features/feedback/pages/FeedbackListPage";
import { FeedbackPage } from "@/features/feedback/pages/FeedbackPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const ME = (role: string) =>
  http.get("/api/v1/auth/me", () =>
    HttpResponse.json({
      id: "u1",
      role,
      email: "u@example.edu",
      display_name: "U",
      workspace_id: "w1",
    }),
  );

const FEEDBACK = {
  feedback_id: "f1",
  student_id: "s1",
  project_id: "p1",
  reports: [
    { report_id: "r1", period_id: "per1", local_start: "2026-09-14", local_end: "2026-09-20" },
  ],
  title: "Phản hồi MealAgent",
  body_markdown: "## Nhận xét\n\nLàm tốt phần loader.\n\n<script>window.pwned=1</script>",
  version: 2,
  status: "published",
  published_version: 1,
  has_unpublished_changes: true,
  attachments: [
    {
      attachment_id: "a1",
      filename: "phan-hoi-mealagent.html",
      content_type: "text/html",
      byte_size: 2048,
      sha256: "x",
    },
  ],
  updated_at: "2026-09-22T03:00:00Z",
  published_at: "2026-09-21T03:00:00Z",
};

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/feedback" element={<FeedbackListPage />} />
          <Route path="/feedback/:id" element={<FeedbackPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a student's list shows what was published, without draft labels", async () => {
  server.use(
    ME("student"),
    http.get("/api/v1/feedback", () =>
      HttpResponse.json({
        items: [
          {
            feedback_id: "f1",
            student_id: "s1",
            project_id: "p1",
            report_ids: ["r1"],
            title: "Phản hồi MealAgent",
            version: 1,
            status: "published",
            published_version: 1,
            has_unpublished_changes: false,
            attachment_count: 1,
            updated_at: "2026-09-21T03:00:00Z",
            published_at: "2026-09-21T03:00:00Z",
            view_url: "x",
          },
        ],
        next_cursor: null,
      }),
    ),
  );

  renderAt("/feedback");

  const link = await screen.findByRole("link", { name: /Phản hồi MealAgent/ });
  expect(link).toHaveAttribute("href", "/feedback/f1");
  expect(screen.getByText("1 file")).toBeInTheDocument();
  expect(screen.queryByText("Published")).not.toBeInTheDocument();
});

test("an empty list says nothing has been published", async () => {
  server.use(
    ME("student"),
    http.get("/api/v1/feedback", () => HttpResponse.json({ items: [], next_cursor: null })),
  );

  renderAt("/feedback");

  expect(await screen.findByTestId("feedback-empty")).toHaveTextContent(
    "Nothing has been published",
  );
});

test("the page renders markdown, never raw HTML, and downloads a file through a link", async () => {
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  server.use(
    ME("student"),
    http.get("/api/v1/feedback/f1", () => HttpResponse.json(FEEDBACK)),
    http.get("/api/v1/feedback/attachments/a1/download", () =>
      HttpResponse.json({ url: "https://files.example/a1", filename: "x", expires_in: 300 }),
    ),
  );

  renderAt("/feedback/f1");

  expect(await screen.findByRole("heading", { name: "Nhận xét" })).toBeInTheDocument();
  expect(screen.getByText("Làm tốt phần loader.")).toBeInTheDocument();
  expect(screen.getByTestId("feedback-body").querySelector("script")).toBeNull();
  // A student is not told about drafts.
  expect(screen.queryByText(/Students still read version/)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith("https://files.example/a1"));
  vi.unstubAllGlobals();
});

test("a professor is told the draft is ahead of what the student reads", async () => {
  server.use(
    ME("prof"),
    http.get("/api/v1/feedback/f1", () => HttpResponse.json(FEEDBACK)),
  );

  renderAt("/feedback/f1");

  expect(await screen.findByRole("status")).toHaveTextContent(
    "This is version 2. Students still read version 1",
  );
});

test("feedback that is not the caller's is a plain not-found", async () => {
  server.use(
    ME("student"),
    http.get("/api/v1/feedback/f9", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Not found", status: 404, detail: "feedback not found" },
        { status: 404 },
      ),
    ),
  );

  renderAt("/feedback/f9");

  expect(await screen.findByRole("alert")).toHaveTextContent("has not been published to you");
});
