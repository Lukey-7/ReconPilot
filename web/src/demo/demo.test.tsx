import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { FundSummary, User } from "../api/types";
import { mockApi } from "../test/mockApi";
import { dayRecord, daysList, intakeFor, location, releaseFor, renderApp, signedInRoutes } from "../test/render";

const FUND = "DEMO-7KQ2XM";
const FRIDAY = "2026-11-13";
const MONDAY = "2026-11-16";

const members = [
  { username: "priya.7kq2xm", display_name: "Priya Shah", role: "analyst" as const },
  { username: "ann.7kq2xm", display_name: "Ann Lee", role: "approver" as const },
  { username: "tom.7kq2xm", display_name: "Tom Reed", role: "approver" as const },
  { username: "vic.7kq2xm", display_name: "Vic Moss", role: "viewer" as const },
];

function demoUser(index: number): User {
  const m = members[index]!;
  return {
    ...m,
    is_admin: false,
    demo: { fund: FUND, fund_name: "Demo Global Equity Fund", expires_at: "2026-11-15T09:00:00+00:00", users: members },
  };
}

const demoFund: FundSummary = {
  code: FUND,
  name: "Demo Global Equity Fund",
  base_currency: "USD",
  start_date: "2026-11-09",
  latest_day: FRIDAY,
  latest_status: "ready",
};

