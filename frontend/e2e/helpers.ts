/**
 * Shared helpers for the end-to-end specs.
 *
 * These run against the dev Compose stack loaded with the demo dataset, so they act as the people
 * in the product act: sign in through the form, click through the screens, and read what a user
 * would read. Anything that reaches past the UI is limited to setting up a precondition the
 * product has no screen for (a deadline in the past), and is called out where it happens.
 */
import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PROF = { email: "prof@example.edu", password: "demo-password-change-me" };
export const STUDENT = { email: "an.nguyen@example.edu", password: "demo-password-change-me" };

/** Mailpit's HTTP API, so a delivered email can be read without a mailbox. */
export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

/**
 * The path from a token link emailed to one address — an invitation or a recovery link.
 *
 * Read from the delivered mail rather than from the log, because the email is the channel the
 * token actually travels on (AUTH-01) and a link nobody receives is an account nobody can reach.
 *
 * Polled: the send is deferred until the issuing transaction commits, then runs as a worker job,
 * so it lands a moment after the click returns.
 */
export async function tokenPath(
  request: APIRequestContext,
  email: string,
  kind: "accept-invitation" | "reset-password",
  attempts = 20,
): Promise<string> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const mine = (await inbox(request)).filter((message) =>
      message.To.some((to) => to.Address === email),
    );
    for (const message of mine) {
      const match = (await messageBody(request, message.ID)).match(
        new RegExp(`/${kind}\\?token=[A-Za-z0-9._~-]+`),
      );
      if (match) return match[0];
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`no ${kind} link was emailed to ${email}`);
}

export async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(who.email);
  await page.getByLabel(/password/i).fill(who.password);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: /sign out/i }).click();
}

type Message = { ID: string; To: { Address: string }[]; Subject: string };

export async function inbox(request: APIRequestContext): Promise<Message[]> {
  const response = await request.get(`${MAILPIT}/api/v1/messages?limit=200`);
  if (!response.ok()) return [];
  const body = (await response.json()) as { messages?: Message[] };
  return body.messages ?? [];
}

export async function clearInbox(request: APIRequestContext): Promise<void> {
  await request.delete(`${MAILPIT}/api/v1/messages`);
}

export async function messageBody(request: APIRequestContext, id: string): Promise<string> {
  const response = await request.get(`${MAILPIT}/api/v1/message/${id}`);
  const body = (await response.json()) as { Text?: string; HTML?: string };
  return `${body.Text ?? ""}\n${body.HTML ?? ""}`;
}

export function addressesOf(messages: Message[]): string[] {
  return messages.flatMap((message) => message.To.map((to) => to.Address));
}
