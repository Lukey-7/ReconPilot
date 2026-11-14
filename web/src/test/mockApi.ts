/**
 * A stand-in for the API in tests: a table of "METHOD /path" routes (query strings are
 * ignored unless a route includes one) answering with a status and a JSON body. Every
 * request is recorded so tests can check what was sent.
 */
import { vi } from "vitest";

export interface Answer {
  status?: number;
  body?: unknown;
  /** Extra response headers (a download's Content-Disposition, say). */
  headers?: Record<string, string>;
}

export type RouteAnswer = Answer | ((request: RecordedRequest) => Answer);

export interface RecordedRequest {
  method: string;
  path: string;
  url: string;
  headers: Record<string, string>;
  body: unknown;
  credentials: RequestCredentials | undefined;
}

export interface MockApi {
  requests: RecordedRequest[];
  routes: Record<string, RouteAnswer>;
  set: (route: string, answer: RouteAnswer) => void;
  calls: (route: string) => RecordedRequest[];
}

function headersOf(init: RequestInit | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  const h = init?.headers;
  if (!h) return out;
  if (h instanceof Headers) h.forEach((v, k) => (out[k] = v));
  else if (Array.isArray(h)) for (const [k, v] of h) out[k] = v;
  else Object.assign(out, h);
  return out;
}

export function mockApi(routes: Record<string, RouteAnswer> = {}): MockApi {
  const api: MockApi = {
    requests: [],
    routes: { ...routes },
    set(route, answer) {
      api.routes[route] = answer;
    },
    calls(route) {
      const [method, path] = route.split(" ");
      return api.requests.filter((r) => r.method === method && (r.path === path || r.url === path));
    },
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const method = (init?.method ?? "GET").toUpperCase();
      const path = url.split("?")[0] ?? url;
      let body: unknown = init?.body;
      if (typeof body === "string") {
        try {
          body = JSON.parse(body);
        } catch {
          /* not JSON */
        }
      }
      const request: RecordedRequest = { method, path, url, headers: headersOf(init), body, credentials: init?.credentials };
      api.requests.push(request);
      const answer = api.routes[`${method} ${url}`] ?? api.routes[`${method} ${path}`];
      if (!answer) {
        return new Response(JSON.stringify({ detail: `No mock for ${method} ${url}` }), { status: 404 });
      }
      const { status = 200, body: payload, headers = {} } = typeof answer === "function" ? answer(request) : answer;
      if (status === 204) return new Response(null, { status });
      return new Response(typeof payload === "string" && headers["Content-Type"] ? payload : JSON.stringify(payload ?? null), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      });
    }),
  );
  return api;
}
