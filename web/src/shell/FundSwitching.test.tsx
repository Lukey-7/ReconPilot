import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi } from "../test/mockApi";
import { location, renderApp, signedInRoutes } from "../test/render";

describe("fund switching", () => {
  it("opens the fund the user last chose, stored on the server, rather than the first fund", async () => {
    const api = mockApi({ ...signedInRoutes(), "GET /api/auth/me/preferences": { body: { fund: "INC2" } } });
    renderApp("/overview");
    await waitFor(() => expect(location()).toBe("/overview?fund=INC2&day=2026-11-09"));
    expect(screen.getByLabelText("Fund")).toHaveValue("INC2");
    // The first fund was never opened on the way.
    expect(api.calls("GET /api/funds/GEF1/days")).toHaveLength(0);
    expect(api.calls("PUT /api/auth/me/preferences")).toHaveLength(0);
  });

  it("opens the fund in the address, without storing it as the user's choice", async () => {
    const api = mockApi({ ...signedInRoutes(), "GET /api/auth/me/preferences": { body: { fund: "INC2" } } });
    renderApp("/overview?fund=GEF1");
    await waitFor(() => expect(location()).toBe("/overview?fund=GEF1&day=2026-11-10"));
    expect(api.calls("PUT /api/auth/me/preferences")).toHaveLength(0);
  });

  it("falls back to the first fund when the stored fund no longer exists or cannot be read", async () => {
    mockApi({ ...signedInRoutes(), "GET /api/auth/me/preferences": { body: { fund: "GONE" } } });
    renderApp("/overview");
    await waitFor(() => expect(location()).toBe("/overview?fund=GEF1&day=2026-11-10"));
  });

  it("stores the fund chosen in the selector for the user", async () => {
    document.cookie = "rp_csrf=token-123; path=/";
    const api = mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Fund"), "INC2");
    await waitFor(() => expect(location()).toBe("/overview?fund=INC2&day=2026-11-09"));
    const stored = api.calls("PUT /api/auth/me/preferences");
    expect(stored).toHaveLength(1);
    expect(stored[0]?.body).toEqual({ fund: "INC2" });
    expect(stored[0]?.headers["X-CSRF-Token"]).toBe("token-123");
  });

  it("reaches the funds screen from beside the selector and with g f", async () => {
    mockApi(signedInRoutes());
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    const user = userEvent.setup();
    const link = await screen.findByRole("link", { name: /^Funds/ });
    expect(link).toHaveAttribute("href", "/funds?fund=GEF1&day=2026-11-10");
    await user.keyboard("gf");
    await waitFor(() => expect(location()).toBe("/funds?fund=GEF1&day=2026-11-10"));
    expect(await screen.findByRole("heading", { level: 1, name: "Funds" })).toBeInTheDocument();
  });
});
