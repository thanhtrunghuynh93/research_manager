/**
 * AUTH-01: the page an invitation link lands on.
 *
 * Until this existed the backend endpoint was reachable only by hand: the professor could issue an
 * invitation nobody could act on. The cases below are the ones that decide whether a real person
 * gets in — a truncated link, a mistyped password, an expired token — rather than the happy path
 * alone.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AcceptInvitationPage } from "@/features/auth/pages/AcceptInvitationPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PASSWORD = "correct horse battery staple";

function renderAccept(search: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/accept-invitation${search}`]}>
        <Routes>
          <Route path="/accept-invitation" element={<AcceptInvitationPage />} />
          <Route path="/me" element={<p>student home</p>} />
          <Route path="/overview" element={<p>professor overview</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function accepted(role: "student" | "prof" = "student") {
  return {
    id: "u1",
    workspace_id: "w1",
    role,
    email: "new@example.edu",
    display_name: "An Nguyen",
    state: "active",
    deactivated_at: null,
    created_at: "2026-09-14T02:00:00Z",
  };
}

test("sets the password and lands on the home for the new account's role", async () => {
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.post("/api/v1/auth/accept-invitation", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(accepted());
    }),
  );
  renderAccept("?token=tok-123");

  await userEvent.type(screen.getByLabelText(/^password$/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /set password and continue/i }));

  expect(await screen.findByText("student home")).toBeInTheDocument();
  expect(sent).toEqual({ token: "tok-123", password: PASSWORD });
});

test("an invited professor lands on the professor overview instead", async () => {
  server.use(
    http.post("/api/v1/auth/accept-invitation", () => HttpResponse.json(accepted("prof"))),
  );
  renderAccept("?token=tok-123");

  await userEvent.type(screen.getByLabelText(/^password$/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /set password and continue/i }));

  expect(await screen.findByText("professor overview")).toBeInTheDocument();
});

test("sends the chosen display name when one is given", async () => {
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.post("/api/v1/auth/accept-invitation", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json(accepted());
    }),
  );
  renderAccept("?token=tok-123");

  await userEvent.type(screen.getByLabelText(/your name/i), "An Nguyen");
  await userEvent.type(screen.getByLabelText(/^password$/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /set password and continue/i }));

  await waitFor(() => expect(sent).toHaveProperty("display_name", "An Nguyen"));
});

test("refuses to submit two passwords that differ", async () => {
  let called = false;
  server.use(
    http.post("/api/v1/auth/accept-invitation", () => {
      called = true;
      return HttpResponse.json(accepted());
    }),
  );
  renderAccept("?token=tok-123");

  await userEvent.type(screen.getByLabelText(/^password$/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), "something else entirely");

  expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
  expect(screen.getByRole("button", { name: /set password and continue/i })).toBeDisabled();
  expect(called).toBe(false);
});

test("a link with no token says so instead of offering a form", async () => {
  renderAccept("");

  expect(await screen.findByRole("alert")).toHaveTextContent(/no invitation token/i);
  expect(screen.queryByLabelText(/^password$/i)).not.toBeInTheDocument();
});

test("shows what the API said about a spent or expired token", async () => {
  server.use(
    http.post("/api/v1/auth/accept-invitation", () =>
      HttpResponse.json(
        {
          type: "about:blank",
          title: "Unprocessable Entity",
          status: 422,
          detail: "invitation token is invalid, used, or expired",
        },
        { status: 422 },
      ),
    ),
  );
  renderAccept("?token=spent");

  await userEvent.type(screen.getByLabelText(/^password$/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /set password and continue/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid, used, or expired/i);
});

test("never puts the token in an editable field", async () => {
  renderAccept("?token=tok-123");

  // The token is the credential. Rendering it into the form would put it in the page, in
  // autofill, and in any screenshot of a person being helped through the screen.
  for (const field of screen.getAllByRole("textbox")) {
    expect(field).not.toHaveValue("tok-123");
  }
});
