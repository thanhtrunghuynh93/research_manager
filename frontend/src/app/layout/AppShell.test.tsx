/** The header: who you are, how the page looks, and the way out. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { AppShell } from "@/app/layout/AppShell";
import "@/lib/i18n";
import { applyTheme, initialTheme } from "@/lib/theme";
import { server } from "@/test/setup";

function renderShell(role: "prof" | "student" = "prof") {
  server.use(
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({
        id: "u1",
        email: "prof@example.edu",
        role,
        display_name: "Prof Demo",
        workspace_id: "w1",
      }),
    ),
    http.get("/api/v1/workspaces", () =>
      HttpResponse.json([
        { id: "w1", name: "Ecomind Lab", timezone: "UTC", access_epoch: 1, owner_id: "u1" },
        { id: "w2", name: "Vision Lab", timezone: "UTC", access_epoch: 1, owner_id: "u1" },
      ]),
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

afterEach(() => {
  document.documentElement.classList.remove("dark");
  localStorage.removeItem("rm.theme");
});

test("greets the signed-in user by name", async () => {
  renderShell();

  expect(await screen.findByTestId("greeting")).toHaveTextContent("Hello Prof Demo");
});

test("the theme toggle flips the class the whole palette hangs off", async () => {
  // main.tsx does this before the first paint; the shell only labels the control, so a test that
  // skips it would be toggling against a document no reader ever sees.
  applyTheme(initialTheme());
  renderShell();
  expect(document.documentElement).toHaveClass("dark");

  await userEvent.click(screen.getByTestId("theme-toggle"));

  await waitFor(() => expect(document.documentElement).not.toHaveClass("dark"));
  // And back, so it is a toggle rather than a one-way switch.
  await userEvent.click(screen.getByTestId("theme-toggle"));
  await waitFor(() => expect(document.documentElement).toHaveClass("dark"));
});

test("offers no language switcher", async () => {
  renderShell();
  await screen.findByTestId("greeting");

  expect(screen.queryByRole("button", { name: /^(vi|en)$/i })).not.toBeInTheDocument();
});

test("names the workspace every screen below is showing", async () => {
  // A professor moves between workspaces (ADR 0014), so the overview, the roll and the assistant
  // all change underneath this header. It is the one place that says which one they are in.
  renderShell("prof");

  await waitFor(() =>
    expect(screen.getByTestId("current-workspace")).toHaveTextContent("Ecomind Lab"),
  );
});

test("the professor is offered Projects, which is how UI-03 becomes reachable", async () => {
  // Nav mirrors the guard: until `/projects` existed, the project workspace had no inbound link
  // from anywhere in the app.
  renderShell();

  await screen.findByTestId("greeting");

  expect(screen.getByRole("link", { name: /^projects$/i })).toHaveAttribute("href", "/projects");
});

test("a student is offered their own progress, and never the professor's screens", async () => {
  server.use(
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({
        id: "s1",
        role: "student",
        email: "an@example.edu",
        display_name: "An Nguyen",
        workspace_id: "w1",
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await screen.findByTestId("greeting");

  expect(screen.getByRole("link", { name: /my progress/i })).toHaveAttribute("href", "/me/profile");
  expect(screen.queryByRole("link", { name: /^projects$/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /^people$/i })).not.toBeInTheDocument();
});
