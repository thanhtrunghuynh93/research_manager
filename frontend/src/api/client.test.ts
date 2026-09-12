/**
 * REP-05: the idempotency key that makes a retried submission one submission.
 *
 * It used to be `crypto.randomUUID()`, which exists only in a secure context — HTTPS, or a
 * localhost origin. Reached over plain HTTP on a LAN or Tailscale address it is undefined, and
 * because the key is minted while the component renders, merely opening the report editor threw
 * before anything was drawn.
 */
import { afterEach, expect, test, vi } from "vitest";

import { newIdempotencyKey } from "@/api/client";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

afterEach(() => {
  vi.unstubAllGlobals();
});

test("returns a v4 uuid where randomUUID exists", () => {
  expect(newIdempotencyKey()).toMatch(UUID_V4);
});

test("still returns one where randomUUID does not exist", () => {
  // Exactly what a browser exposes over plain http: getRandomValues, but no randomUUID.
  vi.stubGlobal("crypto", {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  });

  expect(newIdempotencyKey()).toMatch(UUID_V4);
});

test("still returns one with no web crypto at all", () => {
  vi.stubGlobal("crypto", undefined);

  expect(newIdempotencyKey()).toMatch(UUID_V4);
});

test("does not repeat itself", () => {
  vi.stubGlobal("crypto", {
    getRandomValues: globalThis.crypto.getRandomValues.bind(globalThis.crypto),
  });

  const keys = new Set(Array.from({ length: 500 }, () => newIdempotencyKey()));

  expect(keys.size).toBe(500);
});
