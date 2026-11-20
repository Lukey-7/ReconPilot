import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AuditEntry, DayAudit, Overview, OverviewCase, ReleaseForMe, User } from "../../api/types";
import { type RouteAnswer, mockApi } from "../../test/mockApi";
import { analyst, approver, dayRecord, daysList, location, releaseFor, renderApp, signedInRoutes } from "../../test/render";
import { entryDetail } from "./AuditTrail";

const URL_DAY = "/signoff?fund=GEF1&day=2026-11-10";
const BASE = "/api/funds/GEF1/days/2026-11-10";
const viewer: User = { username: "viewer1", display_name: "Val Kerr", role: "viewer", is_admin: false };

function caseRow(id: string, overrides: Partial<OverviewCase> = {}): OverviewCase {
  return {
    case_id: id,
    security_id: `SEC-${id}`,
    security_name: `Security ${id}`,
    category: "TIMING",
    ai_category: null,
    ai_flag: "",
    status: "PENDING",
    final_category: null,
    nav_impact: -1000,
    nav_impact_bp: -0.04,
    gross_exposure: 5000,
    material: false,
    escalated: false,
    sla_breached: false,
    age_days: 0,
    age_bucket: "0-1",
    version: 1,
    reviewed_by: "",
    reviewed_role: "",
    review_note: "",
    first_seen: "2026-11-10",
    sla_days: 3,
    escalation_reason: "",
    ...overrides,
  };
}

const PENDING_C1 = caseRow("C1", { category: "MISSING_TRADE", material: true, escalated: true });
const APPROVED_C2 = caseRow("C2", {
  category: "PRICE_MISMATCH",
  status: "APPROVED",
  reviewed_by: "analyst1",
  reviewed_role: "analyst",
  review_note: "Vendor price confirmed with the custodian.",
});
const RECLASS_C3 = caseRow("C3", {
  final_category: "DIVIDEND",
  status: "RECLASSIFIED",
  reviewed_by: "approver1",
  reviewed_role: "approver",
});

function overview(cases: OverviewCase[], overrides: Partial<Overview> = {}): Overview {
  const pending = cases.filter((c) => c.status === "PENDING").length;
  return {
    fund: { code: "GEF1", name: "Global Equity Fund", base_currency: "USD", materiality_bp: 1 },
    as_of: "2026-11-10",
    day_status: "ready",
    has_run: true,
    run_at: "2026-11-10T08:00:00+00:00",
    run_by: "analyst1",
    signed_off_by: null,
    signed_off_at: null,
    nav: null,
    checks: [],
    release: { ready: false, reasons: [] },
    run: { matches: 10, breaks: cases.length, new_cases: cases.length, carried_cases: 0 },
    accounted: {
      breaks_found: cases.length,
      breaks_in_cases: cases.length,
      breaks_not_in_case: 0,
      open_cases: cases.length,
      decided: cases.length - pending,
      approved: cases.filter((c) => c.status === "APPROVED").length,
      rejected: 0,
      reclassified: cases.filter((c) => c.status === "RECLASSIFIED").length,
      pending,
    },
    impact: { cases, net: 0, gross: 0, gross_exposure: 0, material: 0 },
    ageing: [],
    sla_breaches: [],
    escalations: [],
    cleared_today: [],
    trend: [],
    ...overrides,
  };
}

function entry(seq: number, action: string, overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    seq,
    ts: `2026-11-10T09:${String(seq % 60).padStart(2, "0")}:00+00:00`,
    actor: "analyst1",
    role: "analyst",
    action,
    case_id: null,
    payload: {},
    prev_hash: "0".repeat(64),
    hash: `${seq}`.padStart(64, "a"),
    ...overrides,
  };
}

function audit(entries: AuditEntry[], overrides: Partial<DayAudit> = {}): DayAudit {
  return { fund: "GEF1", as_of: "2026-11-10", entries, chain_ok: true, broken_at: null, ...overrides };
}

const TRAIL = [
  entry(11, "FILES_UPLOADED", { payload: { as_of: "2026-11-10", files: [{}, {}, {}] } }),
  entry(12, "VALIDATION_PASSED", { payload: { as_of: "2026-11-10", errors: 0, warnings: 1 } }),
  entry(13, "RUN_FINISHED", { payload: { as_of: "2026-11-10", open_cases: 3, new_cases: 2 } }),
  entry(14, "CASE_APPROVED", { case_id: "C2", payload: { case_id: "C2", note: "Vendor price confirmed." } }),
  entry(15, "CASE_RECLASSIFIED", {
    actor: "approver1",
    role: "approver",
    case_id: "C3",
    payload: { case_id: "C3", final: "DIVIDEND", note: "" },
  }),
];

