import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi } from "../test/mockApi";
import { dayRecord, releaseFor, renderApp, signedInRoutes } from "../test/render";

// The strip sits under the top bar on every screen but the overview; upload is one of them.
const URL_DAY2 = "/upload?fund=GEF1&day=2026-11-10";

function strip() {
  return screen.findByRole("region", { name: "NAV and release status" });
}

describe("NAV strip", () => {
  it("shows the day's NAV, NAV per share and movement from the API", async () => {
    mockApi(signedInRoutes());
    renderApp(URL_DAY2);
    expect(await within(await strip()).findByText("251,234,567.89")).toHaveAttribute("data-testid", "strip-nav");
    expect(screen.getByTestId("strip-nps")).toHaveTextContent("102.345678");
    const s = await strip();
    expect(within(s).getByText("NAV, USD")).toBeInTheDocument();
    expect(within(s).getByText("+0.045%")).toBeInTheDocument();
    expect(within(s).getByText("Up", { exact: false })).toBeInTheDocument();
  });

  it("shows a blocked release with its first reason, and every reason on demand", async () => {
    mockApi(signedInRoutes());
    renderApp(URL_DAY2);
    const s = await strip();
    expect(await within(s).findByText("Blocked")).toBeInTheDocument();
    expect(within(s).getByText("3 cases still pending a decision.")).toBeInTheDocument();
    expect(within(s).getByText("and 1 more")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(within(s).getByRole("button", { name: /All 2 reasons/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Pending decisions")).toBeInTheDocument();
    expect(within(dialog).getByText("Material cases awaiting approval")).toBeInTheDocument();
    expect(within(dialog).getByText("1 material case not approved or reclassified.")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows Ready when the server says the day can be signed off", async () => {
    const routes = signedInRoutes();
    routes["GET /api/funds/GEF1/days/2026-11-10/release"] = {
      body: releaseFor("GEF1", "2026-11-10", { ready: true, reasons: [] }),
    };
    mockApi(routes);
    renderApp(URL_DAY2);
    const s = await strip();
    expect(await within(s).findByText("Ready to sign off")).toBeInTheDocument();
    expect(within(s).getByText("Every release condition is met.")).toBeInTheDocument();
    expect(within(s).queryByRole("button", { name: /reason/i })).not.toBeInTheDocument();
  });

  it("shows who signed off a signed-off day", async () => {
    mockApi(signedInRoutes());
    renderApp("/upload?fund=GEF1&day=2026-11-09");
    const s = await strip();
    expect(await within(s).findByText("Signed off")).toBeInTheDocument();
    expect(within(s).getByText(/by approver2/)).toBeInTheDocument();
    expect(within(s).getByRole("link", { name: /View sign-off/ })).toHaveAttribute(
      "href",
      "/signoff?fund=GEF1&day=2026-11-09",
    );
  });

  it("says a day has not been run, with the server's reason", async () => {
    const routes = signedInRoutes();
    routes["GET /api/funds/GEF1/days/2026-11-10"] = { body: dayRecord("GEF1", "2026-11-10", { status: "validated", nav: null }) };
    routes["GET /api/funds/GEF1/days/2026-11-10/release"] = {
      body: releaseFor("GEF1", "2026-11-10", {
        reasons: [{ code: "NOT_RUN", message: "The day has not been run.", case_ids: [] }],
      }),
    };
    mockApi(routes);
    renderApp(URL_DAY2);
    const s = await strip();
    expect(await within(s).findByText("The day has not been run.")).toBeInTheDocument();
    expect(within(s).getByText("Not run yet")).toBeInTheDocument();
    expect(screen.getByTestId("strip-nav")).toHaveTextContent("–");
  });

  it("says when a day has no files", async () => {
    const routes = signedInRoutes();
    routes["GET /api/funds/GEF1/days/2026-11-11"] = { status: 404, body: { detail: "No files have been uploaded for 2026-11-11." } };
    routes["GET /api/funds/GEF1/days/2026-11-11/release"] = {
      body: releaseFor("GEF1", "2026-11-11", {
        day_status: null,
        reasons: [{ code: "NOT_RUN", message: "The day has no files.", case_ids: [] }],
      }),
    };
    mockApi(routes);
    renderApp("/upload?fund=GEF1&day=2026-11-11");
    const s = await strip();
    expect(await within(s).findByText("No files loaded")).toBeInTheDocument();
    expect(within(s).getByText("The day has no files.")).toBeInTheDocument();
  });

  it("keeps the fund and day on the sign-off link", async () => {
    mockApi(signedInRoutes());
    renderApp(URL_DAY2);
    expect(await within(await strip()).findByRole("link", { name: /Open sign-off/ })).toHaveAttribute(
      "href",
      "/signoff?fund=GEF1&day=2026-11-10",
    );
  });
});
