import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { User } from "../../api/types";
import { type RecordedRequest, mockApi } from "../../test/mockApi";
import { analyst, fundA, fundDetail, location, renderApp, signedInRoutes } from "../../test/render";
import type { AdminFund, AdminUser, AiProviders } from "./api";

const admin: User = { username: "admin1", display_name: "Ada Admin", role: "approver", is_admin: true };

function adminUser(overrides: Partial<AdminUser>): AdminUser {
  return {
    username: "x",
    display_name: "X",
    role: "analyst",
    is_admin: false,
    is_active: true,
    locked: false,
    locked_until: null,
    failed_logins: 0,
    last_login_at: "2026-11-13T08:30:00+00:00",
    created_at: "2026-11-01T09:00:00+00:00",
    live_sessions: 0,
    ...overrides,
  };
}

const USERS: AdminUser[] = [
  adminUser({ username: "admin1", display_name: "Ada Admin", role: "approver", is_admin: true, live_sessions: 1 }),
  adminUser({ username: "analyst1", display_name: "Priya Shah", live_sessions: 1 }),
  adminUser({
    username: "viewer1",
    display_name: "Vic Moss",
    role: "viewer",
    locked: true,
    locked_until: "2026-11-13T09:15:00+00:00",
    failed_logins: 0,
  }),
  adminUser({ username: "old1", display_name: "Olive Old", is_active: false, last_login_at: null }),
];

function adminFund(overrides: Partial<AdminFund> = {}): AdminFund {
  return {
    ...fundDetail(fundA, { non_business_dates: ["2026-11-26", "2026-11-05"] }),
    ai: { enabled: false, provider: null, effective_provider: "openai", model: "gpt-6-luna" },
    ...overrides,
  };
}

const PROVIDERS: AiProviders = {
  default: "openai",
  providers: [
    { provider: "anthropic", label: "Anthropic", configured: false, model: null, private: false, endpoint: null,
      problem: "Not configured on the server: set ANTHROPIC_API_KEY." },
    { provider: "openai", label: "OpenAI", configured: true, model: "gpt-6-luna", private: false, endpoint: null,
      problem: null },
    { provider: "google", label: "Google", configured: false, model: null, private: false, endpoint: null,
      problem: "Not configured on the server: set GOOGLE_API_KEY." },
    { provider: "openai_compatible", label: "Private endpoint (OpenAI-compatible)", configured: true,
      model: "house-7b", private: true, endpoint: "llm.bank.internal", problem: null },
  ],
};

function routes(user: User = admin) {
  return {
    ...signedInRoutes(user),
    "GET /api/admin/users": { body: USERS },
    "GET /api/admin/funds/GEF1": { body: adminFund() },
    "GET /api/admin/ai/providers": { body: PROVIDERS },
  };
}

const bodyOf = (r: RecordedRequest) => r.body as Record<string, unknown>;

describe("Administration: who sees it", () => {
  it("tells someone without the admin flag that it is not theirs, and asks the server for nothing", async () => {
    const api = mockApi(routes(analyst));
    renderApp("/admin/users?fund=GEF1&day=2026-11-10");
    expect(await screen.findByText(/Only an administrator can manage users and funds/)).toBeInTheDocument();
    expect(api.calls("GET /api/admin/users")).toHaveLength(0);
  });

  it("is offered in the user menu to an administrator only", async () => {
    mockApi(routes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Ada Admin/ }));
    await user.click(await screen.findByRole("menuitem", { name: /Administration/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Administration: users" })).toBeInTheDocument();
    expect(location()).toBe("/admin/users?fund=GEF1&day=2026-11-10");
  });

  it("has no menu entry for anyone else", async () => {
    mockApi(routes(analyst));
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Priya Shah/ }));
    await screen.findByRole("menuitem", { name: /Sign out/ });
    expect(screen.queryByRole("menuitem", { name: /Administration/ })).not.toBeInTheDocument();
  });

  it("opens on the users tab from /admin and switches to funds", async () => {
    mockApi(routes());
    renderApp("/admin?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("heading", { level: 1, name: "Administration: users" })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(within(screen.getByRole("navigation", { name: "Administration" })).getByRole("link", { name: "Funds" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Administration: funds" })).toBeInTheDocument();
  });
});

