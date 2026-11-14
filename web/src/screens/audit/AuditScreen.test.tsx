import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditEntryCheck, AuditLogEntry, AuditPage, ChainCheck } from "../../api/types";
import { type RouteAnswer, mockApi } from "../../test/mockApi";
import { analyst, location, renderApp, signedInRoutes } from "../../test/render";
import { localDayEnd, localDayStart } from "./filters";

const BASE = "/audit?fund=GEF1&day=2026-11-10";
const LOG = "GET /api/audit";

function entry(seq: number, action: string, overrides: Partial<AuditLogEntry> = {}): AuditLogEntry {
  return {
    seq,
    ts: `2026-11-10T09:${String(seq % 60).padStart(2, "0")}:00+00:00`,
    actor: "analyst1",
    role: "analyst",
    action,
    fund: "GEF1",
    case_id: null,
    case_as_of: null,
    payload: {},
    prev_hash: "a".repeat(64),
    hash: "b".repeat(64),
    ...overrides,
  };
}

const ENTRIES = [
  entry(43, "CASE_REJECTED", {
    actor: "approver1",
    role: "approver",
    case_id: "C1",
    case_as_of: "2026-11-09",
    payload: { case_id: "C1", note: "Book is right" },
  }),
  entry(42, "RUN_FINISHED", { payload: { as_of: "2026-11-10", open_cases: 3, new_cases: 2 } }),
  entry(41, "FILES_UPLOADED", { payload: { as_of: "2026-11-10", files: [{}, {}, {}] } }),
];

function logPage(overrides: Partial<AuditPage> = {}): AuditPage {
  return {
    entries: ENTRIES,
    total: 3,
    newer: 0,
    has_newer: false,
    newer_before: null,
    next_before: null,
    latest_seq: 57,
    ...overrides,
  };
}

function routes(log: RouteAnswer = { body: logPage() }, extra: Record<string, RouteAnswer> = {}) {
  return mockApi({
    ...signedInRoutes(analyst),
    [LOG]: log,
    "GET /api/audit/facets": {
      body: { actors: ["analyst1", "approver1", "system"], actions: ["CASE_REJECTED", "FILES_UPLOADED", "RUN_FINISHED"] },
    },
    ...extra,
  });
}

/** The query the screen last asked the log for. */
function lastQuery(api: ReturnType<typeof mockApi>): URLSearchParams {
  const calls = api.calls(LOG);
  const url = calls[calls.length - 1]?.url ?? "";
  return new URLSearchParams(url.split("?")[1] ?? "");
}

function rows() {
  const table = screen.getByRole("table", { name: /Audit log entries/ });
  return within(table).getAllByRole("row").slice(1);
}

async function openLog(url = BASE) {
  renderApp(url);
  await screen.findByRole("heading", { level: 1, name: "Audit log" });
  await screen.findByRole("table", { name: /Audit log entries/ });
}

