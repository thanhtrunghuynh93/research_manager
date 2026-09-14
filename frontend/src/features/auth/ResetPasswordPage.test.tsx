/**
 * AUTH-01: account recovery, the half a person actually touches.
 *
 * The property worth protecting here is that neither screen tells an anonymous visitor whether an
 * address has an account — the API is careful about that, and a helpful message on the client
 * would give it away again.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { LoginPage } from "@/features/auth/pages/LoginPage";
import { ResetPasswordPage } from "@/features/auth/pages/ResetPasswordPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const PASSWORD = "a new long enough password";

function renderAt(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("sets the new password and sends the person to sign in with it", async () => {
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.post("/api/v1/auth/password-reset/confirm", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return new HttpResponse(null, { status: 204 });
    }),
  );
  renderAt("/reset-password?token=tok-123");

  await userEvent.type(screen.getByLabelText(/new password/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /save password/i }));

  // No session follows a reset: it may have been requested from another device.
  expect(await screen.findByRole("status")).toHaveTextContent(/your password is set/i);
  expect(sent).toEqual({ token: "tok-123", password: PASSWORD });
});

test("refuses two passwords that differ", async () => {
  renderAt("/reset-password?token=tok-123");

  await userEvent.type(screen.getByLabelText(/new password/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), "something else");

  expect(await screen.findByRole("alert")).toHaveTextContent(/do not match/i);
  expect(screen.getByRole("button", { name: /save password/i })).toBeDisabled();
});

test("a link with no token offers a way to ask for a new one", async () => {
  renderAt("/reset-password");

  expect(await screen.findByRole("alert")).toHaveTextContent(/no recovery token/i);
  expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
});

test("shows what the API said about a spent or expired token", async () => {
  server.use(
    http.post("/api/v1/auth/password-reset/confirm", () =>
      HttpResponse.json(
        {
          type: "about:blank",
          title: "Unprocessable Entity",
          status: 422,
          detail: "reset token is invalid, used, or expired",
        },
        { status: 422 },
      ),
    ),
  );
  renderAt("/reset-password?token=spent");

  await userEvent.type(screen.getByLabelText(/new password/i), PASSWORD);
  await userEvent.type(screen.getByLabelText(/password again/i), PASSWORD);
  await userEvent.click(screen.getByRole("button", { name: /save password/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent(/invalid, used, or expired/i);
});

test("the login page can ask for a recovery link", async () => {
  let sent: Record<string, unknown> | null = null;
  server.use(
    http.post("/api/v1/auth/password-reset", async ({ request }) => {
      sent = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ status: "accepted" }, { status: 202 });
    }),
  );
  renderAt("/login");

  await userEvent.click(screen.getByRole("button", { name: /forgot your password/i }));
  await userEvent.type(screen.getByLabelText(/your email/i), "an@example.edu");
  await userEvent.click(screen.getByRole("button", { name: /send a recovery link/i }));

  expect(await screen.findByRole("status")).toHaveTextContent(/if that address has an account/i);
  expect(sent).toEqual({ email: "an@example.edu" });
});

test("the confirmation never reveals whether the address has an account", async () => {
  server.use(
    http.post("/api/v1/auth/password-reset", () =>
      HttpResponse.json({ status: "accepted" }, { status: 202 }),
    ),
  );
  renderAt("/login");

  await userEvent.click(screen.getByRole("button", { name: /forgot your password/i }));
  await userEvent.type(screen.getByLabelText(/your email/i), "nobody@example.edu");
  await userEvent.click(screen.getByRole("button", { name: /send a recovery link/i }));

  // The wording is conditional on purpose; the API answers identically either way.
  const confirmation = await screen.findByRole("status");
  expect(confirmation).toHaveTextContent(/if that address has an account/i);
  expect(confirmation).not.toHaveTextContent(/no such|not found|unknown/i);
});
