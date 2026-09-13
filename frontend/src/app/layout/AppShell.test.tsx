/** The header: who you are, how the page looks, and the way out. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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

test("offers no language switcher", async () => {
  renderShell();
  await screen.findByText("Sign out");

  expect(screen.queryByRole("button", { name: /^(vi|en)$/i })).not.toBeInTheDocument();
});
