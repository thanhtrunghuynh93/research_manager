/**
 * The header switcher: which workspace every screen below is showing, and the way to another.
 *
 * Switching is joining one you already belong to (ADR 0015), so the menu offers memberships and
 * nothing else — a workspace you own but have left is not somewhere you can be without joining
 * it, and that is `/workspaces`' job.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, useLocation } from "react-router-dom";

import { WorkspaceSwitcher } from "@/features/workspaces/components/WorkspaceSwitcher";
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

const ALSO_MINE = { ...HERE, id: "w2", name: "Vision Lab", timezone: "Europe/Berlin" };
const OWNED_NOT_JOINED = { ...ALSO_MINE, id: "w3", name: "Archive Lab", joined: false };

/** Where the router ended up, so a switch can be shown to land somewhere. */
function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>;
}

function renderSwitcher(workspaces: unknown[], me: Record<string, unknown> = ME) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(me)),
    http.get("/api/v1/workspaces", () => HttpResponse.json(workspaces)),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/people"]}>
        <WorkspaceSwitcher />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("one membership is a name, not a menu", async () => {
  renderSwitcher([HERE, OWNED_NOT_JOINED]);

  const current = await screen.findByTestId("current-workspace");
  expect(current).toHaveTextContent("Ecomind Lab");
  // One choice is not a choice: there is nowhere to switch to without joining first.
  expect(current.tagName).toBe("SPAN");
});

test("several memberships open a menu, and choosing one switches", async () => {
  const joined: string[] = [];
  renderSwitcher([HERE, ALSO_MINE, OWNED_NOT_JOINED]);
  server.use(
    http.post("/api/v1/workspaces/:id/join", ({ params }) => {
      joined.push(params.id as string);
      return HttpResponse.json({ ...ALSO_MINE, joined: true });
    }),
  );

  await userEvent.click(await screen.findByTestId("current-workspace"));
  const menu = screen.getByRole("menu");

  // A workspace owned but left is not somewhere you can be, so it is not on the menu.
  expect(within(menu).queryByText("Archive Lab")).not.toBeInTheDocument();
  expect(within(menu).getByRole("menuitemradio", { name: /ecomind lab/i })).toHaveAttribute(
    "aria-checked",
    "true",
  );

  await userEvent.click(within(menu).getByRole("menuitemradio", { name: /vision lab/i }));
  await waitFor(() => expect(joined).toEqual(["w2"]));

  // And lands on the overview rather than staying on a page that named the other workspace's
  // records — /people was the roll of the workspace just left.
  await waitFor(() => expect(screen.getByTestId("where")).toHaveTextContent("/overview"));
});

test("choosing the workspace you are already in just closes the menu", async () => {
  const joined: string[] = [];
  renderSwitcher([HERE, ALSO_MINE]);
  server.use(
    http.post("/api/v1/workspaces/:id/join", ({ params }) => {
      joined.push(params.id as string);
      return HttpResponse.json(HERE);
    }),
  );

  await userEvent.click(await screen.findByTestId("current-workspace"));
  await userEvent.click(
    within(screen.getByRole("menu")).getByRole("menuitemradio", { name: /ecomind lab/i }),
  );

  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(joined, "no call, and no navigation away from the page you were reading").toEqual([]);
  expect(screen.getByTestId("where")).toHaveTextContent("/people");
});

test("the menu carries the way to the administration screen", async () => {
  renderSwitcher([HERE, ALSO_MINE]);

  await userEvent.click(await screen.findByTestId("current-workspace"));
  expect(screen.getByRole("menuitem", { name: /workspaces and settings/i })).toHaveAttribute(
    "href",
    "/workspaces",
  );
});

test("escape closes it and hands focus back", async () => {
  renderSwitcher([HERE, ALSO_MINE]);

  const trigger = await screen.findByTestId("current-workspace");
  await userEvent.click(trigger);
  expect(screen.getByRole("menu")).toBeInTheDocument();

  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

test("a student has no switcher at all", async () => {
  // `GET /workspaces` is professor-only, and a student has one workspace and no way to leave it.
  renderSwitcher([], { ...ME, role: "student" });

  await waitFor(() => expect(screen.queryByTestId("current-workspace")).not.toBeInTheDocument());
});