/** Routes for the sign-off screen of 2026-11-10, on top of a signed-in session. */
function routes(
  user: User,
  {
    release = releaseFor("GEF1", "2026-11-10"),
    cases = [PENDING_C1, APPROVED_C2, RECLASS_C3],
    trail = audit(TRAIL),
  }: { release?: ReleaseForMe; cases?: OverviewCase[]; trail?: DayAudit } = {},
): Record<string, RouteAnswer> {
  return {
    ...signedInRoutes(user),
    [`GET ${BASE}/release`]: { body: release },
    [`GET ${BASE}/overview`]: { body: overview(cases) },
    [`GET ${BASE}/audit`]: { body: trail },
  };
}

const READY = releaseFor("GEF1", "2026-11-10", {
  ready: true,
  reasons: [],
  checks: [
    { name: "Cash tie-out", status: "PASS", detail: "" },
    { name: "Stale prices", status: "WARN", detail: "1 price is 3 days old." },
  ],
  signable_by_me: true,
});
const DECIDED = [caseRow("C1", { category: "MISSING_TRADE", material: true, escalated: true, status: "APPROVED", reviewed_by: "approver1", reviewed_role: "approver" }), APPROVED_C2, RECLASS_C3];

function conditions() {
  return screen.findByRole("region", { name: "Release conditions" });
}

function signBox() {
  return screen.findByRole("region", { name: /^Sign off/ });
}

function condition(list: HTMLElement, code: string): HTMLElement {
  const item = list.querySelector<HTMLElement>(`[data-condition="${code}"]`);
  if (!item) throw new Error(`no condition ${code}`);
  return item;
}

