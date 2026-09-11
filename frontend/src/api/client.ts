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
  detail: string;
  request_id?: string;
  [extra: string]: unknown;
};

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
      problem = (await response.json()) as Problem;
    } catch {
      problem = { type: "about:blank", title: response.statusText, status: response.status, detail: "" };
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
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) =>
    request<T>("PATCH", path, { ...opts, body }),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>("DELETE", path, opts),
};

export function newIdempotencyKey(): string {
  return crypto.randomUUID();
}
