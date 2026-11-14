import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/mockApi";
import { ApiError, api, apiFetch, attachmentName, csrfToken, download, setUnauthorisedHandler } from "./client";

afterEach(() => setUnauthorisedHandler(null));

describe("apiFetch", () => {
  it("sends credentials and parses JSON", async () => {
    const mock = mockApi({ "GET /api/funds": { body: [{ code: "GEF1" }] } });
    await expect(api.get("/api/funds")).resolves.toEqual([{ code: "GEF1" }]);
    expect(mock.requests[0]?.credentials).toBe("include");
    expect(mock.requests[0]?.headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("sends the rp_csrf cookie as X-CSRF-Token on state changes", async () => {
    document.cookie = "rp_csrf=tok%3Dabc; path=/";
    expect(csrfToken()).toBe("tok=abc");
    const mock = mockApi({ "POST /api/funds/GEF1/cases/C1/decision": { body: { ok: true } } });
    await api.post("/api/funds/GEF1/cases/C1/decision", { decision: "approve", version: 1 });
    const sent = mock.requests[0];
    expect(sent?.method).toBe("POST");
    expect(sent?.headers["X-CSRF-Token"]).toBe("tok=abc");
    expect(sent?.headers["Content-Type"]).toBe("application/json");
    expect(sent?.body).toEqual({ decision: "approve", version: 1 });
  });

  it("adds query parameters, skipping empty ones", async () => {
    const mock = mockApi({ "GET /api/x": { body: {} } });
    await api.get("/api/x", { for_user: "me", q: "", material: true, n: null });
    expect(mock.requests[0]?.url).toBe("/api/x?for_user=me&material=true");
  });

  it("returns undefined for 204", async () => {
    mockApi({ "POST /api/auth/logout": { status: 204 } });
    await expect(api.post("/api/auth/logout")).resolves.toBeUndefined();
  });

  it("turns FastAPI's detail into the error message", async () => {
    mockApi({
      "POST /api/a": { status: 409, body: { detail: "C1 was changed by someone else; reload it." } },
      "POST /api/b": {
        status: 409,
        body: {
          detail: {
            message: "2026-11-10 cannot be signed off yet.",
            reasons: [{ code: "FOUR_EYES", message: "m", case_ids: ["C1"] }],
          },
        },
      },
      "POST /api/c": { status: 422, body: { detail: [{ loc: ["body", "version"], msg: "Field required", type: "missing" }] } },
      "GET /api/d": { status: 500, body: null },
    });
    await expect(api.post("/api/a")).rejects.toMatchObject({
      status: 409,
      message: "C1 was changed by someone else; reload it.",
    });
    const signOff = await api.post("/api/b").catch((e: unknown) => e);
    expect(signOff).toBeInstanceOf(ApiError);
    expect((signOff as ApiError).message).toBe("2026-11-10 cannot be signed off yet.");
    expect((signOff as ApiError).reasons.map((r) => r.code)).toEqual(["FOUR_EYES"]);
    await expect(api.post("/api/c")).rejects.toMatchObject({ status: 422, message: "Field required" });
    await expect(api.get("/api/d")).rejects.toMatchObject({ status: 500, message: expect.stringContaining("server") });
  });

  it("reports an unreachable API as status 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))),
    );
    await expect(api.get("/api/funds")).rejects.toMatchObject({ status: 0, message: expect.stringContaining("reach") });
  });

  it("calls the unauthorised handler on a 401, except when signing in or checking the session", async () => {
    const handler = vi.fn();
    setUnauthorisedHandler(handler);
    mockApi({
      "GET /api/funds": { status: 401, body: { detail: "Not signed in." } },
      "POST /api/auth/login": { status: 401, body: { detail: "Wrong username or password." } },
      "GET /api/auth/me": { status: 401, body: { detail: "Not signed in." } },
    });
    await expect(api.post("/api/auth/login", { username: "x", password: "y" })).rejects.toMatchObject({
      status: 401,
      message: "Wrong username or password.",
    });
    await expect(api.get("/api/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(handler).not.toHaveBeenCalled();
    await expect(apiFetch("/api/funds")).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe("download", () => {
  it("reads the file name the server gives", () => {
    expect(attachmentName('attachment; filename="mi_GEF1_2026-11-10.csv"')).toBe("mi_GEF1_2026-11-10.csv");
    expect(attachmentName("attachment; filename=report.xlsx")).toBe("report.xlsx");
    expect(attachmentName("attachment")).toBeNull();
    expect(attachmentName(null)).toBeNull();
  });

  it("hands the file to the browser, falling back to the path's last part for a name", async () => {
    mockApi({ "GET /api/x/mi.csv": { body: "a,b\r\n", headers: { "Content-Type": "text/csv" } } });
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() }));
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    await expect(download("/api/x/mi.csv")).resolves.toEqual({ filename: "mi.csv", bytes: 5 });
    expect(names).toEqual(["mi.csv"]);
    expect(document.querySelector("a[download]")).toBeNull();
    click.mockRestore();
  });

  it("turns a refusal into an ApiError and ends the session on 401", async () => {
    mockApi({
      "GET /api/x/report.xlsx": { status: 409, body: { detail: "Run the day first." } },
      "GET /api/y/report.xlsx": { status: 401, body: { detail: "Not signed in." } },
    });
    const handler = vi.fn();
    setUnauthorisedHandler(handler);
    await expect(download("/api/x/report.xlsx")).rejects.toMatchObject({ status: 409, message: "Run the day first." });
    expect(handler).not.toHaveBeenCalled();
    await expect(download("/api/y/report.xlsx")).rejects.toBeInstanceOf(ApiError);
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
