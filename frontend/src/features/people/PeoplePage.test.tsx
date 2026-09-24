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

const WORKSPACE = {
  id: "w1",
  name: "Ecomind Lab",
  timezone: "Asia/Ho_Chi_Minh",
  access_epoch: 1,
  owner_id: "p1",
  archived_at: null,
};

function renderPeople(users: unknown[], extra: Parameters<typeof server.use> = []) {
  server.use(
    // `extra` first: msw takes the first handler that matches, so a test's own workspace list has
    // to come before the single-workspace default below or it would never be reached.
    ...extra,
    http.get("/api/v1/auth/me", () => HttpResponse.json(PROF)),
    http.get("/api/v1/users", () => HttpResponse.json({ items: users, next_cursor: null })),
    // The page names the workspace it is showing, and offers the others as move destinations.
    http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE])),
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
  expect(within(screen.getByTestId("professors-w1")).getByText("Prof Le")).toBeInTheDocument();
  expect(within(screen.getByTestId("students-w1")).getByText("An Nguyen")).toBeInTheDocument();
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

  const professors = screen.getByTestId("professors-w1");
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
  await userEvent.click(screen.getByRole("button", { name: /^send invitation$/i }));

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
    http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE])),
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

const OTHER_WORKSPACE = { ...WORKSPACE, id: "w2", name: "Vision Lab" };

test("names no workspace when there is only one to be in", async () => {
  renderPeople([PROF, user()]);

  await screen.findByText("An Nguyen");
  expect(screen.queryByTestId("person-workspace")).not.toBeInTheDocument();
});

test("offers a destination for a student who has not started work", async () => {
  const moved: unknown[] = [];
  renderPeople(
    [PROF, user()],
    [
      http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE, OTHER_WORKSPACE])),
      http.post("/api/v1/users/:id/workspace", async ({ request, params }) => {
        const body = (await request.json()) as Record<string, unknown>;
        moved.push({ id: params.id, ...body });
        return HttpResponse.json(user({ workspace_id: "w2" }));
      }),
    ],
  );

  const select = await screen.findByLabelText(/move to/i);
  await userEvent.selectOptions(select, "w2");

  await waitFor(() => expect(moved).toEqual([{ id: "s1", workspace_id: "w2" }]));
});

test("shows the API's reason when a student has already started", async () => {
  renderPeople(
    [PROF, user()],
    [
      http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE, OTHER_WORKSPACE])),
      http.post("/api/v1/users/:id/workspace", () =>
        HttpResponse.json(
          { title: "Invalid request", detail: "this student has already done work" },
          { status: 422 },
        ),
      ),
    ],
  );

  await userEvent.selectOptions(await screen.findByLabelText(/move to/i), "w2");

  expect(await screen.findByRole("alert")).toHaveTextContent(/already done work/i);
});

test("offers nowhere to move to when there is only one workspace", async () => {
  renderPeople([PROF, user()]);

  await screen.findByText("An Nguyen");
  expect(screen.queryByLabelText(/move to/i)).not.toBeInTheDocument();
});

test("shows only the workspace being worked in, however many the professor belongs to", async () => {
  // ADR 0020: the API returns the roll of the workspace in the header, and the page shows that
  // roll alone — no section per workspace, no empty ones for the others.
  renderPeople(
    [PROF, user()],
    [http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE, OTHER_WORKSPACE]))],
  );

  await screen.findByText("An Nguyen");

  expect(within(screen.getByTestId("students-w1")).getByText("An Nguyen")).toBeInTheDocument();
  expect(screen.queryByTestId("students-w2")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "Vision Lab" })).not.toBeInTheDocument();
});

test("lists a colleague who belongs here while working in another workspace", async () => {
  // The roll is keyed by membership, and `workspace_id` is only where someone is working, so
  // grouping by it would drop a colleague the API had just returned for this workspace.
  const colleague = user({
    id: "p2",
    role: "prof",
    workspace_id: "w2",
    email: "hoa@example.edu",
    display_name: "Prof Hoa",
  });
  renderPeople(
    [PROF, colleague, user()],
    [http.get("/api/v1/workspaces", () => HttpResponse.json([WORKSPACE, OTHER_WORKSPACE]))],
  );

  await screen.findByText("Prof Hoa");
  expect(within(screen.getByTestId("professors-w1")).getByText("Prof Hoa")).toBeInTheDocument();
});

test("an invitation can be sent again, and only to someone who has not accepted one", async () => {
  // `POST /users/invitations` has always reissued for an address still in `invited`; what was
  // missing was the button. It carries the row's own workspace, because the roll spans several.
  const sent: Record<string, unknown>[] = [];
  const invited = user({ id: "s2", email: "waiting@example.edu", display_name: "Waiting", state: "invited" });
  renderPeople([PROF, user(), invited], [
    http.post("/api/v1/users/invitations", async ({ request }) => {
      sent.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ email: "waiting@example.edu" }, { status: 201 });
    }),
  ]);

  await screen.findByText("Waiting");
  expect(screen.queryByTestId("resend-s1"), "an accepted account has no link to reissue").toBeNull();

  await userEvent.click(screen.getByTestId("resend-s2"));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toEqual({ email: "waiting@example.edu", role: "student", workspace_id: "w1" });

  // The button carries its own result, so the row needs no sentence beside it — and what
  // reissuing costs is said once, under the invite form.
  expect(await screen.findByText(/invitation resent/i)).toBeInTheDocument();
  expect(screen.getByText(/stops the earlier one working/i)).toBeInTheDocument();
});

test("a colleague still waiting on their invitation can be sent another", async () => {
  // The professors' rows carried no controls at all, which was right for an accepted colleague
  // (ADR 0011 gives a professor no authority over another) and wrong for one who never got in.
  const sent: Record<string, unknown>[] = [];
  const colleague = user({ id: "p2", role: "prof", email: "new.prof@example.edu", display_name: "Dr Tran", state: "invited" });
  renderPeople([PROF, colleague], [
    http.post("/api/v1/users/invitations", async ({ request }) => {
      sent.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ email: "new.prof@example.edu" }, { status: 201 });
    }),
  ]);

  await screen.findByText("Dr Tran");
  expect(screen.queryByTestId("resend-p1"), "the accepted professor keeps no controls").toBeNull();

  await userEvent.click(screen.getByTestId("resend-p2"));
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toMatchObject({ role: "prof" });
});