const instance = {
  mode: "demo",
  demo: { expires_after_hours: 24, week: ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", FRIDAY], last_day: "2026-11-20", resume: null },
};

/** A demo visitor's session: their one fund, its week, Friday as the latest day. */
function demoRoutes(user: User, fridayStatus = "ready") {
  const week = [FRIDAY, "2026-11-12", "2026-11-11", "2026-11-10", "2026-11-09"].map((as_of, i) => ({
    as_of,
    status: i === 0 ? fridayStatus : "signed_off",
  }));
  return {
    ...signedInRoutes(user),
    "GET /api/instance": { body: instance },
    "GET /api/funds": { body: [demoFund] },
    [`GET /api/funds/${FUND}/days`]: { body: daysList(FUND, week, fridayStatus === "signed_off" ? MONDAY : null) },
    [`GET /api/funds/${FUND}/days/${FRIDAY}`]: { body: dayRecord(FUND, FRIDAY, { status: fridayStatus }) },
    [`GET /api/funds/${FUND}/days/${FRIDAY}/release`]: { body: releaseFor(FUND, FRIDAY) },
    [`GET /api/funds/${FUND}/days/${FRIDAY}/intake`]: {
      body: intakeFor(FUND, FRIDAY, {
        open: false,
        blocked: { code: "UPLOADS_OFF", message: "Uploads are switched off in the demo.", day: null, day_status: null },
        day_status: fridayStatus,
      }),
    },
    [`GET /api/funds/${FUND}/days/${FRIDAY}/runs`]: { body: { fund: FUND, as_of: FRIDAY, runs: [] } },
  };
}

describe("demo", () => {
  it("offers Try the demo instead of a password, under the synthetic-data notice, and opens the visitor's fund", async () => {
    const api = mockApi({
      ...demoRoutes(demoUser(0)),
      "GET /api/auth/me": { status: 401, body: { detail: "Sign in to continue." } },
      "POST /api/demo": { body: { user: demoUser(0), fund: FUND } },
    });
    renderApp("/signin");
    expect(await screen.findByRole("heading", { name: "Try the demo" })).toBeInTheDocument();
    expect(screen.getByRole("note", { name: "Demo notice" })).toHaveTextContent("Every figure here is synthetic");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "Try the demo" }));
    await waitFor(() => expect(location()).toBe(`/overview?fund=${FUND}&day=${FRIDAY}`));
    expect(api.calls("POST /api/demo")[0]?.body).toEqual({});
    expect(screen.getByRole("note", { name: "Demo notice" })).toBeInTheDocument();
  });

  it("lets a visitor whose session ended carry on with their own fund", async () => {
    const api = mockApi({
      ...demoRoutes(demoUser(0)),
      "GET /api/instance": {
        body: { ...instance, demo: { ...instance.demo, resume: { fund: FUND, expires_at: "2026-11-15T09:00:00+00:00" } } },
      },
      "GET /api/auth/me": { status: 401, body: { detail: "Sign in to continue." } },
      "POST /api/demo/resume": { body: { user: demoUser(0), fund: FUND } },
    });
    renderApp("/signin");
    expect(await screen.findByRole("button", { name: "Start a new demo" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: `Carry on with ${FUND}` }));
    await waitFor(() => expect(location()).toBe(`/overview?fund=${FUND}&day=${FRIDAY}`));
    expect(api.calls("POST /api/demo/resume")).toHaveLength(1);
    expect(api.calls("POST /api/demo")).toHaveLength(0);
  });

  it("says why a demo cannot start, in the server's words", async () => {
    mockApi({
      "GET /api/instance": { body: instance },
      "GET /api/auth/me": { status: 401, body: { detail: "Sign in to continue." } },
      "POST /api/demo": { status: 503, body: { detail: "The demo is full right now. Please try again in a little while." } },
    });
    renderApp("/signin");
    await userEvent.setup().click(await screen.findByRole("button", { name: "Try the demo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The demo is full right now.");
  });

  it("keeps the ordinary sign-in on a real instance, with no demo notice", async () => {
    mockApi({
      "GET /api/instance": { body: { mode: "real" } },
      "GET /api/auth/me": { status: 401, body: { detail: "Sign in to continue." } },
    });
    renderApp("/signin");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByRole("note", { name: "Demo notice" })).not.toBeInTheDocument();
  });

  it("switches between the fund's one-click users", async () => {
    const api = mockApi({
      ...demoRoutes(demoUser(0)),
      "POST /api/demo/switch": (request) => {
        const index = members.findIndex((m) => m.username === (request.body as { username: string }).username);
        return { body: { user: demoUser(index) } };
      },
    });
    renderApp(`/overview?fund=${FUND}&day=${FRIDAY}`);
    const select = await screen.findByLabelText("Working as");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Priya Shah · Analyst",
      "Ann Lee · Approver",
      "Tom Reed · Approver",
      "Vic Moss · Viewer",
    ]);
    await userEvent.setup().selectOptions(select, "ann.7kq2xm");
    await waitFor(() => expect(screen.getByLabelText("Working as")).toHaveValue("ann.7kq2xm"));
    expect(api.calls("POST /api/demo/switch")[0]?.body).toEqual({ username: "ann.7kq2xm" });
    expect(screen.getByText("Ann Lee")).toBeInTheDocument();
  });

  it("shows no switcher or notice to a real user", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("heading", { name: "Morning overview" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Working as")).not.toBeInTheDocument();
    expect(screen.queryByRole("note", { name: "Demo notice" })).not.toBeInTheDocument();
  });

  it("asks for the latest day's sign-off before a new day can be generated", async () => {
    mockApi(demoRoutes(demoUser(0)));
    renderApp(`/upload?fund=${FUND}&day=${FRIDAY}`);
    expect(await screen.findByText("In the demo, days are generated rather than uploaded.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the sign-off" })).toHaveAttribute(
      "href",
      `/signoff?fund=${FUND}&day=${FRIDAY}`,
    );
    expect(screen.queryByRole("button", { name: /Generate/ })).not.toBeInTheDocument();
  });

  it("generates the next business day and follows its run", async () => {
    const api = mockApi({
      ...demoRoutes(demoUser(0), "signed_off"),
      "POST /api/demo/next-day": { body: { fund: FUND, as_of: MONDAY, job_id: 41 } },
      [`GET /api/funds/${FUND}/days/${MONDAY}`]: {
        body: dayRecord(FUND, MONDAY, {
          status: "running",
          nav: null,
          run_at: null,
          job: {
            id: 41,
            kind: "run_day",
            status: "running",
            attempts: 1,
            max_attempts: 3,
            error: null,
            result: null,
            created_at: "2026-11-14T09:00:00+00:00",
            started_at: "2026-11-14T09:00:01+00:00",
            finished_at: null,
          },
        }),
      },
      [`GET /api/funds/${FUND}/days/${MONDAY}/intake`]: {
        body: intakeFor(FUND, MONDAY, {
          open: false,
          blocked: { code: "UPLOADS_OFF", message: "Uploads are switched off in the demo.", day: null, day_status: null },
        }),
      },
      [`GET /api/funds/${FUND}/days/${MONDAY}/runs`]: { body: { fund: FUND, as_of: MONDAY, runs: [] } },
      [`GET /api/funds/${FUND}/days/${MONDAY}/release`]: { body: releaseFor(FUND, MONDAY, { day_status: "running" }) },
      "GET /api/jobs/41": {
        body: {
          id: 41,
          kind: "run_day",
          status: "running",
          attempts: 1,
          max_attempts: 3,
          error: null,
          result: null,
          created_at: "2026-11-14T09:00:00+00:00",
          started_at: "2026-11-14T09:00:01+00:00",
          finished_at: null,
        },
      },
    });
    renderApp(`/upload?fund=${FUND}&day=${FRIDAY}`);
    await userEvent.setup().click(await screen.findByRole("button", { name: "Generate Mon 16 Nov 2026" }));
    await waitFor(() => expect(location()).toBe(`/upload?fund=${FUND}&day=${MONDAY}`));
    expect(api.calls("POST /api/demo/next-day")).toHaveLength(1);
    expect(await screen.findByRole("list", { name: "Run progress" })).toBeInTheDocument();
  });
});
