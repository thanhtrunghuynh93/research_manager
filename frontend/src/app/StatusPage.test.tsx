import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { StatusPage } from "@/app/StatusPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StatusPage />
    </QueryClientProvider>,
  );
}

test("shows each readiness check", async () => {
  server.use(
    http.get("/api/readyz", () =>
      HttpResponse.json(
        { status: "degraded", checks: { database: "ok", object_storage: "fail" } },
        { status: 503 },
      ),
    ),
  );
  renderPage();
  expect(await screen.findByText("database")).toBeInTheDocument();
  expect(screen.getByText("object_storage")).toBeInTheDocument();
  expect(screen.getByText("fail")).toBeInTheDocument();
});
