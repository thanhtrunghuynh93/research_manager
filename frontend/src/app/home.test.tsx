/**
 * UI-01/UI-02: `/overview` is the professor overview and `/me` the student one, so "home" is not a
 * single page. Sending everyone to `/me` showed the professor a student's screen — the obligations
 * there are the whole workspace's, so they read as the professor's own backlog, above a weekly
 * submission flow the API refuses with 422.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";

import { homeFor } from "@/app/home";
import { HomeRedirect } from "@/app/HomeRedirect";
import { RequireAuth } from "@/app/RequireAuth";
import "@/lib/i18n";
import { server } from "@/test/setup";

test("home is the professor overview for a professor and the student one for a student", () => {
  expect(homeFor("prof")).toBe("/overview");
  expect(homeFor("student")).toBe("/me");
});

function renderAt(path: string, role: "prof" | "student") {
  server.use(
    http.get("/api/v1/auth/me", () => HttpResponse.json({ id: "u1", email: "a@b.edu", role })),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/" element={<HomeRedirect />} />
            <Route path="*" element={<HomeRedirect />} />
          </Route>
          <Route element={<RequireAuth role="student" />}>
            <Route path="/me" element={<div>student overview</div>} />
          </Route>
          <Route element={<RequireAuth role="prof" />}>
            <Route path="/overview" element={<div>professor overview</div>} />
          </Route>
          <Route path="/login" element={<Navigate to="/login-page" replace />} />
          <Route path="/login-page" element={<div>sign in</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test('a professor at "/" lands on the professor overview', async () => {
  renderAt("/", "prof");
  await waitFor(() => expect(screen.getByText("professor overview")).toBeInTheDocument());
});

test('a student at "/" lands on the student overview', async () => {
  renderAt("/", "student");
  await waitFor(() => expect(screen.getByText("student overview")).toBeInTheDocument());
});

test("a professor who opens the student overview is sent to their own, not bounced in a loop", async () => {
  renderAt("/me", "prof");
  await waitFor(() => expect(screen.getByText("professor overview")).toBeInTheDocument());
});

test("an unknown path lands on the caller's own home", async () => {
  renderAt("/no-such-page", "prof");
  await waitFor(() => expect(screen.getByText("professor overview")).toBeInTheDocument());
});
