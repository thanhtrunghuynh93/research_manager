/**
 * AUTH-01 / ADR 0011: the roll a professor manages, and the boundaries drawn on it.
 *
 * Two of these assert the absence of something — no role control, no button on a colleague. They
 * are the point of the screen rather than an oversight: the API refuses both, and a control that
 * always fails is worse than no control.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { PeoplePage } from "@/features/people/pages/PeoplePage";
import "@/lib/i18n";
import { server } from "@/test/setup";

function user(overrides: Record<string, unknown> = {}) {
  return {
    id: "s1",
    workspace_id: "w1",
    role: "student",
    email: "an@example.edu",
    display_name: "An Nguyen",
    state: "active",
    deactivated_at: null,
    created_at: "2026-09-01T02:00:00Z",
    ...overrides,
  };
}

const PROF = user({ id: "p1", role: "prof", email: "prof@example.edu", display_name: "Prof Le" });

function renderPeople(users: unknown[], extra: Parameters<typeof server.use> = []) {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(PROF)),
    http.get("/api/v1/users", () => HttpResponse.json({ items: users, next_cursor: null })),
    ...extra,
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PeoplePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("separates the professors from the students", async () => {
  renderPeople([PROF, user()]);

  await screen.findByText("An Nguyen");
  expect(within(screen.getByTestId("professors")).getByText("Prof Le")).toBeInTheDocument();
  expect(within(screen.getByTestId("students")).getByText("An Nguyen")).toBeInTheDocument();
});

test("offers no control that would change a role", async () => {
  renderPeople([PROF, user()]);
  await screen.findByText("An Nguyen");

  // A role is fixed at acceptance (ADR 0011), so the only place a role is chosen is the invitation.
  const selects = screen.getAllByRole("combobox");
  expect(selects).toHaveLength(1);
  expect(selects[0]).toHaveValue("student");
});

test("gives a colleague no buttons", async () => {
  // ADR 0011: professors are co-equal, so one cannot suspend or remove another from this screen.
  // The row used to carry a note saying so; the absence of the buttons is the part that matters
  // and is what this asserts.
  renderPeople([PROF, user({ id: "p2", role: "prof", display_name: "Prof Tran" })]);
  await screen.findByText("Prof Tran");

  const professors = screen.getByTestId("professors");
  expect(within(professors).queryByRole("button")).not.toBeInTheDocument();
});

test("asks again before removing a student, and names the consequence", async () => {
  const removed: string[] = [];
  renderPeople(
    [PROF, user()],
    [
      http.post("/api/v1/users/:id/remove", ({ params }) => {
        removed.push(params.id as string);
        return HttpResponse.json(user({ state: "deactivated" }));
      }),
    ],
  );
  await screen.findByText("An Nguyen");

  await userEvent.click(screen.getByRole("button", { name: /remove from workspace/i }));

  const confirm = screen.getByTestId("confirm-s1");
  expect(confirm).toHaveTextContent(/cannot be undone/i);
  expect(removed).toEqual([]); // arming the confirmation must not have removed anyone

  await userEvent.click(within(confirm).getByRole("button", { name: /^remove$/i }));

  await waitFor(() => expect(removed).toEqual(["s1"]));
});

test("cancelling the confirmation removes nobody", async () => {
  const removed: string[] = [];
  renderPeople(
    [PROF, user()],
    [
      http.post("/api/v1/users/:id/remove", ({ params }) => {
        removed.push(params.id as string);
        return HttpResponse.json(user({ state: "deactivated" }));
      }),
    ],
  );
  await screen.findByText("An Nguyen");

  await userEvent.click(screen.getByRole("button", { name: /remove from workspace/i }));
  await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

  expect(screen.queryByTestId("confirm-s1")).not.toBeInTheDocument();
  expect(removed).toEqual([]);
});

test("suspension is a separate act from removal", async () => {
  const calls: string[] = [];
  renderPeople(
    [PROF, user()],
    [
      http.post("/api/v1/users/:id/deactivate", () => {
        calls.push("deactivate");
        return HttpResponse.json(user({ state: "deactivated" }));
      }),
    ],
  );
  await screen.findByText("An Nguyen");

  await userEvent.click(screen.getByRole("button", { name: /suspend access/i }));

  // No confirmation: suspension is reversible, and `Restore access` is the undo.
  await waitFor(() => expect(calls).toEqual(["deactivate"]));
});

test("a closed account offers restoration instead", async () => {
  renderPeople([PROF, user({ state: "deactivated", deactivated_at: "2026-09-10T02:00:00Z" })]);
  await screen.findByText("An Nguyen");

  expect(screen.getByRole("button", { name: /restore access/i })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /remove from workspace/i })).not.toBeInTheDocument();
});

test("confirms an invitation by the address it went to, never by a link", async () => {
  renderPeople(
    [PROF],
    [
      http.post("/api/v1/users/invitations", async ({ request }) => {
        const body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            id: "i1",
            email: body.email,
            role: body.role,
            expires_at: "2026-09-21T02:00:00Z",
            accepted_at: null,
            created_at: "2026-09-14T02:00:00Z",
          },
          { status: 201 },
        );
      }),
    ],
  );

  await userEvent.type(screen.getByLabelText(/email/i), "new@example.edu");
  await userEvent.click(screen.getByRole("button", { name: /send invitation/i }));

  expect(await screen.findByRole("status")).toHaveTextContent("new@example.edu");
});

test("a refusal from the API is shown rather than swallowed", async () => {
  renderPeople(
    [PROF, user()],
    [
      http.post("/api/v1/users/:id/remove", () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Forbidden",
            status: 403,
            detail: "a professor account is removed through the break-glass procedure",
          },
          { status: 403 },
        ),
      ),
    ],
  );
  await screen.findByText("An Nguyen");

  await userEvent.click(screen.getByRole("button", { name: /remove from workspace/i }));
  await userEvent.click(
    within(screen.getByTestId("confirm-s1")).getByRole("button", { name: /^remove$/i }),
  );

  expect(await screen.findByRole("alert")).toHaveTextContent(/break-glass/i);
});

test("follows the cursor when the roll is longer than a page", async () => {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json(PROF)),
    http.get("/api/v1/users", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      return cursor
        ? HttpResponse.json({ items: [user({ id: "s2", display_name: "Bao Tran" })] })
        : HttpResponse.json({ items: [PROF, user()], next_cursor: "next" });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PeoplePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText("An Nguyen");

  await userEvent.click(screen.getByRole("button", { name: /show more/i }));

  expect(await screen.findByText("Bao Tran")).toBeInTheDocument();
});
