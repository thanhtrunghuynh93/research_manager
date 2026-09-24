import { expect, type Page, type APIRequestContext } from "@playwright/test";

/**
 * A decoded JSON body from the API, read field by field.
 *
 * These specs are black box: what they assert against is the shape the server actually put on the
 * wire, which is the thing under test. Typing them from `src/api/generated` would check each
 * response against the same definitions that produced it, so a field that drifted would agree
 * with itself and the test would still pass. So the bodies stay untyped on purpose — and that
 * decision is stated once, here, rather than as the forty-three separate `any` annotations it
 * used to be spread across.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;

export const API = "http://localhost:8021";
export const MAILPIT = "http://localhost:8025";
export const PASSWORD = "QaTester-2026-pw";

export const PROF = { email: "qa.prof.k@example.edu", password: PASSWORD, name: "Prof QA Tester" };
export const STUDENT = { email: "qa.student.k@example.edu", password: PASSWORD, name: "Student QA Tester" };

export async function signIn(page: Page, who: { email: string; password: string }) {
  // Clear the session first. /login redirects an authenticated visitor away, so signing in as a
  // second person inside one test silently kept the first person's session — and "Sign out is
  // visible" was already true, which is why it looked like it had worked.
  await page.context().clearCookies();
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(who.email);
  await page.getByLabel(/password/i).fill(who.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible({ timeout: 15_000 });
  // And prove who is actually signed in, rather than trusting the screen. Retried: the session
  // cookie occasionally lands in the request context a beat after the screen has moved on.
  let email: string | undefined;
  for (let i = 0; i < 10; i += 1) {
    const me = await page.request.fetch(`${API}/api/v1/auth/me`, { failOnStatusCode: false });
    if (me.ok()) {
      email = (await me.json()).email;
      if (email === who.email) break;
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  expect(email, "signed in as the account this test asked for").toBe(who.email);
}

/** The invitation link emailed to an address, read from mailpit (the channel AUTH-01 names). */
export async function tokenPath(
  request: APIRequestContext,
  email: string,
  kind: "accept-invitation" | "reset-password" = "accept-invitation",
  attempts = 25,
): Promise<string> {
  for (let i = 0; i < attempts; i += 1) {
    const list = await (await request.get(`${MAILPIT}/api/v1/messages?limit=100`)).json();
    for (const m of list.messages ?? []) {
      if (!(m.To ?? []).some((t: Json) => t.Address === email)) continue;
      const body = await (await request.get(`${MAILPIT}/api/v1/message/${m.ID}`)).text();
      const match = body.match(new RegExp(`/${kind}\\?token=[A-Za-z0-9._~%-]+`));
      if (match) return match[0].replace(/%3D/g, "=");
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`no ${kind} link emailed to ${email}`);
}

/** An API context carrying the signed-in browser's session cookie. */
export async function asUser(page: Page) {
  return page.request;
}

export async function api(page: Page, method: string, path: string, data?: unknown) {
  const res = await page.request.fetch(`${API}/api/v1${path}`, {
    method,
    headers: { "content-type": "application/json" },
    data: data === undefined ? undefined : JSON.stringify(data),
    failOnStatusCode: false,
  });
  let body: Json = null;
  try { body = await res.json(); } catch { body = await res.text(); }
  return { status: res.status(), body };
}

/** A list response, whichever shape it takes — and a legible error when it is neither. */
export function asList(res: { status: number; body: Json }, what = "list"): Json[] {
  if (Array.isArray(res.body)) return res.body;
  if (Array.isArray(res.body?.items)) return res.body.items;
  throw new Error(`${what}: expected a list, got ${res.status} ${JSON.stringify(res.body).slice(0, 300)}`);
}
