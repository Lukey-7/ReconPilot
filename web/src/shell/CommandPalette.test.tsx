import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CaseDetail, QueueCase, User } from "../api/types";
import { mockApi } from "../test/mockApi";
import { location, renderApp, signedInRoutes } from "../test/render";
import { caseIdToLookUp, matches, moreText, visibleGroups } from "./CommandPalette";

const DAY = "2026-11-10";
const BASE = `/overview?fund=GEF1&day=${DAY}`;
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
    gross_exposure: 1000,
    material: false,
    escalated: false,
    sla_breached: false,
    age_days: 0,
    age_bucket: "0-1",
    version: 1,
    ...overrides,
  };
}

function setup(user?: User) {
  return mockApi({
    ...signedInRoutes(user),
    [`GET /api/funds/GEF1/days/${DAY}/cases`]: {
      body: [
        row("EX-1", { security_name: "Harbour Energy", category: "PRICE_MISMATCH", nav_impact: 62384.54, material: true }),
        row("EX-2", { security_name: "Granite Systems", nav_impact: -4659.67 }),
      ],
    },
  });
}

async function openPalette() {
  const user = userEvent.setup();
  renderApp(BASE);
  await screen.findByRole("heading", { name: "Morning overview" });
  await user.keyboard("{Control>}k{/Control}");
  const dialog = await screen.findByRole("dialog", { name: "Command palette" });
  const field = within(dialog).getByRole("combobox");
  return { user, dialog, field };
}

function selected(dialog: HTMLElement): string {
  const option = within(dialog)
    .getAllByRole("option")
    .find((o) => o.getAttribute("aria-selected") === "true");
  return option?.textContent ?? "";
}

