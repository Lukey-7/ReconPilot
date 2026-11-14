import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Overview, OverviewCase } from "../../api/types";
import { mockApi } from "../../test/mockApi";
import { approver, location, releaseFor, renderApp, signedInRoutes } from "../../test/render";

const URL_DAY = "/overview?fund=GEF1&day=2026-11-10";
const OVERVIEW = "GET /api/funds/GEF1/days/2026-11-10/overview";

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

const C1 = caseRow("C1", {
  category: "MISSING_TRADE",
  nav_impact: -45678.9,
  nav_impact_bp: -1.82,
  gross_exposure: 45678.9,
  material: true,
  escalated: true,
  escalation_reason: "material (-1.82 bp of NAV)",
  sla_days: 1,
});
const C2 = caseRow("C2", {
  category: "PRICE_MISMATCH",
  nav_impact: 12000,
  nav_impact_bp: 0.48,
  status: "APPROVED",
  reviewed_by: "approver2",
  reviewed_role: "approver",
  age_days: 4,
  age_bucket: "2-5",
  sla_breached: true,
  sla_days: 3,
  first_seen: "2026-11-04",
});
const C3 = caseRow("C3", {
  category: "TIMING",
  final_category: "DIVIDEND",
  status: "RECLASSIFIED",
  nav_impact: -2500.5,
  nav_impact_bp: -0.1,
  age_days: 7,
  age_bucket: ">5",
  escalated: true,
  escalation_reason: "aged: open 6 business days",
  first_seen: "2026-11-01",
});

function overview(overrides: Partial<Overview> = {}): Overview {
  return {
    fund: { code: "GEF1", name: "Global Equity Fund", base_currency: "USD", materiality_bp: 1 },
    as_of: "2026-11-10",
    day_status: "ready",
    has_run: true,
    run_at: "2026-11-10T08:00:00+00:00",
    run_by: "analyst1",
    signed_off_by: null,
    signed_off_at: null,
    nav: {
      nav: 251234567.89,
      nav_per_share: 102.345678,
      prior_nav_per_share: 102.3,
      movement: 0.000446,
      gross_assets: 250000000,
      cash: 1500000,
      liabilities: 265432.11,
    },
    checks: [
      { name: "Every break is held in a case", status: "PASS", detail: "5 of 5 breaks." },
      { name: "NAV movement within tolerance", status: "WARN", detail: "Moved 0.04%." },
    ],
    release: {
      ready: false,
      reasons: [
        { code: "PENDING_DECISIONS", message: "1 case still pending a decision.", case_ids: ["C1"] },
        { code: "MATERIAL_NOT_APPROVED", message: "1 material case not approved or reclassified.", case_ids: ["C1"] },
      ],
    },
    run: { matches: 120, breaks: 5, new_cases: 2, carried_cases: 1 },
    accounted: {
      breaks_found: 5,
      breaks_in_cases: 5,
      breaks_not_in_case: 0,
      open_cases: 3,
      decided: 2,
      approved: 1,
      rejected: 0,
      reclassified: 1,
      pending: 1,
    },
    impact: { cases: [C1, C2, C3], net: -36179.4, gross: 60179.4, gross_exposure: 63179.4, material: 1 },
    ageing: [
      { bucket: "0-1", count: 1, net: -45678.9, gross: 45678.9 },
      { bucket: "2-5", count: 1, net: 12000, gross: 12000 },
      { bucket: ">5", count: 1, net: -2500.5, gross: 2500.5 },
    ],
    sla_breaches: [C2],
    escalations: [C1, C3],
    cleared_today: [
      {
        case_id: "C0",
        security_id: "SEC-C0",
        security_name: "Security C0",
        category: "MISSING_TRADE",
        final_category: null,
        resolved_category: "TIMING",
        status: "PENDING",
        clear_reason: "Custodian settled the booked trade on 2026-11-10: resolved as a late settlement.",
        nav_impact: -800,
        age_days: 1,
        first_seen: "2026-11-09",
        cleared_on: "2026-11-10",
      },
    ],
    trend: [
      {
        as_of: "2026-11-09",
        open_cases: 2,
        new_cases: 2,
        cleared_cases: 0,
        material_open: 1,
        escalated_open: 1,
        sla_breaches_open: 0,
        aged_over_5: 0,
        open_nav_impact: -1000,
        open_gross_impact: 3000,
        avg_days_to_resolve: null,
      },
      {
        as_of: "2026-11-10",
        open_cases: 3,
        new_cases: 2,
        cleared_cases: 1,
        material_open: 1,
        escalated_open: 2,
        sla_breaches_open: 1,
        aged_over_5: 1,
        open_nav_impact: -36179.4,
        open_gross_impact: 60179.4,
        avg_days_to_resolve: 1,
      },
    ],
    ...overrides,
  };
}

