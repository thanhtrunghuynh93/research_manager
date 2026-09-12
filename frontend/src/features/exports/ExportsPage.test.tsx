/** UI-06: the export carries exactly what the professor asked for, over the window they picked. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";

import { ExportsPage } from "@/features/exports/pages/ExportsPage";
import "@/lib/i18n";
import { server } from "@/test/setup";

function renderPage() {
  server.use(
    http.get("/api/v1/exports/kinds", () =>
      HttpResponse.json({
        kinds: ["reports", "assessments", "projects"],
        default: ["reports", "assessments"],
      }),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ExportsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function downloadUrl(): URL {
  const link = screen.getByTestId("download-json") as HTMLAnchorElement;
  return new URL(link.getAttribute("href")!, "http://test");
}

test("starts from the defaults the server named", async () => {
  renderPage();

  await screen.findByRole("checkbox", { name: /reports/i });
  expect(downloadUrl().searchParams.getAll("kinds")).toEqual(["reports", "assessments"]);
});

test("unticking every kind exports nothing, not the defaults again", async () => {
  // "chose nothing" was conflated with "has not chosen", so the last untick silently restored
  // both defaults — the boxes re-ticked themselves and the download carried what was removed.
  renderPage();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("checkbox", { name: /reports/i }));
  await user.click(screen.getByRole("checkbox", { name: /assessments/i }));

  expect(screen.getByRole("checkbox", { name: /reports/i })).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /assessments/i })).not.toBeChecked();
  expect(downloadUrl().searchParams.getAll("kinds")).toEqual([]);
});

test("removing one kind keeps the rest", async () => {
  renderPage();
  const user = userEvent.setup();

  await user.click(await screen.findByRole("checkbox", { name: /reports/i }));

  expect(downloadUrl().searchParams.getAll("kinds")).toEqual(["assessments"]);
});

test("the date window is the workspace's day, not UTC's", async () => {
  // `${date}T00:00:00Z` read a local date as UTC, so in Asia/Ho_Chi_Minh the window ran
  // 07:00 to 07:00 and lost everything filed on the first morning.
  renderPage();
  const user = userEvent.setup();

  await screen.findByRole("checkbox", { name: /reports/i });
  await user.type(screen.getByLabelText(/^from$/i), "2026-09-14");
  await user.type(screen.getByLabelText(/^to$/i), "2026-09-20");

  const params = downloadUrl().searchParams;
  expect(params.get("since")).toBe("2026-09-13T17:00:00.000Z");
  expect(params.get("until")).toBe("2026-09-20T16:59:59.999Z");
});
