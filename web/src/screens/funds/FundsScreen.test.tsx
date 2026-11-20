import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi } from "../../test/mockApi";
import { fundA, fundB, fundDetail, location, renderApp, signedInRoutes } from "../../test/render";

function routes() {
  return {
    ...signedInRoutes(),
    "GET /api/funds/GEF1": { body: fundDetail(fundA, { non_business_dates: ["2026-11-26", "2026-12-25"] }) },
    "GET /api/funds/INC2": {
      body: fundDetail(fundB, {
        settings: {
          materiality_bp: 0.5,
          escalate_after_days: 3,
          sla_days_material: 1,
          sla_days_other: 4,
          ai_enabled: true,
          check_settings: { cash_tolerance: 5 },
        },
        checks_in_force: {
          max_price_age_days: 1,
          movement_threshold: 0.02,
          cash_tolerance: 5,
          price_move_limits: { EQUITY: 0.1, BOND: 0.02 },
        },
      }),
    },
  };
}

describe("FundsScreen", () => {
  it("lists every fund with its latest day and status, marking the one being worked", async () => {
    mockApi(routes());
    renderApp("/funds?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("heading", { level: 1, name: "Funds" })).toBeInTheDocument();
    expect(screen.getByText("2 funds; working GEF1, Global Equity Fund")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /Every fund/ });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("GEF1");
    expect(rows[0]).toHaveTextContent("Tue 10 Nov 2026");
    expect(rows[0]).toHaveTextContent("Ready for review");
    expect(rows[0]).toHaveTextContent("Working");
    expect(rows[0]).toHaveAttribute("aria-current", "true");
    expect(rows[1]).toHaveTextContent("Income Fund");
    expect(rows[1]).toHaveTextContent("Signed off");
    expect(within(rows[1]!).getByRole("button", { name: "Work this fund: INC2" })).toBeInTheDocument();
  });

  it("shows the fund's settings read-only, with the engine's defaults named as such", async () => {
    mockApi(routes());
    renderApp("/funds?fund=GEF1&day=2026-11-10");
    const settings = await screen.findByRole("region", { name: /Settings for GEF1/ });
    expect(within(settings).getByText("Read-only")).toBeInTheDocument();
    expect(within(settings).getByText("1.00 bp of NAV")).toBeInTheDocument();
    expect(within(settings).getByText("Open longer than 5 business days")).toBeInTheDocument();
    expect(within(settings).getByText("2 business days")).toBeInTheDocument();
    expect(within(settings).getByText("Off")).toBeInTheDocument();
    expect(within(settings).getByText("Warn beyond 2.00% a day")).toBeInTheDocument();
    expect(within(settings).getByText("1.00 USD")).toBeInTheDocument();
    expect(within(settings).getByText("Equity 10.00%, Bond 2.00%")).toBeInTheDocument();
    expect(within(settings).getAllByText("Engine default")).toHaveLength(4);
    const nonBusiness = within(settings).getByRole("list", { name: "Non-business days" });
    expect(within(nonBusiness).getAllByRole("listitem").map((d) => d.textContent)).toEqual([
      "Thu 26 Nov 2026",
      "Fri 25 Dec 2026",
    ]);
    // Nothing on the screen edits a setting.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(within(settings).queryByRole("button")).not.toBeInTheDocument();
  });

  it("switches to another fund, stores the choice and shows that fund's settings", async () => {
    const api = mockApi(routes());
    const user = userEvent.setup();
    renderApp("/funds?fund=GEF1&day=2026-11-10");
    await user.click(await screen.findByRole("button", { name: "Work this fund: INC2" }));
    await waitFor(() => expect(location()).toBe("/funds?fund=INC2&day=2026-11-09"));
    expect(api.calls("PUT /api/auth/me/preferences")[0]?.body).toEqual({ fund: "INC2" });
    const settings = await screen.findByRole("region", { name: /Settings for INC2/ });
    expect(within(settings).getByText("0.50 bp of NAV")).toBeInTheDocument();
    expect(within(settings).getByText("On")).toBeInTheDocument();
    expect(within(settings).getByText("5.00 USD")).toBeInTheDocument();
    expect(within(settings).getAllByText("This fund")).toHaveLength(1);
    expect(within(settings).getByText("Weekends only")).toBeInTheDocument();
  });

  it("says so when the fund's settings cannot be read", async () => {
    mockApi({ ...routes(), "GET /api/funds/GEF1": { status: 500, body: { detail: "Database unavailable." } } });
    renderApp("/funds?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable.");
  });
});
