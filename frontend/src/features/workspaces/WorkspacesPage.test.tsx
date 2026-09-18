/**
 * ADR 0015: belonging is plural and working in is singular, so a row is one of three things —
 * where you are, one you belong to but are not in, or one you own and could join.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { WorkspacesPage } from "@/features/workspaces/pages/WorkspacesPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const ME = {
  id: "u1",
  workspace_id: "w1",
  role: "prof",
  email: "prof@example.edu",
  display_name: "Prof",
  state: "active",
  created_at: "2026-09-01T00:00:00Z",
};

const HERE = {
  id: "w1",
  name: "Ecomind Lab",
  timezone: "Asia/Ho_Chi_Minh",
  access_epoch: 1,
  owner_id: "u1",
  archived_at: null,
  joined: true,
};

const ELSEWHERE = {
  id: "w2",
  name: "Vision Lab",
  timezone: "Europe/Berlin",
  access_epoch: 1,
  owner_id: "u1",
  archived_at: null,
  joined: false,
};

function renderPage(workspaces: unknown[] = [HERE, ELSEWHERE]) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(ME)),
    http.get("/api/v1/workspaces", () => HttpResponse.json(workspaces)),
    // The calendar panel renders on this page; individual tests override these.
    http.get("/api/v1/calendar", () => HttpResponse.json(null)),
    http.get("/api/v1/periods", () => HttpResponse.json([])),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspacesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("a workspace you belong to offers leave, one you do not offers join", async () => {
  renderPage();

  await screen.findByText("Ecomind Lab");
  const [here, elsewhere] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");

  expect(within(here!).getByText(/working here/i)).toBeInTheDocument();
  expect(within(here!).getByRole("button", { name: /^leave$/i })).toBeInTheDocument();
  expect(within(here!).queryByRole("button", { name: /^join$/i })).not.toBeInTheDocument();

  expect(within(elsewhere!).getByRole("button", { name: /^join$/i })).toBeInTheDocument();
  expect(within(elsewhere!).queryByRole("button", { name: /^leave$/i })).not.toBeInTheDocument();
});

test("a workspace you belong to but are not in offers both work here and leave", async () => {
  // Belonging is plural and working in is singular (ADR 0015), so this row is neither the one you
  // are in nor one you would join: it is one you could go to, or give up.
  renderPage([HERE, { ...ELSEWHERE, joined: true }]);

  await screen.findByText("Vision Lab");
  const [, other] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");

  expect(within(other!).getByRole("button", { name: /work here/i })).toBeInTheDocument();
  expect(within(other!).getByRole("button", { name: /^leave$/i })).toBeInTheDocument();
  expect(within(other!).queryByText(/working here/i)).not.toBeInTheDocument();
});

test("archiving is not offered for the workspace you are in", async () => {
  // You are the account standing in the way of it being empty, so the button could only refuse.
  renderPage();

  await screen.findByText("Ecomind Lab");
  const [here, elsewhere] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");

  expect(within(here!).queryByRole("button", { name: /archive/i })).not.toBeInTheDocument();
  expect(within(elsewhere!).getByRole("button", { name: /archive/i })).toBeInTheDocument();
});

test("shows the API's reason when leaving would strand people", async () => {
  renderPage();
  server.use(
    http.post("/api/v1/workspaces/w1/leave", () =>
      HttpResponse.json(
        {
          title: "Invalid request",
          detail: "1 other active account(s) are in this workspace and you are its only professor",
        },
        { status: 422 },
      ),
    ),
  );

  await screen.findByText("Ecomind Lab");
  await userEvent.click(screen.getByRole("button", { name: /leave/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("only professor");
});

/**
 * The calendar panel lives here because a calendar is a workspace setting, and because it is the
 * only genuinely manual step in the chain that makes a report due.
 */
test("the panel says when no calendar is configured, and saving sends one", async () => {
  const saved: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.get("/api/v1/calendar", () => HttpResponse.json(null)),
    http.get("/api/v1/periods", () => HttpResponse.json([])),
    http.put("/api/v1/calendar", async ({ request }) => {
      saved.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({
        id: "c1",
        workspace_id: "w1",
        version: 1,
        timezone: "Asia/Ho_Chi_Minh",
        meeting_weekday: 0,
        week_start_weekday: 0,
        grace_minutes: 0,
        effective_from: "2026-09-14",
        created_at: "2026-09-01T00:00:00Z",
      });
    }),
  );

  expect(await screen.findByTestId("calendar-state")).toHaveTextContent(/no calendar is configured/i);

  await userEvent.click(screen.getByRole("button", { name: /save calendar/i }));

  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(saved[0]).toMatchObject({ timezone: "Asia/Ho_Chi_Minh", meeting_weekday: 0 });
});

test("the panel warns that saving writes a new version rather than moving open weeks", async () => {
  renderPage();
  server.use(
    http.get("/api/v1/calendar", () => HttpResponse.json(null)),
    http.get("/api/v1/periods", () => HttpResponse.json([])),
  );

  await screen.findByTestId("calendar-panel");

  expect(
    screen.getByText(/Weeks that are already open keep the deadline they were created with/i),
  ).toBeInTheDocument();
});
