/** The header: who you are, how the page looks, and the way out. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "@/app/layout/AppShell";
import "@/lib/i18n";
import { server } from "@/test/setup";

function renderShell(role: "prof" | "student" = "prof") {
  server.use(
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({ id: "u1", email: "prof@example.edu", role, display_name: "Prof Demo" }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => document.documentElement.classList.remove("dark"));

test("greets the signed-in user by name", async () => {
  renderShell();

  expect(await screen.findByTestId("greeting")).toHaveTextContent("Hello Prof Demo");
});

test("the theme toggle flips the class the whole palette hangs off", async () => {
  renderShell();
  expect(document.documentElement).not.toHaveClass("dark");

  await userEvent.click(screen.getByTestId("theme-toggle"));

  await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
  // And back, so it is a toggle rather than a one-way switch.
  await userEvent.click(screen.getByTestId("theme-toggle"));
  await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));
});

test("offers no language switcher", async () => {
  renderShell();
  await screen.findByTestId("greeting");

  expect(screen.queryByRole("button", { name: /^(vi|en)$/i })).not.toBeInTheDocument();
});
