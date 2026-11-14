import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Mi, MiBlock, MiTrendDay } from "../../api/types";
import { mockApi } from "../../test/mockApi";
import { fundA, fundDetail, location, renderApp, signedInRoutes } from "../../test/render";

const MI_URL = "/api/funds/GEF1/days/2026-11-10/mi";
const REPORT_URL = "/api/funds/GEF1/days/2026-11-10/exports/report.xlsx";
const CSV_URL = "/api/funds/GEF1/days/2026-11-10/exports/mi.csv";

function block(counts: [number, number, number], net: number, gross: number): MiBlock {
  const buckets = ["0-1", "2-5", ">5"];
  return {
    count: counts[0] + counts[1] + counts[2],
    net,
    gross,
    cells: counts.map((count, i) => ({
      bucket: buckets[i] ?? "",
      count,
      net: count ? net / 3 : 0,
      gross: count ? gross / 3 : 0,
    })),
  };
}

function trendDay(asOf: string, open: number, cleared: number): MiTrendDay {
  return {
    as_of: asOf,
    open_cases: open,
    new_cases: open - 1,
    cleared_cases: cleared,
    material_open: 1,
    escalated_open: 1,
    sla_breaches_open: 0,
    aged_over_5: 0,
    open_nav_impact: -1234.5,
    open_gross_impact: 5678.25,
    avg_days_to_resolve: cleared ? 1.5 : null,
  };
}

function miFixture(overrides: Partial<Mi> = {}): Mi {
  return {
    fund: { code: "GEF1", name: "Global Equity Fund", base_currency: "USD", materiality_bp: 1 },
    as_of: "2026-11-10",
    day_status: "ready",
    has_run: true,
    run_days: 2,
    by_cause_age: {
      buckets: ["0-1", "2-5", ">5"],
      rows: [
        { cause: "TIMING", ...block([2, 1, 0], -3000, 9000) },
        { cause: "DIVIDEND", ...block([0, 0, 1], 1500, 1500) },
      ],
      total: block([2, 1, 1], -1500, 10500),
    },
    time_to_resolve: {
      rows: [
        { cause: "TIMING", cleared: 3, avg_days: 1.33 },
        { cause: "PRICE_MISMATCH", cleared: 1, avg_days: 2 },
      ],
      all: { cleared: 4, avg_days: 1.5 },
    },
    top_open: [
      {
        case_id: "EX-20261109-001",
        security_id: "US0000000001",
        security_name: "Acme Holdings",
        cause: "TIMING",
        nav_impact: -6000,
        nav_impact_bp: -2.39,
        age_days: 1,
        material: true,
        escalated: true,
        sla_breached: false,
        status: "PENDING",
      },
    ],
    sla_breaches: [
      {
        case_id: "EX-20261109-003",
        security_id: "US0000000003",
        security_name: "Borealis Mining",
        cause: "DIVIDEND",
        age_days: 6,
        sla_days: 5,
        material: false,
        status: "APPROVED",
        cleared_on: null,
      },
      {
        case_id: "EX-20261109-004",
        security_id: "US0000000004",
        security_name: "Cobalt Rail",
        cause: "TIMING",
        age_days: 3,
        sla_days: 2,
        material: true,
        status: "APPROVED",
        cleared_on: "2026-11-10",
      },
    ],
    trend: [trendDay("2026-11-09", 3, 0), trendDay("2026-11-10", 4, 2)],
    exports: { report: REPORT_URL, mi_csv: CSV_URL },
    ...overrides,
  };
}

function routes(mi: Mi = miFixture()) {
  return { ...signedInRoutes(), [`GET ${MI_URL}`]: { body: mi } };
}

async function openMi() {
  renderApp("/mi?fund=GEF1&day=2026-11-10");
  return screen.findByRole("heading", { level: 1, name: "Management information" });
}

