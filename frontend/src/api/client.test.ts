/**
 * REP-05: the idempotency key that makes a retried submission one submission.
 *
 * It used to be `crypto.randomUUID()`, which exists only in a secure context — HTTPS, or a
 * localhost origin. Reached over plain HTTP on a LAN or Tailscale address it is undefined, and
 * because the key is minted while the component renders, merely opening the report editor threw
 * before anything was drawn.
 */
import { afterEach, expect, test, vi } from "vitest";

import { asProblem, newIdempotencyKey } from "@/api/client";

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

/**
 * `detail` is what every screen renders when a write is refused, and React renders an array by
 * rendering each of its children — so an array of objects there is React error #31, and the
 * router's error boundary replaces the whole application with a blank page. A negative number in
 * the report editor's optional Hours box used to do exactly that (QA pass 3, defect #1).
 */
const response = (status: number, statusText = "") =>
  new Response(null, { status, statusText }) as Response;

test("leaves a problem document that already conforms alone", () => {
  const problem = asProblem(
    {
      type: "about:blank",
      title: "Validation failed",
      status: 422,
      detail: "the package is missing an entry for every required project",
      missing_project_ids: ["a", "b"],
    },
    response(422),
  );

  expect(problem.detail).toBe("the package is missing an entry for every required project");
  // Callers read the unrecognised keys: the editor names the missing projects out of this one.
  expect(problem.missing_project_ids).toEqual(["a", "b"]);
});

test("folds FastAPI's array of validation errors into a sentence", () => {
  const problem = asProblem(
    {
      detail: [
        {
          type: "greater_than_equal",
          loc: ["body", "entries", 0, "hours"],
          msg: "Input should be greater than or equal to 0",
          input: -5,
          ctx: { ge: 0 },
        },
      ],
    },
    response(422, "Unprocessable Entity"),
  );

  expect(typeof problem.detail).toBe("string");
  expect(problem.detail).toBe("entries[0].hours: Input should be greater than or equal to 0");
});

test("names every rejected field when there are several", () => {
  const problem = asProblem(
    {
      detail: [
        { loc: ["body", "title"], msg: "Field required" },
        { loc: ["path", "period_id"], msg: "Input should be a valid UUID" },
      ],
    },
    response(422),
  );

  expect(problem.detail).toBe("title: Field required; period_id: Input should be a valid UUID");
});

test("does not echo the rejected value back to the screen", () => {
  const problem = asProblem(
    { detail: [{ loc: ["body", "password"], msg: "too short", input: "hunter2" }] },
    response(422),
  );

  expect(problem.detail).not.toContain("hunter2");
});

test("falls back to the status text when the body says nothing useful", () => {
  const problem = asProblem({ detail: null }, response(503, "Service Unavailable"));

  expect(problem.detail).toBe("");
  expect(problem.title).toBe("Service Unavailable");
  expect(problem.status).toBe(503);
});

test("survives a body that is not an object at all", () => {
  const problem = asProblem("gateway timeout", response(504, "Gateway Timeout"));

  expect(problem.detail).toBe("");
  expect(problem.title).toBe("Gateway Timeout");
});
