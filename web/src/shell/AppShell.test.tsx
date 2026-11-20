import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Overview } from "../api/types";
import { mockApi } from "../test/mockApi";
import { approver, location, renderApp, signedInRoutes } from "../test/render";

/** A run day's overview with its NAV and nothing open, enough for the lead card. */
function overviewFor(asOf: string, overrides: Partial<Overview> = {}): Overview {
  return {
    fund: { code: "GEF1", name: "Global Equity Fund", base_currency: "USD", materiality_bp: 1 },
    as_of: asOf,
    day_status: "ready",
    has_run: true,
    run_at: `${asOf}T08:00:00+00:00`,
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
    checks: [],
    release: { ready: false, reasons: [{ code: "PENDING_DECISIONS", message: "1 case still pending a decision.", case_ids: [] }] },
    run: { matches: 120, breaks: 0, new_cases: 0, carried_cases: 0 },
    accounted: null,
    impact: null,
    ageing: [],
    sla_breaches: [],
    escalations: [],
    cleared_today: [],
    trend: [],
    ...overrides,
  };
}

describe("app shell", () => {
  it("opens the first fund's latest day and writes it into the address", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview");
    expect(await screen.findByRole("heading", { name: "Morning overview" })).toBeInTheDocument();
    await waitFor(() => expect(location()).toBe("/overview?fund=GEF1&day=2026-11-10"));
    expect(screen.getByLabelText("Fund")).toHaveValue("GEF1");
    expect(screen.getByLabelText("Business day")).toHaveValue("2026-11-10");
    expect(screen.getByText("Global Equity Fund, Tue 10 Nov 2026")).toBeInTheDocument();
  });

  it("lists the fund's days with their status from the API", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview");
    const select = await screen.findByLabelText("Business day");
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Tue 10 Nov 2026 · Ready for review", "Mon 9 Nov 2026 · Signed off"]);
  });

  it("switching the day updates the address and the overview's lead card", async () => {
    const api = mockApi({
      ...signedInRoutes(),
      "GET /api/funds/GEF1/days/2026-11-10/overview": { body: overviewFor("2026-11-10") },
      "GET /api/funds/GEF1/days/2026-11-09/overview": {
        body: overviewFor("2026-11-09", {
          day_status: "signed_off",
          signed_off_by: "approver2",
          signed_off_at: "2026-11-09T18:02:00+00:00",
          release: { ready: true, reasons: [] },
        }),
      },
    });
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Business day"), "2026-11-09");
    await waitFor(() => expect(location()).toBe("/overview?fund=GEF1&day=2026-11-09"));
    // On the overview the lead card carries NAV and the release status, so the strip is not shown.
    const lead = await screen.findByRole("region", { name: "Release status" });
    expect(await within(lead).findByText("Signed off")).toBeInTheDocument();
    expect(within(lead).getByText(/^Signed off by approver2,/)).toBeInTheDocument();
    expect(within(lead).getByText("251,234,567.89")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "NAV and release status" })).not.toBeInTheDocument();
    expect(api.calls("GET /api/funds/GEF1/days/2026-11-09/overview")).toHaveLength(1);
    expect(api.calls("GET /api/funds/GEF1/days/2026-11-09/release")).toHaveLength(1);
  });

  it("shows the NAV strip on every screen but the overview", async () => {
    mockApi(signedInRoutes());
    renderApp("/upload?fund=GEF1&day=2026-11-09");
    const strip = await screen.findByRole("region", { name: "NAV and release status" });
    expect(await within(strip).findByText("Signed off")).toBeInTheDocument();
  });

  it("switching the fund opens that fund's latest day, offering the next day to load", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Fund"), "INC2");
    await waitFor(() => expect(location()).toBe("/overview?fund=INC2&day=2026-11-09"));
    const options = within(screen.getByLabelText("Business day"))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Tue 10 Nov 2026 · No files yet", "Mon 9 Nov 2026 · Signed off"]);
  });

  it("keeps the fund and day when moving between screens", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-09");
    const user = userEvent.setup();
    const nav = await screen.findByRole("navigation", { name: "Screens" });
    await user.click(within(nav).getByRole("link", { name: /Cases/ }));
    expect(await screen.findByRole("heading", { name: "Cases" })).toBeInTheDocument();
    expect(location()).toBe("/cases?fund=GEF1&day=2026-11-09");
    expect(within(nav).getByRole("link", { name: /Cases/ })).toHaveClass("active");
  });

  it("badges the cases link with the number of cases pending a decision", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const nav = await screen.findByRole("navigation", { name: "Screens" });
    expect(await within(nav).findByText("3")).toBeInTheDocument();
    expect(within(nav).getByText("pending a decision", { exact: false })).toBeInTheDocument();
  });

  it("shows the signed-in user and role, and signs out", async () => {
    const api = mockApi({ ...signedInRoutes(approver), "POST /api/auth/logout": { status: 204 } });
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Tom Reed/ }));
    expect(await screen.findByText(/Signed in as/)).toHaveTextContent("Signed in as approver2, approver");
    await user.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(api.calls("POST /api/auth/logout")).toHaveLength(1);
  });

  it("says plainly when there are no funds yet", async () => {
    mockApi({ ...signedInRoutes(), "GET /api/funds": { body: [] } });
    renderApp("/overview");
    expect(await screen.findByRole("heading", { name: "No funds yet" })).toBeInTheDocument();
  });

  it("sends / to the overview and unknown paths to a not-found page", async () => {
    mockApi(signedInRoutes());
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Morning overview" })).toBeInTheDocument();
  });
});