describe("Sign-off screen", () => {
  it("lists every release condition, unmet ones in the server's words with their cases", async () => {
    mockApi(routes(analyst));
    renderApp(URL_DAY);
    expect(await screen.findByRole("heading", { level: 1, name: "NAV sign-off" })).toBeInTheDocument();
    const list = await conditions();

    const pending = condition(list, "PENDING_DECISIONS");
    expect(pending).toHaveAttribute("data-state", "unmet");
    expect(within(pending).getByText("Every open case decided")).toBeInTheDocument();
    expect(within(pending).getByText("Not met")).toBeInTheDocument();
    expect(within(pending).getByText("3 cases still pending a decision.")).toBeInTheDocument();
    expect(within(pending).getByRole("link", { name: "C2" })).toHaveAttribute(
      "href",
      "/cases?fund=GEF1&day=2026-11-10&case=C2",
    );
    expect(condition(list, "MATERIAL_NOT_APPROVED")).toHaveAttribute("data-state", "unmet");

    const escalated = condition(list, "ESCALATED_NEEDS_APPROVER");
    expect(escalated).toHaveAttribute("data-state", "met");
    expect(within(escalated).getByText("1 escalated case decided by an approver.")).toBeInTheDocument();
    expect(within(condition(list, "CHECK_FAILED")).getByText("No release check failed.")).toBeInTheDocument();
    // Four-eyes applies to whoever signs off, not to an analyst.
    expect(condition(list, "FOUR_EYES")).toHaveAttribute("data-state", "na");
    expect(within(list).getByText("2 conditions not met", { exact: false })).toBeInTheDocument();
  });

  it("shows who decided what, with each person's count", async () => {
    mockApi(routes(analyst));
    renderApp(URL_DAY);
    const who = await screen.findByRole("region", { name: "Who decided what" });
    const people = await within(who).findByRole("list", { name: "People who decided cases today" });
    expect(within(people).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "analyst1 Analyst 1 case",
      "approver1 Approver 1 case",
    ]);
    expect(within(who).getByText("3 open cases, 1 pending")).toBeInTheDocument();
    const table = within(who).getByRole("table");
    const row = within(table).getByRole("link", { name: "C3" }).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("Reclassified")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("Dividend")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("approver1")).toBeInTheDocument();
    expect(within(table).getByText("Vendor price confirmed with the custodian.")).toBeInTheDocument();
  });

  it("shows the day's audit trail with the chain verified", async () => {
    mockApi(routes(analyst));
    renderApp(URL_DAY);
    const trail = await screen.findByRole("region", { name: "Audit trail" });
    expect(await within(trail).findByText(/Chain verified on the server/)).toBeInTheDocument();
    expect(within(trail).getByText("5 entries for this day")).toBeInTheDocument();
    const items = within(within(trail).getByRole("list", { name: "Latest entries" })).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("Files uploaded");
    expect(items[0]).toHaveTextContent("3 files");
    expect(items[4]).toHaveTextContent("Reclassified");
    expect(items[4]).toHaveTextContent("as Dividend");
    expect(items[4]).toHaveTextContent("approver1 (Approver)");
    expect(within(items[3] as HTMLElement).getByRole("link", { name: "C2" })).toBeInTheDocument();
  });

  it("opens the day's entries in the whole audit log", async () => {
    mockApi(routes(analyst));
    renderApp(URL_DAY);
    const trail = await screen.findByRole("region", { name: "Audit trail" });
    expect(within(trail).getByRole("link", { name: "Open in the audit log" })).toHaveAttribute(
      "href",
      "/audit?fund=GEF1&day=2026-11-10&only_day=1",
    );
  });

  it("keeps earlier entries behind an expander and warns of a broken chain", async () => {
    const many = Array.from({ length: 14 }, (_, i) => entry(i + 1, "AI_CALL", { payload: { model: "m1" } }));
    mockApi(routes(analyst, { trail: audit(many, { chain_ok: false, broken_at: 7 }) }));
    renderApp(URL_DAY);
    const trail = await screen.findByRole("region", { name: "Audit trail" });
    expect(await within(trail).findByRole("alert")).toHaveTextContent("Chain broken at entry #7.");
    expect(within(within(trail).getByRole("list", { name: "Latest entries" })).getAllByRole("listitem")).toHaveLength(10);
    expect(within(trail).getByText("Show 4 earlier entries")).toBeInTheDocument();
  });

  it("tells an analyst that only an approver signs off, with no button", async () => {
    mockApi(routes(analyst));
    renderApp(URL_DAY);
    const box = await signBox();
    expect(within(box).getByText("Only an approver can sign off")).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: /Sign off NAV/ })).not.toBeInTheDocument();
  });

  it("tells a viewer the screen is read-only, with no button", async () => {
    mockApi(routes(viewer, { release: READY }));
    renderApp(URL_DAY);
    const box = await signBox();
    expect(within(box).getByText("Read-only")).toBeInTheDocument();
    expect(within(box).getByText(/Viewers can follow the release but cannot sign off/)).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: /Sign off NAV/ })).not.toBeInTheDocument();
  });

  it("keeps the button shut for an approver while conditions are unmet", async () => {
    mockApi(routes(approver));
    renderApp(URL_DAY);
    const box = await signBox();
    expect(within(box).getByText("Blocked")).toBeInTheDocument();
    expect(within(box).getByText("Not ready")).toBeInTheDocument();
    expect(within(box).getByText(/2 conditions are not met yet/)).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: /Sign off NAV/ })).toBeDisabled();
  });

  it("explains four-eyes to an approver who decided cases today", async () => {
    const release = releaseFor("GEF1", "2026-11-10", {
      ready: true,
      reasons: [],
      signable_by_me: false,
      blocking_for_me: [
        { code: "FOUR_EYES", message: "You decided 1 case today, so another approver must sign off.", case_ids: ["C3"] },
      ],
    });
    mockApi(routes({ ...approver, username: "approver1" }, { release, cases: DECIDED }));
    renderApp(URL_DAY);
    const box = await signBox();
    expect(within(box).getByText("Ready to sign off")).toBeInTheDocument();
    expect(within(box).getByText("Four-eyes rule")).toBeInTheDocument();
    expect(within(box).getByText("You decided 1 case today, so another approver must sign off.")).toBeInTheDocument();
    expect(within(within(box).getByRole("list", { name: "Cases you decided" })).getByRole("link", { name: "C3" })).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: /Sign off NAV/ })).toBeDisabled();

    const fourEyes = condition(await conditions(), "FOUR_EYES");
    expect(fourEyes).toHaveAttribute("data-state", "unmet");
    expect(within(fourEyes).getByText("Four-eyes: the signer decided no case today")).toBeInTheDocument();
  });

  it("offers sign-off in the command palette only to an approver who may sign off, and it only opens the confirmation", async () => {
    const api = mockApi(routes(approver, { release: READY, cases: DECIDED }));
    renderApp(URL_DAY);
    await signBox();
    const user = userEvent.setup();
    await user.keyboard("{Control>}k{/Control}");
    const palette = await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("sign off the nav");
    expect(within(palette).getByRole("option", { name: /Sign off the NAV…/ })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Sign off the NAV?" })).toBeInTheDocument();
    expect(api.calls(`POST ${BASE}/signoff`)).toHaveLength(0);
  });

  it("does not offer sign-off in the palette to an analyst", async () => {
    mockApi(routes(analyst, { release: READY, cases: DECIDED }));
    renderApp(URL_DAY);
    await signBox();
    const user = userEvent.setup();
    await user.keyboard("{Control>}k{/Control}");
    const palette = await screen.findByRole("dialog", { name: "Command palette" });
    expect(within(palette).queryByText(/Sign off the NAV/)).not.toBeInTheDocument();
  });

  it("signs off after confirming, then shows the day locked and the next day open", async () => {
    document.cookie = "rp_csrf=token-123; path=/";
    const r = routes(approver, { release: READY, cases: DECIDED });
    let signedOff = false;
    const signedDay = dayRecord("GEF1", "2026-11-10", {
      status: "signed_off",
      signed_off_by: "approver2",
      signed_off_at: "2026-11-10T17:45:00+00:00",
      release: { ready: true, reasons: [] },
    });
    r[`GET ${BASE}`] = () => ({ body: signedOff ? signedDay : dayRecord("GEF1", "2026-11-10") });
    r[`GET ${BASE}/release`] = () => ({
      body: signedOff ? { ...READY, signed_off: true, day_status: "signed_off", signable_by_me: false } : READY,
    });
    r["GET /api/funds/GEF1/days"] = () => ({
      body: daysList(
        "GEF1",
        [
          { as_of: "2026-11-10", status: signedOff ? "signed_off" : "ready" },
          { as_of: "2026-11-09", status: "signed_off" },
        ],
        signedOff ? "2026-11-11" : null,
      ),
    });
    r[`POST ${BASE}/signoff`] = () => {
      signedOff = true;
      return { body: signedDay };
    };
    const api = mockApi(r);
    renderApp(URL_DAY);
    const user = userEvent.setup();

    const box = await signBox();
    expect(within(box).getByText(/Every release condition is met/)).toBeInTheDocument();
    await user.click(within(box).getByRole("button", { name: /Sign off NAV/ }));

    const dialog = await screen.findByRole("dialog", { name: "Sign off the NAV?" });
    expect(within(dialog).getByText("251,234,567.89")).toBeInTheDocument();
    expect(within(dialog).getByText("102.345678")).toBeInTheDocument();
    expect(within(dialog).getByText("3")).toBeInTheDocument();
    expect(api.calls(`POST ${BASE}/signoff`)).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: /Sign off NAV/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const posts = api.calls(`POST ${BASE}/signoff`);
    expect(posts).toHaveLength(1);
    expect(posts[0]?.headers["X-CSRF-Token"]).toBe("token-123");

    const after = await signBox();
    expect(await within(after).findByText(/The day is locked/)).toBeInTheDocument();
    expect(within(after).getByText("approver2")).toBeInTheDocument();
    // The strip agrees.
    const strip = screen.getByRole("region", { name: "NAV and release status" });
    expect(await within(strip).findByText("Signed off")).toBeInTheDocument();
    // The done moment: the day's summary, and the next business day, open for its files, as the one primary.
    const summary = after.querySelector<HTMLElement>(".so-done-summary");
    expect(summary).not.toBeNull();
    expect(within(summary as HTMLElement).getByText("251,234,567.89")).toBeInTheDocument();
    expect(await within(after).findByText("Wed 11 Nov 2026")).toBeInTheDocument();
    expect(within(after).getByText(/is open for its files/)).toBeInTheDocument();
    const next = await within(after).findByRole("button", { name: "Go to the next day" });
    expect(next).toHaveClass("primary");
    await user.click(next);
    await waitFor(() => expect(location()).toContain("day=2026-11-11"));
  });

  it("shows a refused sign-off in the server's words", async () => {
    const r = routes(approver, { release: READY, cases: DECIDED });
    r[`POST ${BASE}/signoff`] = {
      status: 409,
      body: {
        detail: {
          message: "2026-11-10 cannot be signed off yet.",
          reasons: [{ code: "PENDING_DECISIONS", message: "1 case still pending a decision.", case_ids: ["C9"] }],
        },
      },
    };
    mockApi(r);
    renderApp(URL_DAY);
    const user = userEvent.setup();
    await user.click(within(await signBox()).getByRole("button", { name: /Sign off NAV/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Sign off NAV/ }));
    const alert = await within(await signBox()).findByRole("alert");
    expect(alert).toHaveTextContent("2026-11-10 cannot be signed off yet.");
    expect(within(alert).getByText("Pending decisions")).toBeInTheDocument();
    expect(alert).toHaveTextContent("1 case still pending a decision.");
  });

  it("shows a signed-off day as locked, with no button", async () => {
    mockApi(routes(approver));
    renderApp("/signoff?fund=GEF1&day=2026-11-09");
    const box = await signBox();
    expect(await within(box).findByText(/The day is locked/)).toBeInTheDocument();
    expect(within(box).getByText("Signed off")).toBeInTheDocument();
    expect(within(box).queryByRole("button", { name: /Sign off NAV/ })).not.toBeInTheDocument();
    // A later day is already loaded.
    expect(within(box).getByRole("button", { name: "Go to Tue 10 Nov 2026" })).toBeInTheDocument();
    expect(within(await conditions()).getByText("as checked at sign-off")).toBeInTheDocument();
  });

  it("says when the day has not run", async () => {
    const release = releaseFor("GEF1", "2026-11-10", {
      day_status: "validated",
      reasons: [{ code: "NOT_RUN", message: "The day has not been run.", case_ids: [] }],
    });
    const r = routes(approver, { release, trail: audit(TRAIL.slice(0, 2)) });
    r[`GET ${BASE}/overview`] = { body: overview([], { has_run: false, accounted: null, impact: null, run: null }) };
    mockApi(r);
    renderApp(URL_DAY);
    const list = await conditions();
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(within(list).getByText("The day has run")).toBeInTheDocument();
    const box = await signBox();
    expect(within(box).getByText("Not run yet")).toBeInTheDocument();
    expect(within(box).getByRole("button", { name: /Sign off NAV/ })).toBeDisabled();
    expect(await screen.findByText("The day has not run, so it has no cases to decide yet.")).toBeInTheDocument();
  });

  it("says when the day has no files", async () => {
    const r = routes(approver);
    r["GET /api/funds/GEF1/days/2026-11-11"] = { status: 404, body: { detail: "No files have been uploaded for 2026-11-11." } };
    r["GET /api/funds/GEF1/days/2026-11-11/release"] = {
      body: releaseFor("GEF1", "2026-11-11", { reasons: [{ code: "NOT_RUN", message: "The day has no files.", case_ids: [] }] }),
    };
    mockApi(r);
    renderApp("/signoff?fund=GEF1&day=2026-11-11");
    expect(await screen.findByText(/No files have been uploaded for 2026-11-11\. There is nothing to sign off/)).toBeInTheDocument();
  });
});

