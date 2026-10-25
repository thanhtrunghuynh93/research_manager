import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { ConnectPage } from "@/features/connect/pages/ConnectPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

const QUERY =
  "?client_id=abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcb&response_type=code&code_challenge=c&code_challenge_method=S256&state=s";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/connect${QUERY}`]}>
        <ConnectPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("names the client and the workspace, and sends the request back unchanged on Allow", async () => {
  const posted: unknown[] = [];
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  server.use(
    http.post("/api/v1/oauth/consent", () =>
      HttpResponse.json({ client_name: "Claude", scope: "rms:read", workspace_name: "Vision Lab" }),
    ),
    http.post("/api/v1/oauth/authorize", async ({ request }) => {
      posted.push(await request.json());
      return HttpResponse.json({ redirect_to: "https://claude.ai/cb?code=x&state=s" });
    }),
  );

  renderPage();
  expect(await screen.findByRole("heading", { name: /Connect Claude/ })).toBeInTheDocument();
  expect(screen.getByText(/Vision Lab/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Allow" }));

  await waitFor(() => expect(assign).toHaveBeenCalledWith("https://claude.ai/cb?code=x&state=s"));
  expect(posted[0]).toMatchObject({
    client_id: "abc",
    redirect_uri: "https://claude.ai/cb",
    code_challenge_method: "S256",
  });
  vi.unstubAllGlobals();
});

test("a request the API rejects shows no Allow button", async () => {
  server.use(
    http.post("/api/v1/oauth/consent", () =>
      HttpResponse.json(
        { type: "about:blank", title: "Bad request", status: 400, detail: "unknown client" },
        { status: 400 },
      ),
    ),
  );

  renderPage();

  expect(await screen.findByRole("alert")).toHaveTextContent("cannot be completed");
  expect(screen.queryByRole("button", { name: "Allow" })).not.toBeInTheDocument();
});
