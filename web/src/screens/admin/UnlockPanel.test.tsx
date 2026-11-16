import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { User } from "../../api/types";
import { type RecordedRequest, mockApi } from "../../test/mockApi";
import { analyst, approver, renderApp, signedInRoutes } from "../../test/render";
import type { UnlockRequest, UnlockState } from "./api";

const URL = "/signoff?fund=GEF1&day=2026-11-09";
const UNLOCK = "/api/funds/GEF1/days/2026-11-09/unlock";
const admin: User = { username: "admin1", display_name: "Ada Admin", role: "approver", is_admin: true };
const REASON = "The custodian restated a price for 9 November after release.";

function request(overrides: Partial<UnlockRequest> = {}): UnlockRequest {
  return {
    id: 7,
    status: "pending",
    reason: REASON,
    requested_by: "admin1",
    requested_at: "2026-11-10T09:00:00+00:00",
    expires_at: "2026-11-11T09:00:00+00:00",
    decided_by: null,
    decided_at: null,
    decision_note: "",
    confirmable_by_me: false,
    declinable_by_me: false,
    withdrawable_by_me: false,
    ...overrides,
  };
}

function state(overrides: Partial<UnlockState> = {}): UnlockState {
  return {
    fund: "GEF1",
    as_of: "2026-11-09",
    day_status: "signed_off",
    signed_off_by: "approver2",
    signed_off_at: "2026-11-09T18:02:00+00:00",
    unlockable: true,
    problem: null,
    requestable_by_me: false,
    pending: null,
    history: [],
    confirm_within_hours: 24,
    ...overrides,
  };
}

const bodyOf = (r: RecordedRequest) => r.body as Record<string, unknown>;

/** The unlock routes as the server keeps them: a step's answer is what the next read returns too. */
function stateful(initial: UnlockState, steps: Record<string, (r: RecordedRequest) => UnlockState>) {
  let current = initial;
  const routes: Record<string, (r: RecordedRequest) => { status?: number; body: unknown }> = {
    [`GET ${UNLOCK}`]: () => ({ body: current }),
  };
  for (const [route, step] of Object.entries(steps)) {
    routes[route] = (r) => {
      current = step(r);
      return { status: route === `POST ${UNLOCK}` ? 201 : 200, body: current };
    };
  }
  return routes;
}

