import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi } from "../test/mockApi";
import { approver, location, renderApp, signedInRoutes } from "../test/render";

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

  it("switching the day updates the address and the strip", async () => {
    const api = mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Business day"), "2026-11-09");
    await waitFor(() => expect(location()).toBe("/overview?fund=GEF1&day=2026-11-09"));
    const strip = screen.getByRole("region", { name: "NAV and release status" });
    expect(await within(strip).findByText("Signed off")).toBeInTheDocument();
    expect(api.calls("GET /api/funds/GEF1/days/2026-11-09/release")).toHaveLength(1);
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
