/**
 * ADR 0015: belonging is plural and working in is singular, so a row is one of three things —
 * where you are, one you belong to but are not in, or one you own and could join.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

  await screen.findByTestId("workspace-list");
  const [here, elsewhere] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");

  expect(within(here!).getByText(/working here/i)).toBeInTheDocument();
  expect(within(here!).getByRole("button", { name: /^leave$/i })).toBeInTheDocument();
  expect(within(here!).queryByRole("button", { name: /^join$/i })).not.toBeInTheDocument();

  expect(within(elsewhere!).getByRole("button", { name: /^join$/i })).toBeInTheDocument();
  expect(within(elsewhere!).queryByRole("button", { name: /^leave$/i })).not.toBeInTheDocument();
});

test("a workspace you belong to but are not in offers leave, and no way to go there", async () => {
  // Belonging is plural and working in is singular (ADR 0015), so this row is neither the one you
  // are in nor one you would join: it is one you could give up. Going to it is the header's
  // switcher — see WorkspaceSwitcher.test.tsx — so this screen no longer offers it.
  renderPage([HERE, { ...ELSEWHERE, joined: true }]);

  await screen.findByText("Vision Lab");
  const [, other] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");

  expect(within(other!).getByRole("button", { name: /^leave$/i })).toBeInTheDocument();
  expect(within(other!).queryByRole("button", { name: /work here/i })).not.toBeInTheDocument();
  expect(within(other!).queryByText(/working here/i)).not.toBeInTheDocument();
});

test("archiving is not offered for the workspace you are in", async () => {
  // You are the account standing in the way of it being empty, so the button could only refuse.
  renderPage();

  await screen.findByTestId("workspace-list");
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

  await screen.findByTestId("workspace-list");
  await userEvent.click(screen.getByRole("button", { name: /leave/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("only professor");
});

const CALENDAR = {
  id: "c1",
  workspace_id: "w1",
  version: 1,
  timezone: "Asia/Ho_Chi_Minh",
  meeting_weekday: 0,
  week_start_weekday: 0,
  grace_minutes: 0,
  effective_from: "2026-09-14",
  created_at: "2026-09-01T00:00:00Z",
};

function period(start: string, end: string, deadline: string) {
  return {
    id: `p-${start}`,
    workspace_id: "w1",
    local_start: start,
    local_end: end,
    start_utc: `${start}T00:00:00Z`,
    end_utc: `${end}T00:00:00Z`,
    meeting_date: end,
    deadline_utc: deadline,
  };
}

test("the workspace being worked in comes first, and its owner can rename it", async () => {
  const renamed: unknown[] = [];
  renderPage();
  server.use(
    http.patch("/api/v1/workspaces/w1", async ({ request }) => {
      renamed.push(await request.json());
      return HttpResponse.json({ ...HERE, name: "Ecomind Research" });
    }),
  );

  const card = await screen.findByTestId("this-workspace");
  expect(within(card).getByTestId("workspace-name")).toHaveTextContent("Ecomind Lab");

  await userEvent.click(within(card).getByRole("button", { name: /rename/i }));
  const input = within(card).getByLabelText(/name/i);
  await userEvent.clear(input);
  await userEvent.type(input, "Ecomind Research");
  await userEvent.click(within(card).getByRole("button", { name: /^save$/i }));

  await waitFor(() => expect(renamed).toEqual([{ name: "Ecomind Research" }]));
});

test("a colleague who does not own the workspace gets no rename button", async () => {
  // ADR 0012: renaming is the owner's, and a button the API always refuses is worse than none.
  renderPage([{ ...HERE, owner_id: "someone-else" }, ELSEWHERE]);

  const card = await screen.findByTestId("this-workspace");
  expect(within(card).queryByRole("button", { name: /rename/i })).not.toBeInTheDocument();
});

test("archiving asks once more before it happens", async () => {
  const archived: string[] = [];
  renderPage();
  server.use(
    http.post("/api/v1/workspaces/:id/archive", ({ params }) => {
      archived.push(String(params.id));
      return HttpResponse.json({ ...ELSEWHERE, archived_at: "2026-09-24T00:00:00Z" });
    }),
  );

  await screen.findByTestId("workspace-list");
  const [, elsewhere] = within(screen.getByTestId("workspace-list")).getAllByRole("listitem");
  await userEvent.click(within(elsewhere!).getByRole("button", { name: /archive/i }));

  expect(archived).toEqual([]);
  expect(elsewhere).toHaveTextContent(/archive it\?/i);
  await userEvent.click(within(elsewhere!).getByRole("button", { name: /^archive$/i }));
  await waitFor(() => expect(archived).toEqual(["w2"]));
});

test("creating a workspace is folded away until asked for", async () => {
  renderPage();

  await screen.findByTestId("workspace-list");
  expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /new workspace/i }));
  expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument();
});

test("model spend is not on this screen", async () => {
  renderPage();

  await screen.findByTestId("workspace-list");
  expect(screen.queryByText(/model spend/i)).not.toBeInTheDocument();
});

test("with no schedule it says why nothing is due, and saving starts the chosen week", async () => {
  const saved: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.put("/api/v1/calendar", async ({ request }) => {
      saved.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json(CALENDAR);
    }),
  );

  expect(await screen.findByTestId("calendar-state")).toHaveTextContent(/no weekly schedule yet/i);
  // No "open weeks" step any more: saving opens them and makes this week's reports due.
  expect(screen.queryByRole("button", { name: /open weeks/i })).not.toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText(/week starts on/i), "1");
  await userEvent.click(screen.getByLabelText(/next week/i));
  await userEvent.click(screen.getByRole("button", { name: /save schedule/i }));

  await waitFor(() => expect(saved).toHaveLength(1));
  const sent = saved[0]!;
  expect(sent).toMatchObject({ week_start_weekday: 1, timezone: "Asia/Ho_Chi_Minh" });
  // The next Tuesday after the start of this week: a Tuesday, and in the future.
  const [y, m, d] = String(sent.effective_from).split("-").map(Number);
  expect(new Date(Date.UTC(y!, m! - 1, d!)).getUTCDay()).toBe(2);
});

test("a schedule reads as a sentence and the weeks it produces, with an edit behind a button", async () => {
  const saved: Record<string, unknown>[] = [];
  renderPage();
  server.use(
    http.get("/api/v1/calendar", () => HttpResponse.json(CALENDAR)),
    http.get("/api/v1/periods", () =>
      HttpResponse.json([
        period("2999-01-05", "2999-01-11", "2999-01-11T16:59:00Z"),
        period("2999-01-12", "2999-01-18", "2999-01-18T16:59:00Z"),
      ]),
    ),
    http.put("/api/v1/calendar", async ({ request }) => {
      saved.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ ...CALENDAR, version: 2, meeting_weekday: 2 });
    }),
  );

  expect(await screen.findByTestId("calendar-state")).toHaveTextContent(
    /Each week runs Monday to Sunday\. Reports are due Sunday at 23:59, the evening before your Monday meeting/,
  );
  expect(within(await screen.findByTestId("upcoming-weeks")).getAllByRole("listitem")).toHaveLength(
    2,
  );
  expect(screen.queryByRole("button", { name: /save schedule/i })).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /edit schedule/i }));
  // An edit has no "first week" to choose: it applies to every week that has not begun.
  expect(screen.queryByText(/first week/i)).not.toBeInTheDocument();
  expect(screen.getByText(/current week keeps its deadline/i)).toBeInTheDocument();

  await userEvent.selectOptions(screen.getByLabelText(/meeting day/i), "2");
  await userEvent.click(screen.getByRole("button", { name: /save schedule/i }));
  await waitFor(() => expect(saved).toHaveLength(1));
  expect(saved[0]).toMatchObject({ meeting_weekday: 2, week_start_weekday: 0 });
});
