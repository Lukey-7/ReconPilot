import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CaseDetail, EngineCase, QueueCase, User } from "../../api/types";
import { type MockApi, mockApi } from "../../test/mockApi";
import { analyst, approver, dayRecord, location, releaseFor, renderApp, signedInRoutes } from "../../test/render";

const DAY = "2026-11-10";
const BASE = `/cases?fund=GEF1&day=${DAY}`;
const QUEUE = `GET /api/funds/GEF1/days/${DAY}/cases`;
const viewer: User = { username: "viewer1", display_name: "Val Kerr", role: "viewer", is_admin: false };

function row(id: string, overrides: Partial<QueueCase> = {}): QueueCase {
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
    ...overrides,
  };
}

const C1 = row("C1", {
  category: "MISSING_TRADE",
  ai_category: "TIMING",
  ai_flag: "AI disagrees: needs review",
  nav_impact: -45678.9,
  nav_impact_bp: -1.82,
  gross_exposure: 45678.9,
  material: true,
  escalated: true,
  version: 3,
});
const C2 = row("C2", { category: "PRICE_MISMATCH", nav_impact: 12000, nav_impact_bp: 0.48, age_days: 4, age_bucket: "2-5", sla_breached: true });
const C3 = row("C3", { nav_impact: -2500.5, nav_impact_bp: -0.1, status: "APPROVED", version: 2 });

function engineCase(q: QueueCase, overrides: Partial<EngineCase> = {}): EngineCase {
  return {
    case_id: q.case_id,
    security_id: q.security_id,
    category: q.category,
    confidence: 0.82,
    explanation: `Rules explanation for ${q.case_id}.`,
    query_draft: `Rules draft query for ${q.case_id}.`,
    break_ids: [`B-${q.case_id}`],
    status: q.status,
    final_category: q.final_category,
    reviewed_by: q.status === "PENDING" ? "" : "analyst2",
    review_note: "",
    ai_category: q.ai_category,
    ai_confidence: q.ai_category ? 0.71 : null,
    ai_explanation: q.ai_category ? `AI explanation for ${q.case_id}.` : "",
    ai_steps: q.ai_category ? ["Check the trade blotter.", "Ask the custodian for the settlement status."] : [],
    ai_query: q.ai_category ? `AI draft query for ${q.case_id}.` : "",
    ai_model: q.ai_category ? "test-model" : "",
    ai_status: q.ai_category ? "ACCEPTED" : "",
    ai_flag: q.ai_flag,
    ai_fallback_reason: "",
    nav_impact: q.nav_impact,
    nav_impact_bp: q.nav_impact_bp,
    gross_exposure: q.gross_exposure,
    material: q.material,
    break_kinds: ["QUANTITY"],
    first_seen: "2026-11-09",
    age_days: q.age_days,
    age_bucket: q.age_bucket,
    escalated: q.escalated,
    escalation_reason: q.escalated ? "material (-1.82 bp of NAV)" : "",
    sla_days: 3,
    sla_breached: q.sla_breached,
    cleared_on: "",
    clear_reason: "",
    resolved_category: null,
    reviewed_role: q.status === "PENDING" ? "" : "analyst",
    ...overrides,
  };
}

function detailOf(q: QueueCase, overrides: Partial<CaseDetail> = {}, caseOverrides: Partial<EngineCase> = {}): CaseDetail {
  return {
    ...q,
    as_of: DAY,
    day_status: "ready",
    is_open: true,
    case: engineCase(q, caseOverrides),
    security: { security_id: q.security_id, name: q.security_name, currency: "USD", asset_class: "EQUITY" },
    breaks: [
      {
        break_id: `B-${q.case_id}`,
        kind: "QUANTITY",
        security_id: q.security_id,
        book_value: 25900,
        custodian_value: 25000,
        difference: -900,
        reference: "",
        note: "",
      },
    ],
    book_position: { security_id: q.security_id, quantity: 25900, price: 50.75, price_date: DAY, currency: "USD" },
    custodian_holding: { security_id: q.security_id, quantity: 25000, price: 50.75, currency: "USD" },
    book_trades: [],
    book_cash: [],
    custodian_cash: [],
    carried_items: [],
    fx_rate: 1,
    history: [
      {
        type: "audit",
        at: "2026-11-10T08:00:01+00:00",
        seq: 41,
        actor: "analyst1",
        role: "analyst",
        action: "AI_CALL",
        payload: { case_id: q.case_id, model: "test-model", ai_category: q.ai_category, disagrees: !!q.ai_flag },
      },
    ],
    ...overrides,
  };
}