describe("MiScreen", () => {
  it("shows open breaks by cause and age with gross beside net and a total row", async () => {
    mockApi(routes());
    await openMi();
    const section = await screen.findByRole("region", { name: "Open breaks by cause and age" });
    const [matrix] = within(section).getAllByRole("table");
    const headers = within(matrix!).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Cause", "0 to 1 day", "2 to 5 days", "Over 5 days", "Total", "Gross impact USD", "Net impact USD"]);
    const rows = within(matrix!).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "Late settlement",
      "Dividend",
      "All causes",
    ]);
    expect(rows[0]).toHaveTextContent(/2\s*1\s*0\s*3\s*9,000\.00\s*−3,000\.00/);
    expect(rows[2]).toHaveTextContent(/4\s*10,500\.00\s*−1,500\.00/);
    expect(within(section).getByText("4 open cases, age in business days")).toBeInTheDocument();
    // The impact per bucket is on demand, still gross beside net.
    const more = within(section).getByText("Show the impact by age");
    expect(more.closest("details")).not.toHaveAttribute("open");
    const byAge = within(section).getAllByRole("table")[1]!;
    expect(within(byAge).getAllByRole("columnheader", { name: "Gross" })).toHaveLength(3);
    expect(within(byAge).getAllByRole("columnheader", { name: "Net" })).toHaveLength(3);
  });

  it("switches the trend between measures, keeping every figure behind an expander", async () => {
    mockApi(routes());
    const user = userEvent.setup();
    await openMi();
    const section = await screen.findByRole("region", { name: "Trend" });
    expect(within(section).getByText("2 run days, 9 Nov to 10 Nov")).toBeInTheDocument();
    expect(within(section).getByRole("img", { name: "Open cases per run day, 9 Nov to 10 Nov" })).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Open" })).toHaveAttribute("aria-pressed", "true");
    await user.click(within(section).getByRole("button", { name: "Cleared" }));
    expect(within(section).getByRole("button", { name: "Cleared" })).toHaveAttribute("aria-pressed", "true");
    expect(within(section).getByRole("button", { name: "Open" })).toHaveAttribute("aria-pressed", "false");
    expect(within(section).getByRole("img", { name: "Cleared cases per run day, 9 Nov to 10 Nov" })).toBeInTheDocument();

    const table = within(section).getByRole("table");
    const last = within(table).getAllByRole("row")[2]!;
    expect(last).toHaveAttribute("aria-current", "date");
    expect(last).toHaveTextContent("Tue 10 Nov 2026");
    expect(last).toHaveTextContent("5,678.25");
    expect(last).toHaveTextContent("−1,234.50");
    expect(last).toHaveTextContent("1.50");
  });

  it("lists time to resolve by cause, the largest open breaks and SLA breaches", async () => {
    mockApi(routes());
    await openMi();
    const resolve = await screen.findByRole("region", { name: "Time to resolve" });
    expect(within(resolve).getByText("4 cases cleared so far")).toBeInTheDocument();
    const resolveRows = within(resolve).getAllByRole("row").slice(1);
    expect(resolveRows[0]).toHaveTextContent(/Late settlement\s*3\s*1\.33/);
    expect(resolveRows[2]).toHaveTextContent(/All causes\s*4\s*1\.50/);

    const top = screen.getByRole("region", { name: "Largest open breaks" });
    const link = within(top).getByRole("link", { name: "EX-20261109-001" });
    expect(link).toHaveAttribute("href", "/cases?fund=GEF1&day=2026-11-10&case=EX-20261109-001");
    const topRow = link.closest("tr")!;
    expect(topRow).toHaveTextContent("Acme Holdings");
    expect(topRow).toHaveTextContent("−2.39 bp");
    expect(topRow).toHaveTextContent("−6,000.00");
    expect(within(topRow).getByText("Material")).toBeInTheDocument();
    expect(within(topRow).getByText("Escalated")).toBeInTheDocument();
    expect(within(topRow).getByText("Pending")).toBeInTheDocument();

    const sla = screen.getByRole("region", { name: "SLA breaches" });
    expect(within(sla).getByText("1 still open, 1 since cleared")).toBeInTheDocument();
    const [open, cleared] = within(sla).getAllByRole("row").slice(1);
    expect(within(open!).getByRole("link", { name: "EX-20261109-003" })).toBeInTheDocument();
    expect(within(open!).getByText("Past SLA")).toBeInTheDocument();
    expect(open).toHaveTextContent(/Dividend.*6\s*5/);
    // A breach that has since cleared is history: no link into today's queue.
    expect(within(cleared!).queryByRole("link")).not.toBeInTheDocument();
    expect(within(cleared!).getByText("Cleared")).toBeInTheDocument();
    expect(cleared).toHaveTextContent("Tue 10 Nov 2026");
  });

  it("says when a day has not been run, offers no exports and still shows the earlier trend", async () => {
    mockApi(
      routes(
        miFixture({
          has_run: false,
          day_status: "validated",
          run_days: 1,
          by_cause_age: { buckets: ["0-1", "2-5", ">5"], rows: [], total: block([0, 0, 0], 0, 0) },
          time_to_resolve: { rows: [], all: { cleared: 0, avg_days: null } },
          top_open: [],
          sla_breaches: [],
          trend: [trendDay("2026-11-09", 3, 0)],
          exports: null,
        }),
      ),
    );
    await openMi();
    expect(await screen.findByRole("heading", { name: "Not run yet" })).toBeInTheDocument();
    expect(screen.getByText("Validated, not run.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to upload and run" })).toHaveAttribute(
      "href",
      "/upload?fund=GEF1&day=2026-11-10",
    );
    expect(screen.queryByRole("button", { name: /Exception report/ })).not.toBeInTheDocument();
    const trend = screen.getByRole("region", { name: "Trend" });
    expect(within(trend).getByText("Mon 9 Nov 2026, the only run day so far")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Open breaks by cause and age" })).not.toBeInTheDocument();
  });

  it("explains a day without files", async () => {
    mockApi({ ...signedInRoutes(), [`GET ${MI_URL}`]: { status: 404, body: { detail: "No files have been uploaded for 2026-11-10." } } });
    await openMi();
    expect(
      await screen.findByText("No files have been uploaded for 2026-11-10. Management information starts once the day has been run."),
    ).toBeInTheDocument();
  });

  describe("exports", () => {
    let clicked: { href: string; download: string }[];

    beforeEach(() => {
      clicked = [];
      vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:mi-test"), revokeObjectURL: vi.fn() }));
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push({ href: this.href, download: this.download });
      });
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("downloads the exception report and the MI data under the server's file names", async () => {
      const api = mockApi({
        ...routes(),
        [`GET ${REPORT_URL}`]: {
          body: "xlsx bytes",
          headers: {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "Content-Disposition": 'attachment; filename="exceptions_GEF1_2026-11-10.xlsx"',
          },
        },
        [`GET ${CSV_URL}`]: {
          body: "as_of,metric,cause,age_bucket,value\r\n",
          headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": 'attachment; filename="mi_GEF1_2026-11-10.csv"' },
        },
      });
      const user = userEvent.setup();
      await openMi();
      const exports = await screen.findByRole("group", { name: "Exports for this day" });
      await user.click(within(exports).getByRole("button", { name: /Exception report/ }));
      expect(await screen.findByText("Downloaded exceptions_GEF1_2026-11-10.xlsx.")).toBeInTheDocument();
      await user.click(within(exports).getByRole("button", { name: /MI data/ }));
      expect(await screen.findByText("Downloaded mi_GEF1_2026-11-10.csv.")).toBeInTheDocument();
      expect(clicked).toEqual([
        { href: "blob:mi-test", download: "exceptions_GEF1_2026-11-10.xlsx" },
        { href: "blob:mi-test", download: "mi_GEF1_2026-11-10.csv" },
      ]);
      expect(api.calls(`GET ${REPORT_URL}`)[0]?.credentials).toBe("include");
      expect(api.calls(`GET ${CSV_URL}`)).toHaveLength(1);
    });

    it("shows a refused export in the server's words and saves nothing", async () => {
      mockApi({
        ...routes(),
        [`GET ${REPORT_URL}`]: {
          status: 409,
          body: { detail: "2026-11-10 has no finished run to export yet; run the day first." },
        },
      });
      const user = userEvent.setup();
      await openMi();
      await user.click(await screen.findByRole("button", { name: /Exception report/ }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "2026-11-10 has no finished run to export yet; run the day first.",
      );
      expect(clicked).toEqual([]);
    });
  });

  it("is reached from the screen list and with g m, keeping the fund and day", async () => {
    mockApi({ ...routes(), "GET /api/funds/GEF1": { body: fundDetail(fundA) } });
    const user = userEvent.setup();
    renderApp("/funds?fund=GEF1&day=2026-11-10");
    await screen.findByRole("heading", { level: 1, name: "Funds" });
    const nav = screen.getByRole("navigation", { name: "Screens" });
    await waitFor(() =>
      expect(within(nav).getByRole("link", { name: /MI/ })).toHaveAttribute("href", "/mi?fund=GEF1&day=2026-11-10"),
    );
    await user.keyboard("gm");
    await waitFor(() => expect(location()).toBe("/mi?fund=GEF1&day=2026-11-10"));
    expect(await screen.findByRole("heading", { level: 1, name: "Management information" })).toBeInTheDocument();
  });
});
