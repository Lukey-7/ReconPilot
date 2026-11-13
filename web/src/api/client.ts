/**
 * The one way the front end talks to the API.
 *
 * - Every request sends the session cookie (`credentials: "include"`).
 * - Every state-changing request sends `X-CSRF-Token` with the value of the `rp_csrf`
 *   cookie, which the server checks against the session (phase 1, task 6).
 * - A 401 on any request except signing in means the session has ended: the handler
 *   registered by the auth context clears the user, and the app returns to sign-in.
 * - Errors become `ApiError`, carrying the status and FastAPI's `detail`, whose message
 *   is ready to show a person.
 */

export const CSRF_COOKIE = "rp_csrf";
export const CSRF_HEADER = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
/** Routes whose 401 is an answer, not a lost session. */
const NO_SESSION_ROUTES = new Set(["/api/auth/login", "/api/auth/me"]);

/** FastAPI's `detail`: a message, an object (409 at sign-off: `{message, reasons}`) or a 422 list. */
export type ErrorDetail =
  | string
  | { message?: string; reasons?: { code: string; message: string; case_ids: string[] }[] }
  | { loc?: (string | number)[]; msg?: string; type?: string }[]
  | null;

export class ApiError extends Error {
  readonly status: number;
  readonly detail: ErrorDetail;

  constructor(status: number, detail: ErrorDetail, fallback = "The request failed.") {
    super(messageFor(status, detail, fallback));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  /** Reasons attached to a refusal (sign-off's 409), if any. */
  get reasons(): { code: string; message: string; case_ids: string[] }[] {
    const d = this.detail;
    return d && typeof d === "object" && !Array.isArray(d) && Array.isArray(d.reasons) ? d.reasons : [];
  }
}

function messageFor(status: number, detail: ErrorDetail, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => d.msg).filter(Boolean);
    if (msgs.length) return msgs.join(" ");
  } else if (detail && typeof detail === "object" && detail.message) {
    return detail.message;
  }
  if (status === 0) return "Could not reach ReconPilot. Check your connection and try again.";
  if (status === 401) return "Your session has ended. Sign in again.";
  if (status === 403) return "Your role does not allow this.";
  if (status === 404) return "Not found.";
  if (status >= 500) return "ReconPilot hit a problem on the server. Try again in a moment.";
  return fallback;
}

/** The value of a cookie readable by scripts (only `rp_csrf` is; the session cookie is httpOnly). */
export function readCookie(name: string): string | null {
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

export function csrfToken(): string | null {
  return readCookie(CSRF_COOKIE);
}

let onUnauthorised: (() => void) | null = null;

/** Called once by the auth context: what to do when the session has ended. */
export function setUnauthorisedHandler(handler: (() => void) | null): void {
  onUnauthorised = handler;
}

export interface RequestOptions {
  method?: string;
  /** Sent as JSON. */
  json?: unknown;
  /** Sent as is (for uploads). */
  body?: BodyInit;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

function withQuery(path: string, query: RequestOptions["query"]): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** Call the API and return its JSON body (or `undefined` for 204). Throws `ApiError`. */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? (options.json !== undefined || options.body ? "POST" : "GET")).toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  let body = options.body;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  if (!SAFE_METHODS.has(method)) {
    const token = csrfToken();
    if (token) headers[CSRF_HEADER] = token;
  }

  let response: Response;
  try {
    response = await fetch(withQuery(path, options.query), {
      method,
      headers,
      body,
      credentials: "include",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, null);
  }

  if (response.status === 401 && !NO_SESSION_ROUTES.has(path)) onUnauthorised?.();
  if (!response.ok) {
    let detail: ErrorDetail = null;
    try {
      const payload = (await response.json()) as { detail?: ErrorDetail };
      detail = payload?.detail ?? null;
    } catch {
      detail = null;
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T>(path: string, query?: RequestOptions["query"], signal?: AbortSignal) =>
    apiFetch<T>(path, { query, signal }),
  post: <T>(path: string, json?: unknown) => apiFetch<T>(path, { method: "POST", json }),
};

/** A URL path segment, escaped. */
export function seg(value: string): string {
  return encodeURIComponent(value);
}