function setup(user: User = analyst, extra: Record<string, Parameters<MockApi["set"]>[1]> = {}): MockApi {
  return mockApi({
    ...signedInRoutes(user),
    [QUEUE]: { body: [C1, C2, C3] },
    "GET /api/funds/GEF1/cases/C1": { body: detailOf(C1) },
    "GET /api/funds/GEF1/cases/C2": { body: detailOf(C2) },
    "GET /api/funds/GEF1/cases/C3": { body: detailOf(C3, {}, { review_note: "Checked with the broker." }) },
    ...extra,
  });
}

async function openCase(id: string) {
  return screen.findByRole("heading", { level: 2, name: id });
}

function queueRows() {
  const table = screen.getByRole("table", { name: /Open cases/ });
  return within(table).getAllByRole("row").slice(1);
}

describe("case workbench", () => {
  it("shows the queue in the server's order with flags as words, and opens the largest case first", async () => {
    setup();
    renderApp(BASE);
    await openCase("C1");
    expect(location()).toBe(`${BASE}&case=C1`);
    const rows = queueRows();
    expect(rows.map((r) => r.getAttribute("data-row-id"))).toEqual(["C1", "C2", "C3"]);
    const first = rows[0] as HTMLElement;
    expect(within(first).getByText("Material")).toBeInTheDocument();
    expect(within(first).getByText("Escalated")).toBeInTheDocument();
    expect(within(first).getByText("AI disagrees")).toBeInTheDocument();
    expect(within(first).getByText("−45,678.90")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("Past SLA")).toBeInTheDocument();
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("3 open cases, 2 pending")).toBeInTheDocument();
  });

  it("puts the rules beside the AI, with the disagreement, steps, draft query, history and evidence", async () => {
    setup();
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    expect(screen.getByText("AI disagrees: needs review")).toBeInTheDocument();
    const rules = screen.getByRole("article", { name: "Rules engine" });
    expect(within(rules).getByText("Missing trade")).toBeInTheDocument();
    expect(within(rules).getByText("Rules explanation for C1.")).toBeInTheDocument();
    const ai = screen.getByRole("article", { name: "AI second opinion" });
    expect(within(ai).getByText("Late settlement")).toBeInTheDocument();
    expect(within(ai).getByText("AI explanation for C1.")).toBeInTheDocument();
    expect(screen.getByText("Check the trade blotter.")).toBeInTheDocument();
    expect(screen.getByText(/Escalated: material \(-1.82 bp of NAV\) \(at escalation\)/)).toBeInTheDocument();
    // The AI's draft first, the rules' draft a tab away.
    expect(screen.getByText("AI draft query for C1.")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Rules draft" }));
    expect(screen.getByText("Rules draft query for C1.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy query" }));
    expect(await navigator.clipboard.readText()).toBe("Rules draft query for C1.");
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    // History from the audit log.
    expect(screen.getByText("#41")).toBeInTheDocument();
    expect(screen.getByText("AI second opinion (test-model)")).toBeInTheDocument();
    // Evidence: book against custodian, and the break.
    const position = screen.getByRole("table", { name: "Position, book against custodian" });
    expect(within(position).getByText("25,900")).toBeInTheDocument();
    expect(within(position).getByText("−900")).toBeInTheDocument();
    expect(within(position).getByText("agrees")).toBeInTheDocument();
    const breaks = screen.getByRole("table", { name: "Breaks in this case" });
    expect(within(breaks).getByText("Quantity")).toBeInTheDocument();
  });

  it("sends the filters and the search to the server and keeps them in the address", async () => {
    const api = setup();
    renderApp(BASE);
    await openCase("C1");
    const user = userEvent.setup();
    api.set(QUEUE, { body: [C1] });
    await user.click(screen.getByRole("button", { name: "Material" }));
    await waitFor(() => expect(api.requests.some((r) => r.url.includes("material=true"))).toBe(true));
    expect(location()).toContain("material=true");
    expect(screen.getByRole("button", { name: "Material" })).toHaveAttribute("aria-pressed", "true");
    await user.selectOptions(screen.getByLabelText("Cause"), "MISSING_TRADE");
    await waitFor(() => expect(api.requests.some((r) => r.url.includes("category=MISSING_TRADE"))).toBe(true));
    await user.type(screen.getByLabelText(/Search cases/), "C1");
    await waitFor(() => expect(location()).toContain("q=C1"));
    expect(api.requests.some((r) => r.url.includes("q=C1"))).toBe(true);
    await user.click(screen.getAllByRole("button", { name: "Clear filters" })[0] as HTMLElement);
    await waitFor(() => expect(location()).toBe(`${BASE}&case=C1`));
  });

  it("approves with the case's version and the note, then refetches the day", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C1/decision", {
      body: detailOf({ ...C1, status: "APPROVED", version: 4 }, {}, { reviewed_by: "analyst1", reviewed_role: "analyst" }),
    });
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Note/), "Agreed with the custodian.");
    const queueCalls = api.calls(QUEUE).length;
    await user.click(screen.getByRole("button", { name: /^Approve/ }));
    expect(await screen.findByText("Approved C1. Recorded in the audit log.")).toBeInTheDocument();
    const [post] = api.calls("POST /api/funds/GEF1/cases/C1/decision");
    expect(post?.body).toEqual({ decision: "approve", note: "Agreed with the custodian.", version: 3 });
    expect(post?.headers).toBeDefined();
    await waitFor(() => expect(api.calls(QUEUE).length).toBeGreaterThan(queueCalls));
    expect(screen.getByLabelText(/^Note/)).toHaveValue("");
  });

  it("will not reject without a note, and rejects with one", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C2/decision", { body: detailOf({ ...C2, status: "REJECTED", version: 2 }) });
    renderApp(`${BASE}&case=C2`);
    await openCase("C2");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /^Reject/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("A rejection needs a note explaining why.");
    expect(screen.getByLabelText(/^Note/)).toHaveFocus();
    expect(api.calls("POST /api/funds/GEF1/cases/C2/decision")).toHaveLength(0);
    await user.type(screen.getByLabelText(/^Note/), "Price is the vendor's stale close.");
    await user.click(screen.getByRole("button", { name: /^Reject/ }));
    expect(await screen.findByText("Rejected C2. Recorded in the audit log.")).toBeInTheDocument();
    expect(api.calls("POST /api/funds/GEF1/cases/C2/decision")[0]?.body).toEqual({
      decision: "reject",
      note: "Price is the vendor's stale close.",
      version: 1,
    });
  });

  it("reclassifies to the cause picked, offering the AI's reading first", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C1/decision", {
      body: detailOf({ ...C1, status: "RECLASSIFIED", final_category: "DIVIDEND", version: 4 }),
    });
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    const user = userEvent.setup();
    expect(screen.getByLabelText("Reclassify as")).toHaveValue("TIMING");
    await user.selectOptions(screen.getByLabelText("Reclassify as"), "DIVIDEND");
    await user.click(screen.getByRole("button", { name: /^Reclassify/ }));
    await waitFor(() =>
      expect(api.calls("POST /api/funds/GEF1/cases/C1/decision")[0]?.body).toEqual({
        decision: "reclassify",
        category: "DIVIDEND",
        note: "",
        version: 3,
      }),
    );
    expect(await screen.findByText("Reclassified C1 as Dividend. Recorded in the audit log.")).toBeInTheDocument();
  });

  it("says plainly when someone else decided first, shows their decision and keeps the note", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C1/decision", () => {
      // Meanwhile another analyst approved it: the case now reads version 4.
      api.set("GET /api/funds/GEF1/cases/C1", {
        body: detailOf({ ...C1, status: "APPROVED", version: 4 }, {}, { reviewed_by: "analyst2", reviewed_role: "analyst" }),
      });
      return { status: 409, body: { detail: "C1 was changed by someone else (version 4, you had 3); reload it." } };
    });
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/^Note/), "My reasoning.");
    await user.click(screen.getByRole("button", { name: /^Approve/ }));
    expect(await screen.findByText(/analyst2 decided this case while you had it open/)).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Not recorded");
    expect(screen.getByLabelText(/^Note/)).toHaveValue("My reasoning.");
    expect(screen.getByText("analyst2")).toBeInTheDocument();
  });

  it("explains a locked day and closes the bar once the day is signed off", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C2/decision", () => {
      api.set("GET /api/funds/GEF1/cases/C2", { body: detailOf(C2, { day_status: "signed_off" }) });
      api.set(`GET /api/funds/GEF1/days/${DAY}`, {
        body: dayRecord("GEF1", DAY, { status: "signed_off", signed_off_by: "approver2" }),
      });
      return { status: 409, body: { detail: `${DAY} is signed off; its cases are locked.` } };
    });
    renderApp(`${BASE}&case=C2`);
    await openCase("C2");
    await userEvent.setup().click(screen.getByRole("button", { name: /^Approve/ }));
    expect(await screen.findByText(/the day was signed off before your decision arrived/)).toBeInTheDocument();
    expect(await screen.findByText(/signed off by approver2\. Its cases are locked\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Approve/ })).toBeNull();
  });

  it("gives viewers the case without a decision bar or decision keys", async () => {
    const api = setup(viewer);
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    expect(screen.getByText(/Read-only\. Viewers can see every case/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Approve/ })).toBeNull();
    expect(screen.queryByLabelText(/^Note/)).toBeNull();
    fireEvent.keyDown(document.body, { key: "a" });
    expect(api.calls("POST /api/funds/GEF1/cases/C1/decision")).toHaveLength(0);
  });

  it("tells an analyst that an escalated case needs an approver, and an approver nothing of the sort", async () => {
    setup(analyst);
    const first = renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    expect(screen.getByText(/an approver must decide this case before sign-off/)).toBeInTheDocument();
    first.unmount();
    setup(approver, { [`GET /api/funds/GEF1/days/${DAY}/release`]: { body: releaseFor("GEF1", DAY) } });
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    expect(screen.queryByText(/an approver must decide this case before sign-off/)).toBeNull();
  });

  it("shows a decided case's decision and a signed-off day as read-only", async () => {
    setup(analyst, {
      "GET /api/funds/GEF1/cases/C3": { body: detailOf(C3, { day_status: "signed_off" }, { review_note: "Checked with the broker." }) },
    });
    renderApp(`${BASE}&case=C3`);
    await openCase("C3");
    const bar = screen.getByRole("region", { name: "Decision" });
    expect(within(bar).getByText("Approved")).toBeInTheDocument();
    expect(within(bar).getByText("analyst2")).toBeInTheDocument();
    expect(within(bar).getByText("Checked with the broker.")).toBeInTheDocument();
    expect(within(bar).getByText(/The NAV for this day is signed off/)).toBeInTheDocument();
  });

  it("moves with j and k, opens with Enter, and decides only a case that is open", async () => {
    const api = setup();
    api.set("POST /api/funds/GEF1/cases/C2/decision", { body: detailOf({ ...C2, status: "APPROVED", version: 2 }) });
    renderApp(BASE);
    await openCase("C1");
    fireEvent.keyDown(document.body, { key: "j" });
    await waitFor(() => expect(queueRows()[1]).toHaveFocus());
    // The cursor is on C2 but C1 is open: the first "a" opens C2 instead of deciding anything.
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "a" });
    await openCase("C2");
    expect(api.calls("POST /api/funds/GEF1/cases/C2/decision")).toHaveLength(0);
    expect(api.calls("POST /api/funds/GEF1/cases/C1/decision")).toHaveLength(0);
    fireEvent.keyDown(document.body, { key: "a" });
    expect(await screen.findByText("Approved C2. Recorded in the audit log.")).toBeInTheDocument();
    // k goes back up, Enter opens.
    fireEvent.keyDown(document.body, { key: "k" });
    await waitFor(() => expect(queueRows()[0]).toHaveFocus());
    fireEvent.keyDown(document.body, { key: "ArrowDown" });
    fireEvent.keyDown(document.body, { key: "ArrowDown" });
    await waitFor(() => expect(queueRows()[2]).toHaveFocus());
    fireEvent.keyDown(document.body, { key: "Enter" });
    await openCase("C3");
    expect(location()).toContain("case=C3");
  });

  it("goes to the search with /, to the note with r and to the cause with c", async () => {
    setup();
    renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    fireEvent.keyDown(document.body, { key: "/" });
    expect(screen.getByLabelText(/Search cases/)).toHaveFocus();
    fireEvent.keyDown(screen.getByLabelText(/Search cases/), { key: "Escape" });
    fireEvent.keyDown(document.body, { key: "r" });
    expect(screen.getByLabelText(/^Note/)).toHaveFocus();
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document.body, { key: "c" });
    expect(screen.getByLabelText("Reclassify as")).toHaveFocus();
  });

  it("collapses and widens the evidence pane, and remembers the choice", async () => {
    setup();
    const { container } = renderApp(`${BASE}&case=C1`);
    await openCase("C1");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Widen" }));
    expect(container.querySelector(".wb")).toHaveClass("wb-ev-wide");
    await user.click(screen.getByRole("button", { name: "Hide" }));
    expect(container.querySelector(".wb")).toHaveClass("wb-ev-collapsed");
    expect(screen.queryByRole("table", { name: "Breaks in this case" })).toBeNull();
    expect(window.localStorage.getItem("rp-evidence-pane")).toBe("collapsed");
    await user.click(screen.getByRole("button", { name: "Show the evidence" }));
    expect(screen.getByRole("table", { name: "Breaks in this case" })).toBeInTheDocument();
  });

  it("says when the day has not been run yet", async () => {
    setup(analyst, { [QUEUE]: { status: 409, body: { detail: `${DAY} has not been run yet.` } } });
    renderApp(BASE);
    expect(await screen.findByText(`${DAY} has not been run yet. Run the day to see its cases.`)).toBeInTheDocument();
    expect(screen.getByText("No cases to show for this day.")).toBeInTheDocument();
  });
});
