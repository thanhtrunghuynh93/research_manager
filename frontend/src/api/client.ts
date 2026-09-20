/**
 * Thin fetch wrapper used by every feature's queries.ts.
 * - Sends the session cookie (same origin).
 * - Parses RFC 9457 problem responses into ApiError.
 * - Adds Idempotency-Key on demand for retryable mutations (report submit, review actions).
 */

export type Problem = {
  type: string;
  title: string;
  status: number;
  /** Always a string by the time it leaves here — see `asProblem`. */
  detail: string;
  request_id?: string;
  [extra: string]: unknown;
};

/**
 * One entry of a non-conforming `detail`, as a sentence.
 *
 * The shape handled here is FastAPI's: `{loc, msg, type, input, ctx}`. `input` is the caller's own
 * rejected value and is never read — it can be the whole payload, and the field name says where to
 * look without putting it back on the screen.
 */
function oneDetail(entry: unknown): string {
  if (typeof entry === "string") return entry;
  if (typeof entry !== "object" || entry === null) return "";
  const record = entry as Record<string, unknown>;
  const message = typeof record.msg === "string" ? record.msg : "";
  const field = Array.isArray(record.loc)
    ? record.loc
        .slice(1)
        .map((part) => (typeof part === "number" ? `[${part}]` : `.${String(part)}`))
        .join("")
        .replace(/^\./, "")
    : "";
  if (!message) return field;
  return field ? `${field}: ${message}` : message;
}

/**
 * A problem document whose `detail` is a string, whatever the server actually sent.
 *
 * Every component that shows the API's own words renders `problem.detail` — and React renders an
 * array by rendering each of its children, so an array of objects there is React error #31, which
 * the router's error boundary turns into a blank page with no navigation on it. That is what a
 * negative number in the report editor's optional Hours box used to do to the whole application.
 *
 * `app.api.problems` now answers validation failures in this shape, so this is the net rather than
 * the fix: it holds for an endpoint that has not been reached yet, a proxy that rewrites an error,
 * and any future handler that forgets. The unrecognised keys are kept, because callers read them —
 * the editor names the projects missing from a package out of `missing_project_ids`.
 */
export function asProblem(body: unknown, response: Response): Problem {
  const raw = (typeof body === "object" && body !== null ? body : {}) as Record<string, unknown>;
  const detail = raw.detail;
  return {
    ...raw,
    type: typeof raw.type === "string" ? raw.type : "about:blank",
    title: typeof raw.title === "string" && raw.title ? raw.title : response.statusText,
    status: typeof raw.status === "number" ? raw.status : response.status,
    detail:
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map(oneDetail).filter(Boolean).join("; ")
          : oneDetail(detail),
  };
}

export class ApiError extends Error {
  constructor(
    public readonly problem: Problem,
    public readonly response: Response,
  ) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
  }
}

type RequestOptions = {
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Statuses to treat as success and still parse (e.g. 503 from /api/readyz). */
  acceptStatuses?: number[];
};

async function request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    signal: opts.signal,
  });

  const accepted = response.ok || (opts.acceptStatuses?.includes(response.status) ?? false);
  if (!accepted) {
    let problem: Problem;
    try {
      problem = asProblem(await response.json(), response);
    } catch {
      problem = {
        type: "about:blank",
        title: response.statusText,
        status: response.status,
        detail: "",
      };
    }
    throw new ApiError(problem, response);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>("GET", path, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("POST", path, { ...opts, body }),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PUT", path, { ...opts, body }),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PATCH", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};

/**
 * A random key identifying one submission attempt (REP-05).
 *
 * `crypto.randomUUID` exists only in a secure context — HTTPS, or a localhost origin — so over
 * plain HTTP on a LAN or Tailscale address it is undefined and merely reading it throws.
 * `crypto.getRandomValues` carries no such restriction, so the v4 layout is assembled from it
 * and `randomUUID` is used only when it is actually there.
 */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    // Neither is a browser this app supports; a key that is merely unlikely to repeat still
    // makes a retry idempotent, which is the only thing asked of it.
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6]! & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8]! & 0x3f) | 0x80; // variant 1
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