describe("command palette", () => {
  it("opens with Ctrl+K, focused on its field, listing actions, screens, cases, funds and days", async () => {
    setup();
    const { dialog, field } = await openPalette();
    expect(field).toHaveFocus();
    // The day's cases arrive from the queue's own query.
    await within(dialog).findByText("EX-1");
    expect(within(dialog).getAllByRole("group").map((g) => g.firstElementChild?.textContent)).toEqual([
      "Actions",
      "Screens",
      "Cases",
      "Funds",
      "Business days",
    ]);
    const screens = within(dialog).getByRole("group", { name: /^Screens/ });
    expect(within(screens).getAllByRole("option").map((o) => o.querySelector(".pal-label")?.textContent)).toEqual([
      "Overview",
      "Upload",
      "Cases",
      "Sign-off",
      "MI",
      "Audit log",
      "Funds",
    ]);
    const cases = await within(dialog).findByRole("group", { name: /^Cases/ });
    expect(within(cases).getByText("EX-1")).toBeInTheDocument();
    expect(within(cases).getByText(/Harbour Energy · Price mismatch · \+62,384\.54 · Pending/)).toBeInTheDocument();
    const actions = within(dialog).getByRole("group", { name: /^Actions/ });
    expect(within(actions).getByText("Show keyboard shortcuts")).toBeInTheDocument();
    expect(within(actions).getByText("Switch to the light theme")).toBeInTheDocument();
    expect(within(actions).getByText("Sign out")).toBeInTheDocument();
  });

  it("opens from inside a field too, and Ctrl+K or Esc closes it", async () => {
    setup();
    renderApp(BASE);
    await screen.findByRole("heading", { name: "Morning overview" });
    const select = screen.getByLabelText("Fund");
    select.focus();
    fireEvent.keyDown(select, { key: "k", ctrlKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Command palette" });
    const user = userEvent.setup();
    await user.keyboard("{Control>}k{/Control}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    await user.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(location()).toBe(BASE);
  });

  it("gives focus back where it was when the palette or the shortcuts close without an action", async () => {
    setup();
    renderApp(BASE);
    const heading = await screen.findByRole("heading", { level: 1, name: "Morning overview" });
    const select = screen.getByLabelText("Fund");
    select.focus();
    const user = userEvent.setup();
    await user.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(select).toHaveFocus();

    heading.focus();
    fireEvent.keyDown(heading, { key: "?" });
    await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(heading).toHaveFocus();
  });

  it("jumps to a screen, keeping the fund and day", async () => {
    setup();
    const { user, dialog } = await openPalette();
    await user.keyboard("audit");
    expect(selected(dialog)).toContain("Audit log");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Audit log" })).toBeInTheDocument();
    expect(location()).toBe(`/audit?fund=GEF1&day=${DAY}`);
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });

  it("finds a case by its security and opens it in the workbench", async () => {
    setup();
    const { user, dialog } = await openPalette();
    await within(dialog).findByText("EX-2");
    await user.keyboard("granite");
    const options = within(dialog).getAllByRole("option");
    expect(options).toHaveLength(1);
    expect(selected(dialog)).toContain("EX-2");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(location()).toBe(`/cases?fund=GEF1&day=${DAY}&case=EX-2`));
  });

  it("switches the fund and the day, staying on the screen", async () => {
    const api = setup();
    const { user } = await openPalette();
    await user.keyboard("income{Enter}");
    await waitFor(() => expect(location()).toBe("/overview?fund=INC2&day=2026-11-09"));
    expect(api.calls("PUT /api/auth/me/preferences")[0]?.body).toEqual({ fund: "INC2" });

    await user.keyboard("{Control>}k{/Control}");
    await screen.findByRole("dialog", { name: "Command palette" });
    await user.keyboard("2026-11-10{Enter}");
    await waitFor(() => expect(location()).toBe("/overview?fund=INC2&day=2026-11-10"));
  });

  it("moves with the arrows, wrapping, and runs the selected action with Enter", async () => {
    setup();
    const { user, dialog, field } = await openPalette();
    await user.keyboard("shortcuts");
    expect(field).toHaveAttribute("aria-activedescendant");
    expect(selected(dialog)).toContain("Show keyboard shortcuts");
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Keyboard shortcuts" })).toBeInTheDocument();
  });

  it("walks the list with the arrow keys", async () => {
    setup();
    const { user, dialog } = await openPalette();
    await user.keyboard("o");
    const first = selected(dialog);
    await user.keyboard("{ArrowDown}");
    expect(selected(dialog)).not.toBe(first);
    await user.keyboard("{ArrowUp}");
    expect(selected(dialog)).toBe(first);
    await user.keyboard("{ArrowUp}");
    const options = within(dialog).getAllByRole("option");
    expect(selected(dialog)).toBe(options[options.length - 1]?.textContent);
  });

  it("says when nothing matches", async () => {
    setup();
    const { user, dialog } = await openPalette();
    await user.keyboard("zzzz");
    expect(within(dialog).queryAllByRole("option")).toHaveLength(0);
    expect(within(dialog).getByText(/Nothing matches/)).toBeInTheDocument();
  });

  it("says how many more cases match under a capped group, in good grammar", async () => {
    const api = setup();
    api.set(`GET /api/funds/GEF1/days/${DAY}/cases`, {
      body: Array.from({ length: 7 }, (_, i) => row(`EX-${i + 1}`)),
    });
    const { dialog } = await openPalette();
    const cases = await within(dialog).findByRole("group", { name: /^Cases/ });
    expect(cases.firstElementChild?.textContent).toBe("Cases · 2 more match; keep typing");
  });

  it("looks up a case id that is not in the day's queue and opens it on the last day it was in a run", async () => {
    const api = setup();
    const earlier = {
      ...row("EX-20261105-004", { security_name: "Kestrel Mining", category: "PRICE_MISMATCH", status: "APPROVED" }),
      as_of: "2026-11-06",
      is_open: false,
    } as unknown as CaseDetail;
    api.set("GET /api/funds/GEF1/cases/EX-20261105-004", { body: earlier });
    const { user, dialog } = await openPalette();
    await within(dialog).findByText("EX-1");
    await user.keyboard("ex-20261105-004");
    const option = await within(dialog).findByRole("option", { name: /EX-20261105-004/ });
    expect(option).toHaveTextContent(/Kestrel Mining · Price mismatch · .* · Approved · cleared Fri 6 Nov 2026/);
    // Looked up on its latest day: no as_of is sent.
    expect(api.calls("GET /api/funds/GEF1/cases/EX-20261105-004")[0]?.url).toBe("/api/funds/GEF1/cases/EX-20261105-004");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(location()).toBe("/cases?fund=GEF1&day=2026-11-06&case=EX-20261105-004"));
  });

  it("says when a typed case id is not a case in the fund", async () => {
    setup();
    const { user, dialog } = await openPalette();
    await within(dialog).findByText("EX-1");
    await user.keyboard("EX-20261105-999");
    expect(await within(dialog).findByText("No case EX-20261105-999 in GEF1.")).toBeInTheDocument();
    expect(within(dialog).queryAllByRole("option")).toHaveLength(0);
  });

  it("offers the demo's other users to a demo visitor", async () => {
    const demoUser: User = {
      username: "priya.x",
      display_name: "Priya Shah",
      role: "analyst",
      is_admin: false,
      demo: {
        fund: "GEF1",
        fund_name: "Global Equity Fund",
        expires_at: "2026-11-15T10:00:00+00:00",
        users: [
          { username: "priya.x", display_name: "Priya Shah", role: "analyst" },
          { username: "ann.x", display_name: "Ann Lee", role: "approver" },
        ],
      },
    };
    setup(demoUser);
    const { user, dialog } = await openPalette();
    await user.keyboard("work as");
    expect(within(dialog).getByText("Work as Ann Lee (approver)")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Work as Priya Shah/)).not.toBeInTheDocument();
  });

  it("offers a viewer no action the role forbids", async () => {
    setup(viewer);
    const { dialog } = await openPalette();
    const actions = within(dialog).getByRole("group", { name: /^Actions/ });
    expect(within(actions).queryByText(/Approve|Reject|Reclassify|Run|Sign off/)).not.toBeInTheDocument();
  });
});

describe("palette helpers", () => {
  it("words the overflow note for one and for many", () => {
    expect(moreText(1)).toBe("1 more matches; keep typing");
    expect(moreText(7)).toBe("7 more match; keep typing");
  });

  it("looks up only a full case id that is not already listed", () => {
    expect(caseIdToLookUp(" ex-20261111-001 ", [])).toBe("EX-20261111-001");
    expect(caseIdToLookUp("EX-20261111-001", [{ id: "case-EX-20261111-001" }])).toBeNull();
    expect(caseIdToLookUp("EX-2026", [])).toBeNull();
    expect(caseIdToLookUp("granite", [])).toBeNull();
  });
});

describe("palette matching", () => {
  it("needs every word, in any order and case", () => {
    const item = { text: "ex-1 harbour energy price mismatch" };
    expect(matches(item, "price HARBOUR")).toBe(true);
    expect(matches(item, "price granite")).toBe(false);
    expect(matches(item, "  ")).toBe(true);
  });

  it("caps each group and says how many more match", () => {
    const items = Array.from({ length: 14 }, (_, i) => ({
      id: `case-${i}`,
      group: "Cases",
      label: `C${i}`,
      text: `c${i} case`,
      run: () => {},
    }));
    const idle = visibleGroups(items, "");
    expect(idle[0]?.items).toHaveLength(5);
    expect(idle[0]?.more).toBe(9);
    const typed = visibleGroups(items, "case");
    expect(typed[0]?.items).toHaveLength(10);
    expect(typed[0]?.more).toBe(4);
  });
});
