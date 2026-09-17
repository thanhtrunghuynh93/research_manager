/**
 * AUTH-03: signing out has to end access to what was on screen, not just to the server.
 *
 * The cache is shared by everyone who uses the browser. Invalidation marks entries stale but
 * leaves them readable, so on a shared machine the next person to sign in saw the previous user's
 * overview and projects until each refetch landed.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { useLogin, useLogout, useSession } from "@/features/auth/queries";
import { server } from "@/test/setup";

const OVERVIEW_KEY = ["overview"];

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(OVERVIEW_KEY, { students: ["someone else's students"] });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

test("signing out removes what the previous user could read", async () => {
  server.use(http.post("/api/v1/auth/logout", () => new HttpResponse(null, { status: 204 })));
  const { client, wrapper } = harness();
  const { result } = renderHook(() => useLogout(), { wrapper });

  result.current.mutate();

  await waitFor(() => expect(client.getQueryData(OVERVIEW_KEY)).toBeUndefined());
});

test("signing in does not inherit whatever the last account left behind", async () => {
  server.use(
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ id: "u2", email: "other@example.edu", role: "student" }),
    ),
  );
  const { client, wrapper } = harness();
  const { result } = renderHook(() => useLogin(), { wrapper });

  result.current.mutate({ email: "other@example.edu", password: "a long enough password" });

  await waitFor(() => expect(client.getQueryData(OVERVIEW_KEY)).toBeUndefined());
});

/**
 * The two tests above read the cache directly, which is why they passed while the header was
 * visibly broken: the cache was correct and nothing was watching it.
 *
 * These mount two components on the session — AppShell decides the whole menu from it, RequireAuth
 * decides whether to redirect — because one observer is not enough to catch the defect. With a
 * single observer the handover looks fine; with two, the one that subscribed first is orphaned
 * when the session query is removed from the cache, and renders the previous user until reload.
 */
function Menu() {
  const session = useSession();
  return <nav data-testid="menu">{session.data ? "full menu" : "signed out"}</nav>;
}

function Guard() {
  const session = useSession();
  return <div data-testid="guard">{session.data ? "the page" : "redirected"}</div>;
}

function shell(children: ReactNode) {
  const client = new QueryClient({
    // The app's own defaults: a session that is fresh for 30s will not be refetched into place,
    // so the handover is the only thing that can update these components.
    defaultOptions: { queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false } },
  });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function Out() {
  const logout = useLogout();
  return <button onClick={() => logout.mutate()}>out</button>;
}

function In() {
  const login = useLogin();
  return (
    <button onClick={() => login.mutate({ email: "s@example.edu", password: "a long password" })}>
      in
    </button>
  );
}

test("signing out reaches every component watching the session, with no reload", async () => {
  server.use(
    http.get("/api/v1/auth/me", () =>
      HttpResponse.json({ id: "u1", email: "prof@example.edu", role: "prof" }),
    ),
    http.post("/api/v1/auth/logout", () => new HttpResponse(null, { status: 204 })),
  );
  shell(
    <>
      <Menu />
      <Guard />
      <Out />
    </>,
  );
  await waitFor(() => expect(screen.getByTestId("menu")).toHaveTextContent("full menu"));

  screen.getByRole("button", { name: "out" }).click();

  await waitFor(() => expect(screen.getByTestId("menu")).toHaveTextContent("signed out"));
  await waitFor(() => expect(screen.getByTestId("guard")).toHaveTextContent("redirected"));
});

test("signing in reaches every component watching the session, with no reload", async () => {
  server.use(
    http.get("/api/v1/auth/me", () => new HttpResponse(null, { status: 401 })),
    http.post("/api/v1/auth/login", () =>
      HttpResponse.json({ id: "u2", email: "s@example.edu", role: "student" }),
    ),
  );
  shell(
    <>
      <Menu />
      <Guard />
      <In />
    </>,
  );
  await waitFor(() => expect(screen.getByTestId("menu")).toHaveTextContent("signed out"));

  screen.getByRole("button", { name: "in" }).click();

  await waitFor(() => expect(screen.getByTestId("menu")).toHaveTextContent("full menu"));
  await waitFor(() => expect(screen.getByTestId("guard")).toHaveTextContent("the page"));
});