describe("audit log", () => {
  it("lists the fund's entries newest first, in words, with each case opening the workbench", async () => {
    const api = routes();
    await openLog();
    const query = lastQuery(api);
    expect(query.get("fund")).toBe("GEF1");
    expect(query.get("limit")).toBe("50");
    expect(query.has("as_of")).toBe(false);
    expect(screen.getByText(/Global Equity Fund, every day\. The log holds 57 entries\./)).toBeInTheDocument();

    const [rejected, finished, uploaded] = rows() as [HTMLElement, HTMLElement, HTMLElement];
    expect(within(rejected).getByText("Rejected")).toBeInTheDocument();
    expect(within(rejected).getByText("(Approver)")).toBeInTheDocument();
    expect(within(rejected).getByText("“Book is right”")).toBeInTheDocument();
    expect(within(rejected).getByRole("link", { name: "C1" })).toHaveAttribute(
      "href",
      "/cases?fund=GEF1&day=2026-11-09&case=C1",
    );
    expect(within(finished).getByText("3 open cases, 2 new")).toBeInTheDocument();
    expect(within(uploaded).getByText("3 files")).toBeInTheDocument();
    // One fund on show: no fund column.
    expect(screen.queryByRole("columnheader", { name: "Fund" })).toBeNull();

    const pager = screen.getByRole("navigation", { name: "Pages of the audit log" });
    expect(within(pager).getByText("1 to 3 of 3 entries, newest first")).toBeInTheDocument();
    for (const name of ["Newest", "Newer", "Older"]) expect(within(pager).getByRole("button", { name })).toBeDisabled();
  });

  it("sends each filter to the server and keeps it in the address", async () => {
    const api = routes();
    const user = userEvent.setup();
    await openLog();
    const form = screen.getByRole("search", { name: "Filter the audit log" });

    await user.selectOptions(within(form).getByLabelText("Action"), "Rejected");
    await waitFor(() => expect(lastQuery(api).get("action")).toBe("CASE_REJECTED"));
    expect(location()).toContain("action=CASE_REJECTED");

    await user.selectOptions(within(form).getByLabelText("Who"), "approver1");
    await waitFor(() => expect(lastQuery(api).get("actor")).toBe("approver1"));

    await user.click(within(form).getByLabelText("Only Tue 10 Nov 2026"));
    await waitFor(() => expect(lastQuery(api).get("as_of")).toBe("2026-11-10"));
    expect(location()).toContain("only_day=1");
    expect(screen.getByText(/Global Equity Fund, Tue 10 Nov 2026 only/)).toBeInTheDocument();

    await user.type(within(form).getByLabelText("Case"), "C1{Enter}");
    await waitFor(() => expect(lastQuery(api).get("case")).toBe("C1"));

    const from = within(form).getByLabelText("From");
    await user.type(from, "2026-11-09");
    await waitFor(() => expect(lastQuery(api).get("from")).toBe(localDayStart("2026-11-09")));
    const to = within(form).getByLabelText("To");
    await user.type(to, "2026-11-10");
    await waitFor(() => expect(lastQuery(api).get("to")).toBe(localDayEnd("2026-11-10")));
    expect(location()).toContain("from=2026-11-09");

    await user.click(within(form).getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(location()).toBe(BASE));
    // Back to the unfiltered view (already fetched, so shown from the cache).
    expect(within(form).getByLabelText("Action")).toHaveValue("");
    expect(within(form).getByLabelText("Case")).toHaveValue("");
    expect(within(form).queryByRole("button", { name: "Clear filters" })).toBeNull();
    expect([...new URLSearchParams(api.calls(LOG)[0]?.url.split("?")[1]).keys()].sort()).toEqual(["fund", "limit"]);
  });

  it("shows every fund and the system's own entries, with a fund column", async () => {
    const all = logPage({
      entries: [entry(44, "SIGN_IN", { fund: null, payload: { ip: "127.0.0.1" } }), ...ENTRIES.slice(1)],
    });
    const api = routes({ body: all });
    const user = userEvent.setup();
    await openLog();
    await user.selectOptions(screen.getByLabelText("Entries"), "Every fund and sign-ins");
    await waitFor(() => expect(lastQuery(api).has("fund")).toBe(false));
    expect(location()).toContain("scope=all");
    expect(screen.getByLabelText("Only Tue 10 Nov 2026")).toBeDisabled();
    expect(await screen.findByRole("columnheader", { name: "Fund" })).toBeInTheDocument();
    expect(within(rows()[0] as HTMLElement).getByText("System")).toBeInTheDocument();
    expect(within(rows()[1] as HTMLElement).getByText("GEF1")).toBeInTheDocument();
    expect(api.calls("GET /api/audit/facets").some((c) => !c.url.includes("fund="))).toBe(true);
  });

  it("pages older and back to newer with the server's cursors", async () => {
    const api = routes((request) => {
      const before = new URLSearchParams(request.url.split("?")[1] ?? "").get("before");
      if (before === "41") {
        return { body: logPage({ entries: [entry(40, "SIGN_IN")], total: 120, newer: 50, has_newer: true, newer_before: null, next_before: 39 }) };
      }
      return { body: logPage({ total: 120, next_before: 41 }) };
    });
    const user = userEvent.setup();
    await openLog();
    const pager = screen.getByRole("navigation", { name: "Pages of the audit log" });
    expect(within(pager).getByText("1 to 3 of 120 entries, newest first")).toBeInTheDocument();
    await user.click(within(pager).getByRole("button", { name: "Older" }));
    await waitFor(() => expect(lastQuery(api).get("before")).toBe("41"));
    expect(location()).toContain("before=41");
    expect(await within(pager).findByText("51 to 51 of 120 entries, newest first")).toBeInTheDocument();
    await user.click(within(pager).getByRole("button", { name: "Newer" }));
    await waitFor(() => expect(location()).toBe(BASE));
    expect(await within(pager).findByText("1 to 3 of 120 entries, newest first")).toBeInTheDocument();
    expect(api.calls(LOG).every((c) => !c.url.includes("before=39"))).toBe(true);
  });

  it("opens an entry's full record with the server's check of it", async () => {
    const check: AuditEntryCheck = { ...(ENTRIES[0] as AuditLogEntry), hash_ok: true, linked: true };
    const api = routes(undefined, {
      "GET /api/audit/entries/43": { body: check },
      "GET /api/audit/entries/42": { body: { ...(ENTRIES[1] as AuditLogEntry), hash_ok: false, linked: true } },
    });
    const user = userEvent.setup();
    await openLog();
    const toggle = screen.getByRole("button", { name: "Entry 43: show its full record" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const checks = await screen.findByRole("list", { name: "Server check of entry #43" });
    expect(within(checks).getByText("Its hash recomputes from what it records.")).toBeInTheDocument();
    expect(within(checks).getByText("It names the hash of entry #42.")).toBeInTheDocument();
    expect(screen.getByText(/"note": "Book is right"/)).toBeInTheDocument();
    expect(screen.getAllByText("b".repeat(64)).length).toBeGreaterThan(0);
    expect(api.calls("GET /api/audit/entries/43")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Entry 42: show its full record" }));
    const tampered = await screen.findByRole("list", { name: "Server check of entry #42" });
    expect(
      within(tampered).getByText("Its hash does not match what it records: the entry was changed after it was written."),
    ).toBeInTheDocument();
  });

  it("verifies the chain on the server and says it is intact", async () => {
    const intact: ChainCheck = {
      chain_ok: true,
      broken_at: null,
      entries: 57,
      last_seq: 57,
      last_hash: "c".repeat(64),
      verified_at: "2026-11-10T10:02:00+00:00",
      verified_by: "analyst1",
      seq: 58,
    };
    const api = routes(undefined, { "POST /api/audit/verify": { body: intact } });
    const user = userEvent.setup();
    await openLog();
    const before = api.calls(LOG).length;
    await user.click(screen.getByRole("button", { name: "Verify chain" }));
    const verdict = await screen.findByText(/Chain intact\./);
    expect(verdict.closest("[role=status]")).toHaveTextContent(
      /All 57 entries re-checked on the server.*by you; the check itself is entry #58\./,
    );
    expect(api.calls("POST /api/audit/verify")).toHaveLength(1);
    // The check is recorded in the log, so the log is asked again.
    await waitFor(() => expect(api.calls(LOG).length).toBeGreaterThan(before));
  });

  it("names and shows the first broken entry when the chain is broken", async () => {
    const broken: ChainCheck = {
      chain_ok: false,
      broken_at: 4,
      entries: 57,
      last_seq: 57,
      last_hash: "c".repeat(64),
      verified_at: "2026-11-10T10:02:00+00:00",
      verified_by: "approver1",
      seq: 58,
    };
    routes(undefined, {
      "POST /api/audit/verify": { body: broken },
      "GET /api/audit/entries/4": { body: { ...entry(4, "CASE_APPROVED"), hash_ok: false, linked: true } },
    });
    const user = userEvent.setup();
    await openLog();
    await user.click(screen.getByRole("button", { name: "Verify chain" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Chain broken at entry #4.");
    expect(alert).toHaveTextContent("by approver1");
    await user.click(await within(alert).findByText("Show entry #4"));
    expect(await within(alert).findByText(/Its hash does not match what it records/)).toBeInTheDocument();
  });

  describe("export", () => {
    let clicked: { href: string; download: string }[];

    beforeEach(() => {
      clicked = [];
      vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:audit-test"), revokeObjectURL: vi.fn() }));
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push({ href: this.href, download: this.download });
      });
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("downloads the entries the filters match, under the server's file name", async () => {
      const api = routes(undefined, {
        "GET /api/audit/export.csv": {
          body: "seq,ts,actor,role,action,fund,case_id,payload,prev_hash,hash\r\n",
          headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="audit_GEF1_2026-11-10.csv"' },
        },
      });
      const user = userEvent.setup();
      await openLog(`${BASE}&action=CASE_REJECTED`);
      await user.click(screen.getByRole("button", { name: "Export CSV" }));
      expect(await screen.findByText("Downloaded audit_GEF1_2026-11-10.csv.")).toBeInTheDocument();
      expect(clicked).toEqual([{ href: "blob:audit-test", download: "audit_GEF1_2026-11-10.csv" }]);
      const url = api.calls("GET /api/audit/export.csv")[0]?.url ?? "";
      expect(url).toBe("/api/audit/export.csv?fund=GEF1&action=CASE_REJECTED");
    });

    it("shows a refused export in the server's words and saves nothing", async () => {
      routes(undefined, {
        "GET /api/audit/export.csv": {
          status: 422,
          body: { detail: "120,000 entries match; an export holds at most 100,000. Narrow the filters." },
        },
      });
      const user = userEvent.setup();
      await openLog();
      await user.click(screen.getByRole("button", { name: "Export CSV" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Narrow the filters.");
      expect(clicked).toEqual([]);
    });
  });

  it("says when nothing matches", async () => {
    routes({ body: logPage({ entries: [], total: 0 }) });
    renderApp(`${BASE}&actor=nobody`);
    expect(await screen.findByText("No entry matches these filters.")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Pages of the audit log" })).toBeNull();
  });

  it("is reached from the screen list and with g l, keeping the fund and day", async () => {
    routes(undefined, { "GET /api/funds/GEF1/days/2026-11-10/overview": { status: 500, body: {} } });
    const user = userEvent.setup();
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const nav = await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() =>
      expect(within(nav).getByRole("link", { name: /Audit log/ })).toHaveAttribute(
        "href",
        "/audit?fund=GEF1&day=2026-11-10",
      ),
    );
    await user.keyboard("gl");
    await waitFor(() => expect(location()).toBe("/audit?fund=GEF1&day=2026-11-10"));
    expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
  });
});