describe("Unlocking a signed-off day", () => {
  it("shows nothing to someone who can do nothing about a signed-off day", async () => {
    mockApi({ ...signedInRoutes(analyst), [`GET ${UNLOCK}`]: { body: state() } });
    renderApp(URL);
    expect(await screen.findByRole("heading", { level: 1, name: "NAV sign-off" })).toBeInTheDocument();
    await screen.findByText(/The NAV was signed off by/);
    expect(screen.queryByRole("region", { name: /Unlock/ })).not.toBeInTheDocument();
  });

  it("lets an administrator ask, with a reason of a sentence at least", async () => {
    const api = mockApi({
      ...signedInRoutes(admin),
      ...stateful(state({ requestable_by_me: true }), {
        [`POST ${UNLOCK}`]: (r) =>
          state({ pending: request({ reason: bodyOf(r).reason as string, withdrawable_by_me: true }) }),
      }),
    });
    renderApp(URL);
    const panel = await screen.findByRole("region", { name: "Unlock this day" });
    expect(panel).toHaveTextContent("a different approver confirms within 24 hours");
    const user = userEvent.setup();
    await user.click(within(panel).getByRole("button", { name: "Ask to unlock…" }));
    const dialog = await screen.findByRole("dialog", { name: "Ask to unlock Mon 9 Nov 2026?" });
    const submit = within(dialog).getByRole("button", { name: "Ask to unlock" });
    await user.type(within(dialog).getByLabelText("Reason"), "typo");
    expect(submit).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("Reason"));
    await user.type(within(dialog).getByLabelText("Reason"), REASON);
    await user.click(submit);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(bodyOf(api.calls(`POST ${UNLOCK}`)[0]!)).toEqual({ reason: REASON });
    const waiting = await screen.findByRole("region", { name: "Unlock requested" });
    expect(waiting).toHaveTextContent(REASON);
    expect(waiting).toHaveTextContent("A different approver must confirm by");
    expect(within(waiting).getByRole("button", { name: "Withdraw request" })).toBeInTheDocument();
    expect(within(waiting).queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it("lets a different approver confirm, then reads the day again", async () => {
    const api = mockApi({
      ...signedInRoutes(approver),
      ...stateful(state({ pending: request({ confirmable_by_me: true, declinable_by_me: true }) }), {
        [`POST ${UNLOCK}/7/confirm`]: () =>
          state({
            day_status: "ready",
            signed_off_by: null,
            history: [request({ status: "confirmed", decided_by: "approver2", decided_at: "2026-11-10T10:00:00+00:00" })],
          }),
      }),
    });
    renderApp(URL);
    const panel = await screen.findByRole("region", { name: "Unlock requested" });
    expect(panel).toHaveTextContent("admin1 asked to unlock Mon 9 Nov 2026");
    expect(panel).toHaveTextContent("an approver other than admin1");
    const dayReads = api.calls("GET /api/funds/GEF1/days/2026-11-09").length;
    const user = userEvent.setup();
    await user.click(within(panel).getByRole("button", { name: "Confirm unlock…" }));
    const dialog = await screen.findByRole("dialog", { name: "Unlock Mon 9 Nov 2026?" });
    expect(dialog).toHaveTextContent("signed off by approver2");
    expect(dialog).toHaveTextContent("must be signed off again");
    await user.type(within(dialog).getByLabelText("Note (optional)"), "Agreed.");
    await user.click(within(dialog).getByRole("button", { name: "Unlock the day" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(bodyOf(api.calls(`POST ${UNLOCK}/7/confirm`)[0]!)).toEqual({ note: "Agreed." });
    expect(await screen.findByText("Mon 9 Nov 2026 is unlocked. It must be signed off again.")).toBeInTheDocument();
    await waitFor(() => expect(api.calls("GET /api/funds/GEF1/days/2026-11-09").length).toBeGreaterThan(dayReads));
  });

  it("asks an approver who declines to say why", async () => {
    const api = mockApi({
      ...signedInRoutes(approver),
      ...stateful(state({ pending: request({ confirmable_by_me: true, declinable_by_me: true }) }), {
        [`POST ${UNLOCK}/7/decline`]: () =>
          state({ history: [request({ status: "declined", decided_by: "approver2", decision_note: "Fix today." })] }),
      }),
    });
    renderApp(URL);
    const panel = await screen.findByRole("region", { name: "Unlock requested" });
    const user = userEvent.setup();
    await user.click(within(panel).getByRole("button", { name: "Decline…" }));
    const dialog = await screen.findByRole("dialog", { name: "Decline the unlock?" });
    const go = within(dialog).getByRole("button", { name: "Decline" });
    expect(go).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Why"), "Fix today.");
    await user.click(go);
    await waitFor(() => expect(api.calls(`POST ${UNLOCK}/7/decline`)).toHaveLength(1));
    expect(bodyOf(api.calls(`POST ${UNLOCK}/7/decline`)[0]!)).toEqual({ note: "Fix today." });
    const history = await screen.findByText("Earlier unlock requests (1)");
    await user.click(history);
    expect(await screen.findByText(/Declined by approver2/)).toBeInTheDocument();
  });

  it("shows the server's refusal when confirming is no longer possible", async () => {
    mockApi({
      ...signedInRoutes(approver),
      [`GET ${UNLOCK}`]: { body: state({ pending: request({ confirmable_by_me: true, declinable_by_me: true }) }) },
      [`POST ${UNLOCK}/7/confirm`]: {
        status: 409,
        body: { detail: "2026-11-10 has already been run from this day's sign-off; a day can be unlocked only before the next day runs." },
      },
    });
    renderApp(URL);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Confirm unlock…" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Unlock the day" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("has already been run");
  });

  it("tells an administrator why a day cannot be unlocked", async () => {
    mockApi({
      ...signedInRoutes(admin),
      [`GET ${UNLOCK}`]: {
        body: state({ unlockable: false, problem: "Only the latest signed-off day can be unlocked; 2026-11-10 is signed off too." }),
      },
    });
    renderApp(URL);
    const panel = await screen.findByRole("region", { name: "Unlocking" });
    expect(panel).toHaveTextContent("Only the latest signed-off day can be unlocked");
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });
});