function setup(body: Overview | { status: number; body: unknown }, user = signedInRoutes()) {
  const routes = { ...user };
  routes[OVERVIEW] = "status" in body && typeof body.status === "number" ? body : { body };
  return mockApi(routes);
}

function section(name: string) {
  return screen.findByRole("region", { name });
}

describe("Morning overview", () => {
  it("reads the day from the overview route and leads with the release status and its reasons", async () => {
    const api = setup(overview());
    renderApp(URL_DAY);
    const release = await section("Release status");
    expect(within(release).getByText("Blocked")).toBeInTheDocument();
    expect(within(release).getByText("2 things stand between this day and sign-off.")).toBeInTheDocument();
    const reasons = within(release).getByRole("list", { name: "Why release is blocked" });
    expect(within(reasons).getByText("Pending decisions")).toBeInTheDocument();
    expect(within(reasons).getByText("1 material case not approved or reclassified.")).toBeInTheDocument();
    expect(within(reasons).getAllByRole("link", { name: "C1" })[0]).toHaveAttribute(
      "href",
      "/cases?fund=GEF1&day=2026-11-10&case=C1",
    );
    expect(api.calls(OVERVIEW)).toHaveLength(1);
    // The release status is the first section on the screen.
    const regions = screen.getAllByRole("region").filter((r) => r.closest(".ov-grid"));
    expect(regions[0]).toBe(release);
    expect(screen.getByText(/Run by analyst1/)).toBeInTheDocument();
  });

  it("keeps the release checks behind an expander", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const release = await section("Release status");
    const summary = within(release).getByText("Release checks", { selector: "summary" });
    const details = summary.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(within(release).getByText("(1 pass, 1 warning)")).toBeInTheDocument();
    await userEvent.setup().click(summary);
    expect(details).toHaveAttribute("open");
    expect(within(release).getByText("NAV movement within tolerance")).toBeVisible();
  });

  it("accounts for every break the run found", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const acc = await section("Every break accounted for");
    const value = (label: string) => within(acc).getByText(label).closest("div")?.querySelector("dd")?.textContent;
    expect(value("Breaks found by this run")).toBe("5");
    expect(value("Held in a case")).toBe("5");
    expect(value("Not in any case")).toBe("0");
    expect(value("Open cases")).toBe("3");
    expect(value("Pending a decision")).toBe("1");
    expect(value("Decided or pending")).toBe("3");
    expect(within(acc).getByText("All 5 breaks sit in a case; 1 case still waits for a decision.")).toBeInTheDocument();
    expect(within(acc).getByText(/120 matches, 2 new cases, 1 case carried/)).toBeInTheDocument();
  });

  it("flags breaks that are not in any case", async () => {
    setup(
      overview({
        accounted: { ...overview().accounted!, breaks_in_cases: 4, breaks_not_in_case: 1 },
      }),
    );
    renderApp(URL_DAY);
    const acc = await section("Every break accounted for");
    expect(within(acc).getByText(/1 break is not in any case/)).toBeInTheDocument();
  });

  it("stays uncluttered: three impact totals, and the minor sections two to a panel", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const impact = await section("Open breaks by NAV impact");
    const totals = within(impact).getByTestId("impact-gross").closest("dl") as HTMLElement;
    expect(within(totals).getAllByRole("term").map((t) => t.textContent)).toEqual([
      "Gross impact",
      "Net impact",
      "Material",
    ]);
    const panelOf = (name: string) => screen.getByRole("region", { name }).parentElement;
    expect(panelOf("Ageing")).toBe(panelOf("SLA breaches and escalations"));
    expect(panelOf("Trend")).toBe(panelOf("Cleared today"));
    expect(panelOf("Ageing")).toHaveClass("ov-panel");
  });

  it("ranks open breaks by NAV impact and shows gross and net together", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const impact = await section("Open breaks by NAV impact");
    expect(within(impact).getByTestId("impact-gross")).toHaveTextContent("60,179.40 USD");
    expect(within(impact).getByTestId("impact-net")).toHaveTextContent("−36,179.40 USD");
    const rows = within(impact).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("link")[0]?.textContent)).toEqual(["C1", "C2", "C3"]);
    const first = rows[0]!;
    expect(within(first).getByText("Missing trade")).toBeInTheDocument();
    expect(within(first).getByText("Material")).toBeInTheDocument();
    expect(within(first).getByText("−1.82 bp")).toBeInTheDocument();
    expect(within(first).getByText("−45,678.90")).toBeInTheDocument();
    expect(within(first).getByText("Pending")).toBeInTheDocument();
    // A reclassified case shows the cause a person chose.
    expect(within(rows[2]!).getByText("Dividend")).toBeInTheDocument();
  });

  it("opens a case in the workbench when its row is clicked", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const impact = await section("Open breaks by NAV impact");
    const row = within(impact).getByText("Security C2").closest("tr");
    await userEvent.setup().click(row!);
    await waitFor(() => expect(location()).toBe("/cases?fund=GEF1&day=2026-11-10&case=C2"));
  });

  it("shows the ten largest open breaks and the rest on demand", async () => {
    const cases = Array.from({ length: 12 }, (_, i) =>
      caseRow(`K${String(i + 1).padStart(2, "0")}`, { nav_impact: -(1000 - i), nav_impact_bp: -0.04 }),
    );
    setup(overview({ impact: { cases, net: -11934, gross: 11934, gross_exposure: 60000, material: 0 } }));
    renderApp(URL_DAY);
    const impact = await section("Open breaks by NAV impact");
    expect(within(impact).getAllByRole("row")).toHaveLength(11);
    await userEvent.setup().click(within(impact).getByRole("button", { name: "Show all 12 open cases" }));
    expect(within(impact).getAllByRole("row")).toHaveLength(13);
    expect(within(impact).getByRole("button", { name: "Show the 10 largest" })).toHaveAttribute("aria-expanded", "true");
  });

  it("shows ageing buckets with gross and net, linking to the queue by age", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const age = await section("Ageing");
    const over5 = within(age).getByRole("row", { name: /Over 5 days/ });
    expect(within(over5).getByText("2,500.50")).toBeInTheDocument();
    expect(within(over5).getByText("−2,500.50")).toBeInTheDocument();
    expect(within(over5).getByRole("link", { name: "Over 5 days" })).toHaveAttribute(
      "href",
      "/cases?fund=GEF1&day=2026-11-10&age=%3E5",
    );
  });

  it("lists SLA breaches and escalations, with the reason recorded at escalation", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const att = await section("SLA breaches and escalations");
    const sla = within(att).getByRole("list", { name: /Past SLA/ });
    expect(within(sla).getByRole("link", { name: "C2" })).toBeInTheDocument();
    expect(within(sla).getByText(/Open 4 business days, SLA 3 days/)).toBeInTheDocument();
    const esc = within(att).getByRole("list", { name: /Escalated/ });
    expect(within(esc).getAllByRole("listitem")).toHaveLength(2);
    expect(within(esc).getAllByText("At escalation:")).toHaveLength(2);
    expect(within(esc).getByText(/Material \(-1\.82 bp of NAV\)/)).toBeInTheDocument();
  });

  it("shows what cleared today and why", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const cleared = await section("Cleared today");
    expect(within(cleared).getByRole("link", { name: "C0" })).toHaveAttribute(
      "href",
      "/cases?fund=GEF1&day=2026-11-10&case=C0",
    );
    expect(within(cleared).getByText("Late settlement")).toBeInTheDocument();
    expect(within(cleared).getByText(/Custodian settled the booked trade/)).toBeInTheDocument();
  });

  it("shows a small trend with its figures on demand", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const trend = await section("Trend");
    expect(within(trend).getByText("Open cases up 1 since 9 Nov, to 3.")).toBeInTheDocument();
    expect(within(trend).getByRole("img", { name: "Open cases per run day, 9 Nov to 10 Nov" })).toBeInTheDocument();
    expect(within(trend).getByText("Show the figures").closest("details")).not.toHaveAttribute("open");
    const today = within(trend).getByRole("row", { name: /Tue 10 Nov 2026/ });
    expect(today).toHaveAttribute("aria-current", "date");
  });

  it("gives each run day's open impact gross beside net, and opens an earlier day", async () => {
    setup(overview());
    renderApp(URL_DAY);
    const trend = await section("Trend");
    const first = within(trend).getByRole("row", { name: /Mon 9 Nov 2026/ });
    expect(within(first).getByText("3,000.00")).toBeInTheDocument();
    expect(within(first).getByText("net −1,000.00")).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: "Mon 9 Nov 2026" })).toHaveAttribute(
      "href",
      "/overview?fund=GEF1&day=2026-11-09",
    );
    const today = within(trend).getByRole("row", { name: /Tue 10 Nov 2026/ });
    expect(within(today).getByText("60,179.40")).toBeInTheDocument();
    expect(within(today).queryByRole("link")).toBeNull();
  });

  it("explains a day that has not been run, and still shows the trend", async () => {
    setup(
      overview({
        day_status: "validated",
        has_run: false,
        run_at: null,
        run_by: null,
        nav: null,
        checks: [],
        release: { ready: false, reasons: [{ code: "NOT_RUN", message: "The day has not been run.", case_ids: [] }] },
        run: null,
        accounted: null,
        impact: null,
        ageing: [
          { bucket: "0-1", count: 0, net: 0, gross: 0 },
          { bucket: "2-5", count: 0, net: 0, gross: 0 },
          { bucket: ">5", count: 0, net: 0, gross: 0 },
        ],
        sla_breaches: [],
        escalations: [],
        cleared_today: [],
        trend: overview().trend.slice(0, 1),
      }),
    );
    renderApp(URL_DAY);
    const release = await section("Release status");
    expect(within(release).getByText("Not run")).toBeInTheDocument();
    expect(within(release).getByText("The day has not been run.")).toBeInTheDocument();
    const notRun = await section("Not run yet");
    expect(within(notRun).getByText("Validated, not run.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Open breaks by NAV impact" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Every break accounted for" })).not.toBeInTheDocument();
    expect(within(await section("Trend")).getByText("2 open cases on the first run day.")).toBeInTheDocument();
    expect(screen.queryByText(/Run by/)).not.toBeInTheDocument();
  });

  it("shows a clean day plainly: ready, nothing open, nothing late", async () => {
    setup(
      overview({
        release: { ready: true, reasons: [] },
        checks: [{ name: "Every break is held in a case", status: "PASS", detail: "No breaks." }],
        run: { matches: 125, breaks: 0, new_cases: 0, carried_cases: 0 },
        accounted: {
          breaks_found: 0,
          breaks_in_cases: 0,
          breaks_not_in_case: 0,
          open_cases: 0,
          decided: 0,
          approved: 0,
          rejected: 0,
          reclassified: 0,
          pending: 0,
        },
        impact: { cases: [], net: 0, gross: 0, gross_exposure: 0, material: 0 },
        ageing: [
          { bucket: "0-1", count: 0, net: 0, gross: 0 },
          { bucket: "2-5", count: 0, net: 0, gross: 0 },
          { bucket: ">5", count: 0, net: 0, gross: 0 },
        ],
        sla_breaches: [],
        escalations: [],
        cleared_today: [],
      }),
      signedInRoutes(approver),
    );
    renderApp(URL_DAY);
    const release = await section("Release status");
    expect(within(release).getByText("Ready to sign off")).toBeInTheDocument();
    expect(within(release).getByText("Every release condition is met. An approver can sign off the NAV.")).toBeInTheDocument();
    expect(within(release).queryByRole("list", { name: "Why release is blocked" })).not.toBeInTheDocument();
    expect(within(await section("Every break accounted for")).getByText("The run found no breaks; no case is open.")).toBeInTheDocument();
    const impact = await section("Open breaks by NAV impact");
    expect(within(impact).getByText(/No open breaks/)).toBeInTheDocument();
    expect(within(impact).getByTestId("impact-gross")).toHaveTextContent("0.00 USD");
    expect(within(impact).getByTestId("impact-net")).toHaveTextContent("0.00 USD");
    expect(within(await section("Ageing")).getByText("No case is open.")).toBeInTheDocument();
    expect(within(await section("Ageing")).queryByRole("link")).not.toBeInTheDocument();
    expect(within(await section("SLA breaches and escalations")).getByText(/No open case is past its SLA/)).toBeInTheDocument();
    expect(within(await section("Cleared today")).getByText(/No case cleared/)).toBeInTheDocument();
  });

  it("says who signed off a signed-off day", async () => {
    setup(
      overview({
        day_status: "signed_off",
        signed_off_by: "approver2",
        signed_off_at: "2026-11-10T18:02:00+00:00",
        release: { ready: true, reasons: [] },
      }),
    );
    renderApp(URL_DAY);
    const release = await section("Release status");
    expect(within(release).getByText("Signed off")).toBeInTheDocument();
    expect(within(release).getByText(/Signed off by approver2, .*The day is locked\./)).toBeInTheDocument();
  });

  it("says when the day has no files, in the server's words", async () => {
    const routes = signedInRoutes();
    routes["GET /api/funds/GEF1/days/2026-11-10/release"] = {
      body: releaseFor("GEF1", "2026-11-10", { reasons: [{ code: "NOT_RUN", message: "The day has no files.", case_ids: [] }] }),
    };
    setup({ status: 404, body: { detail: "No files have been uploaded for 2026-11-10." } }, routes);
    renderApp(URL_DAY);
    expect(await screen.findByText(/No files have been uploaded for 2026-11-10\. Upload the day/)).toBeInTheDocument();
  });

  it("offers to try again when the overview cannot be loaded", async () => {
    setup({ status: 500, body: { detail: "The database is unavailable." } });
    renderApp(URL_DAY);
    expect(await screen.findByRole("alert")).toHaveTextContent("The database is unavailable.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("leads to upload and run when the day has no files", async () => {
    setup({ status: 404, body: { detail: "No files have been uploaded for 2026-11-10." } });
    renderApp(URL_DAY);
    expect(await screen.findByRole("link", { name: "Upload the day’s files" })).toHaveAttribute(
      "href",
      "/upload?fund=GEF1&day=2026-11-10",
    );
  });
});
