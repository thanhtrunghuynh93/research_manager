/**
 * AUTH-03: signing out has to end access to what was on screen, not just to the server.
 *
 * The cache is shared by everyone who uses the browser. Invalidation marks entries stale but
 * leaves them readable, so on a shared machine the next person to sign in saw the previous user's
 * overview, projects and notifications until each refetch landed.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { useLogin, useLogout } from "@/features/auth/queries";
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