describe("audit entry details", () => {
  it("words the common actions plainly", () => {
    expect(entryDetail(entry(1, "SIGN_OFF_BLOCKED", { payload: { reasons: [{ code: "FOUR_EYES", cases: [] }] } }))).toBe(
      "Four-eyes rule",
    );
    expect(entryDetail(entry(2, "DAY_SIGNED_OFF", { payload: { cases: 4 } }))).toBe("4 open cases");
    expect(entryDetail(entry(3, "CASE_REJECTED", { payload: { note: "Book is right" } }))).toBe("“Book is right”");
    expect(entryDetail(entry(4, "AI_CALL", { payload: { model: "m1", fallback_used: true } }))).toBe("m1, the rules stand");
    expect(entryDetail(entry(5, "SOMETHING_NEW", { payload: { x: 1 } }))).toBe("");
  });

  it("words the entries the whole audit log adds: exports, chain checks, sign-ins, users and funds", () => {
    const exported = entry(6, "EXPORT_DOWNLOADED", {
      payload: { export: "audit_csv", filename: "audit_GEF1_2026-11-14.csv", rows: 12 },
    });
    expect(entryDetail(exported)).toBe("Audit log, audit_GEF1_2026-11-14.csv, 12 entries");
    expect(entryDetail(entry(7, "EXPORT_DOWNLOADED", { payload: { export: "mi_csv", filename: "mi.csv" } }))).toBe(
      "MI data, mi.csv",
    );
    expect(entryDetail(entry(8, "AUDIT_CHAIN_VERIFIED", { payload: { intact: true, entries: 57 } }))).toBe(
      "intact, 57 entries checked",
    );
    expect(entryDetail(entry(9, "AUDIT_CHAIN_VERIFIED", { payload: { intact: false, broken_at: 4 } }))).toBe(
      "broken at entry #4",
    );
    expect(entryDetail(entry(10, "SIGN_IN_FAILED", { payload: { reason: "wrong password" } }))).toBe("wrong password");
    expect(entryDetail(entry(11, "ACCOUNT_LOCKED", { payload: { failed_logins: 5 } }))).toBe("after 5 failed sign-ins");
    expect(entryDetail(entry(12, "USER_CREATED", { payload: { username: "ann", role: "approver" } }))).toBe(
      "ann, approver",
    );
    expect(entryDetail(entry(13, "FUND_CREATED", { payload: { code: "INC2", name: "Income Fund" } }))).toBe(
      "INC2, Income Fund",
    );
  });
});