describe("Administration: users", () => {
  it("lists every user with role, status and sign-in, and never offers to change your own account", async () => {
    mockApi(routes());
    renderApp("/admin/users?fund=GEF1&day=2026-11-10");
    const table = await screen.findByRole("table", { name: /Every user/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Ada Admin");
    expect(within(rows[0]!).getByText("You")).toBeInTheDocument();
    expect(within(rows[0]!).queryByRole("button")).not.toBeInTheDocument();
    expect(rows[2]).toHaveTextContent("Locked until");
    expect(rows[3]).toHaveTextContent("Deactivated");
    expect(rows[3]).toHaveTextContent("Never");
    expect(screen.getByText("3 active users, 1 locked account")).toBeInTheDocument();
  });

  it("adds a user, checking the two passwords agree first", async () => {
    const api = mockApi({
      ...routes(),
      "POST /api/admin/users": (request) => ({
        status: 201,
        body: adminUser({ username: bodyOf(request).username as string }),
      }),
    });
    renderApp("/admin/users?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add a user" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a user" });
    await user.type(within(dialog).getByLabelText("Username"), "nell");
    await user.type(within(dialog).getByLabelText("Name"), "Nell Newby");
    await user.selectOptions(within(dialog).getByLabelText("Role"), "approver");
    await user.type(within(dialog).getByLabelText("Password"), "Harbour-Lantern-9052");
    await user.type(within(dialog).getByLabelText("Password again"), "Harbour-Lantern-9053");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The two passwords differ.");
    expect(api.calls("POST /api/admin/users")).toHaveLength(0);

    await user.clear(within(dialog).getByLabelText("Password again"));
    await user.type(within(dialog).getByLabelText("Password again"), "Harbour-Lantern-9052");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(bodyOf(api.calls("POST /api/admin/users")[0]!)).toEqual({
      username: "nell",
      display_name: "Nell Newby",
      role: "approver",
      is_admin: false,
      password: "Harbour-Lantern-9052",
    });
    expect(api.calls("GET /api/admin/users").length).toBeGreaterThan(1); // the list is read again
  });

  it("shows the server's refusal in its own words", async () => {
    mockApi({
      ...routes(),
      "POST /api/admin/users": { status: 422, body: { detail: "That password is too common." } },
    });
    renderApp("/admin/users?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add a user" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a user" });
    await user.type(within(dialog).getByLabelText("Username"), "nell");
    await user.type(within(dialog).getByLabelText("Password"), "Password1234");
    await user.type(within(dialog).getByLabelText("Password again"), "Password1234");
    await user.click(within(dialog).getByRole("button", { name: "Add user" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("That password is too common.");
  });

  it("changes a role, resets a password, unlocks and deactivates from one person's dialog", async () => {
    const api = mockApi({
      ...routes(),
      "PATCH /api/admin/users/viewer1": (request) => ({
        body: adminUser({ username: "viewer1", display_name: "Vic Moss", ...(bodyOf(request) as Partial<AdminUser>) }),
      }),
      "POST /api/admin/users/viewer1/password": { body: adminUser({ username: "viewer1" }) },
      "POST /api/admin/users/viewer1/unlock": { body: adminUser({ username: "viewer1" }) },
    });
    renderApp("/admin/users?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Manage Vic Moss (viewer1)" }));
    const dialog = await screen.findByRole("dialog", { name: /Manage Vic Moss/ });

    await user.click(within(dialog).getByRole("button", { name: "Unlock account" }));
    expect(await within(dialog).findByText("Vic Moss can sign in again.")).toBeInTheDocument();
    expect(api.calls("POST /api/admin/users/viewer1/unlock")).toHaveLength(1);

    expect(within(dialog).getByRole("button", { name: "Change role" })).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText("Role"), "analyst");
    await user.click(within(dialog).getByRole("button", { name: "Change role" }));
    expect(await within(dialog).findByText(/Vic Moss is now analyst/)).toBeInTheDocument();
    expect(bodyOf(api.calls("PATCH /api/admin/users/viewer1")[0]!)).toEqual({ role: "analyst" });

    await user.type(within(dialog).getByLabelText("New password"), "Harbour-Lantern-9052");
    await user.click(within(dialog).getByRole("button", { name: "Reset password" }));
    expect(await within(dialog).findByText(/password is reset/)).toBeInTheDocument();
    expect(bodyOf(api.calls("POST /api/admin/users/viewer1/password")[0]!)).toEqual({ password: "Harbour-Lantern-9052" });

    await user.click(within(dialog).getByRole("button", { name: "Deactivate" }));
    expect(await within(dialog).findByText(/deactivated and can no longer sign in/)).toBeInTheDocument();
    expect(bodyOf(api.calls("PATCH /api/admin/users/viewer1")[1]!)).toEqual({ is_active: false });
  });
});

describe("Administration: funds", () => {
  it("saves only the settings that changed, with percentages sent as fractions", async () => {
    const api = mockApi({
      ...routes(),
      "PATCH /api/admin/funds/GEF1": { body: adminFund() },
    });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const settings = await screen.findByRole("region", { name: /Settings for GEF1/ });
    const save = within(settings).getByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    const user = userEvent.setup();
    const materiality = within(settings).getByLabelText("Materiality");
    await user.clear(materiality);
    await user.type(materiality, "0.5");
    const equity = within(settings).getByLabelText("Price-move limit, Equity");
    await user.clear(equity);
    await user.type(equity, "15");
    await user.click(save);
    expect(await within(settings).findByText(/Saved. Applies from the next run/)).toBeInTheDocument();
    expect(bodyOf(api.calls("PATCH /api/admin/funds/GEF1")[0]!)).toEqual({
      settings: { materiality_bp: 0.5, check_settings: { price_move_limits: { EQUITY: 0.15, BOND: 0.02 } } },
    });
  });

  it("shows a refused setting in the server's words", async () => {
    mockApi({
      ...routes(),
      "PATCH /api/admin/funds/GEF1": {
        status: 422,
        body: { detail: "escalate_after_days must be a whole number of business days, 0 or more." },
      },
    });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const settings = await screen.findByRole("region", { name: /Settings for GEF1/ });
    const user = userEvent.setup();
    const escalate = within(settings).getByLabelText("Escalate after");
    await user.clear(escalate);
    await user.type(escalate, "3");
    await user.click(within(settings).getByRole("button", { name: "Save settings" }));
    expect(await within(settings).findByRole("alert")).toHaveTextContent("whole number of business days");
  });

  it("switches AI on only after the administrator confirms where the evidence goes", async () => {
    const api = mockApi({
      ...routes(),
      "PUT /api/admin/funds/GEF1/ai": {
        body: adminFund({ ai: { enabled: true, provider: "openai", effective_provider: "openai", model: "gpt-6-luna" } }),
      },
    });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const panel = await screen.findByRole("region", { name: "AI second opinion" });
    expect(await within(panel).findByText("Off")).toBeInTheDocument();
    const select = within(panel).getByLabelText("Provider");
    expect(within(select).getByRole("option", { name: "Anthropic (not configured)" })).toBeDisabled();
    const user = userEvent.setup();
    await user.selectOptions(select, "openai");
    await user.click(within(panel).getByRole("button", { name: "Switch AI on…" }));

    const dialog = await screen.findByRole("dialog", { name: "Switch AI on for GEF1?" });
    expect(within(dialog).getByText(/Evidence leaves the building/)).toBeInTheDocument();
    expect(within(dialog).getByRole("note")).toHaveTextContent("OpenAI, outside the firm, model gpt-6-luna");
    const go = within(dialog).getByRole("button", { name: "Switch AI on" });
    expect(go).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(go);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(bodyOf(api.calls("PUT /api/admin/funds/GEF1/ai")[0]!)).toEqual({
      enabled: true,
      provider: "openai",
      acknowledged: true,
    });
    const on = await screen.findByRole("region", { name: "AI second opinion" });
    expect(await within(on).findByText("On")).toBeInTheDocument();
    expect(within(on).getByRole("button", { name: "Switch AI off" })).toBeInTheDocument();
  });

  it("says the private endpoint's host, not 'outside the firm', for the private endpoint", async () => {
    mockApi(routes());
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const panel = await screen.findByRole("region", { name: "AI second opinion" });
    const user = userEvent.setup();
    await user.selectOptions(await within(panel).findByLabelText("Provider"), "openai_compatible");
    await user.click(within(panel).getByRole("button", { name: "Switch AI on…" }));
    const dialog = await screen.findByRole("dialog", { name: "Switch AI on for GEF1?" });
    expect(within(dialog).getByRole("note")).toHaveTextContent(
      "Evidence goes to your private endpoint. From the next run, the evidence behind each new case",
    );
    expect(within(dialog).getByRole("note")).toHaveTextContent("the private endpoint at llm.bank.internal, model house-7b");
  });

  it("switches AI off in one step", async () => {
    const api = mockApi({
      ...routes(),
      "GET /api/admin/funds/GEF1": {
        body: adminFund({ ai: { enabled: true, provider: null, effective_provider: "openai", model: "gpt-6-luna" } }),
      },
      "PUT /api/admin/funds/GEF1/ai": { body: adminFund() },
    });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const panel = await screen.findByRole("region", { name: "AI second opinion" });
    const user = userEvent.setup();
    await user.click(await within(panel).findByRole("button", { name: "Switch AI off" }));
    await waitFor(() => expect(api.calls("PUT /api/admin/funds/GEF1/ai")).toHaveLength(1));
    expect(bodyOf(api.calls("PUT /api/admin/funds/GEF1/ai")[0]!)).toMatchObject({ enabled: false });
  });

  it("changes the calendar only after the latest loaded day", async () => {
    const api = mockApi({
      ...routes(),
      "PATCH /api/admin/funds/GEF1": { body: adminFund({ non_business_dates: ["2026-11-05", "2026-11-26", "2026-12-25"] }) },
    });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const calendar = await screen.findByRole("region", { name: "Business calendar" });
    const list = within(calendar).getByRole("list", { name: "Non-business days" });
    expect(within(list).getByText("Worked")).toBeInTheDocument(); // 5 November, before the latest day
    expect(within(list).getAllByRole("button")).toHaveLength(1); // only 26 November can be removed
    const user = userEvent.setup();
    await user.type(within(calendar).getByLabelText("Add a non-business day"), "2026-12-25");
    await user.click(within(calendar).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.calls("PATCH /api/admin/funds/GEF1")).toHaveLength(1));
    expect(bodyOf(api.calls("PATCH /api/admin/funds/GEF1")[0]!)).toEqual({
      non_business_dates: ["2026-11-05", "2026-11-26", "2026-12-25"],
    });
  });

  it("adds a fund and starts working it", async () => {
    const created = adminFund({ code: "INC3", name: "Income Fund III" });
    const api = mockApi({
      ...routes(),
      "POST /api/admin/funds": { status: 201, body: created },
      "GET /api/admin/funds/INC3": { body: created },
      "GET /api/funds/INC3/days": { body: { fund: "INC3", start_date: "2026-11-16", latest_day: null, next_day: "2026-11-16", days: [] } },
    });
    api.set("GET /api/funds", { body: [fundA, { ...fundA, code: "INC3", name: "Income Fund III" }] });
    renderApp("/admin/funds?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add a fund" }));
    const dialog = await screen.findByRole("dialog", { name: "Add a fund" });
    await user.type(within(dialog).getByLabelText("Fund code"), "inc3");
    await user.type(within(dialog).getByLabelText("Fund name"), "Income Fund III");
    await user.type(within(dialog).getByLabelText("First business day"), "2026-11-16");
    await user.click(within(dialog).getByRole("button", { name: "Add fund" }));
    await waitFor(() => expect(location()).toContain("fund=INC3"));
    expect(bodyOf(api.calls("POST /api/admin/funds")[0]!)).toEqual({
      code: "INC3",
      name: "Income Fund III",
      start_date: "2026-11-16",
      non_business_dates: [],
      settings: { materiality_bp: 1 },
    });
  });
});
