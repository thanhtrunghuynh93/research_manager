import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { LoginPage } from "@/features/auth/pages/LoginPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("signs in with an email and password", async () => {
  const submitted: unknown[] = [];
  server.use(
    http.post("/api/v1/auth/login", async ({ request }) => {
      submitted.push(await request.json());
      return HttpResponse.json({ id: "u1", email: "prof@example.edu", role: "prof" });
    }),
  );
  renderPage();

  await userEvent.type(screen.getByLabelText(/email/i), "prof@example.edu");
  await userEvent.type(screen.getByLabelText(/password/i), "a long enough password");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

  await waitFor(() =>
    expect(submitted).toEqual([
      { email: "prof@example.edu", password: "a long enough password" },
    ]),
  );
});

test("shows the problem detail when the credentials are rejected", async () => {
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json(
        {
          type: "about:blank",
          title: "Authentication required",
          status: 401,
          detail: "invalid email or password",
        },
        { status: 401 },
      ),
    ),
  );
  renderPage();

  await userEvent.type(screen.getByLabelText(/email/i), "prof@example.edu");
  await userEvent.type(screen.getByLabelText(/password/i), "wrong");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

  expect(await screen.findByRole("alert")).toHaveTextContent("invalid email or password");
});

test("does not say whether the address exists", async () => {
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json(
        { title: "Authentication required", status: 401, detail: "invalid email or password" },
        { status: 401 },
      ),
    ),
  );
  renderPage();

  await userEvent.type(screen.getByLabelText(/email/i), "nobody@example.edu");
  await userEvent.type(screen.getByLabelText(/password/i), "whatever it is");
  await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

  const alert = await screen.findByRole("alert");
  expect(alert).not.toHaveTextContent("nobody@example.edu");
});
