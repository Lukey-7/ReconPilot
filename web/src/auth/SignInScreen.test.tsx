import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { mockApi } from "../test/mockApi";
import { analyst, location, renderApp, signedInRoutes } from "../test/render";
import { safeDestination } from "./SignInScreen";

const signedOut = { "GET /api/auth/me": { status: 401, body: { detail: "Not signed in." } } };

async function fillAndSubmit(username: string, password: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Username"), username);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("sign-in", () => {
  it("sends a signed-out visitor to sign-in, then back to where they were going", async () => {
    const routes = signedInRoutes();
    const api = mockApi({ ...routes, ...signedOut });
    renderApp("/cases?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(location()).toBe("/signin");

    api.set("POST /api/auth/login", { body: { user: analyst } });
    await fillAndSubmit("analyst1", "Ledger-Walrus-4817");

    expect(await screen.findByRole("heading", { name: "Cases" })).toBeInTheDocument();
    expect(location()).toBe("/cases?fund=GEF1&day=2026-11-10");
    expect(api.calls("POST /api/auth/login")[0]?.body).toEqual({ username: "analyst1", password: "Ledger-Walrus-4817" });
    expect(screen.getByText("Priya Shah")).toBeInTheDocument();
    expect(screen.getByText("Analyst")).toBeInTheDocument();
  });

  it("shows the server's answer for wrong details and clears the password", async () => {
    mockApi({
      ...signedOut,
      "POST /api/auth/login": { status: 401, body: { detail: "Wrong username or password." } },
    });
    renderApp("/signin");
    await fillAndSubmit("analyst1", "nope");
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByRole("alert")).toHaveFocus();
  });

  it("explains a locked account in the server's words", async () => {
    mockApi({
      ...signedOut,
      "POST /api/auth/login": {
        status: 423,
        body: { detail: "Account locked after 5 failed sign-ins. Try again in 15 minutes." },
      },
    });
    renderApp("/signin");
    await fillAndSubmit("analyst1", "whatever-it-is");
    expect(await screen.findByRole("alert")).toHaveTextContent("Account locked after 5 failed sign-ins");
  });

  it("asks for both fields before calling the server", async () => {
    const api = mockApi(signedOut);
    renderApp("/signin");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your username and password.");
    expect(api.calls("POST /api/auth/login")).toHaveLength(0);
  });

  it("returns to sign-in when the session ends while working", async () => {
    const routes = signedInRoutes();
    const api = mockApi(routes);
    renderApp("/overview?fund=GEF1&day=2026-11-10");
    expect(await screen.findByRole("heading", { name: "Morning overview" })).toBeInTheDocument();

    // The session times out: the next request answers 401.
    api.set("GET /api/funds/GEF1/days/2026-11-09", { status: 401, body: { detail: "Session expired." } });
    api.set("GET /api/funds/GEF1/days/2026-11-09/release", { status: 401, body: { detail: "Session expired." } });
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByLabelText("Business day"), "2026-11-09");

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Your session ended");
    await waitFor(() => expect(location()).toBe("/signin"));
  });

  it("only returns to pages inside the app", () => {
    expect(safeDestination("/cases?fund=GEF1")).toBe("/cases?fund=GEF1");
    expect(safeDestination("//evil.example/x")).toBe("/overview");
    expect(safeDestination("https://evil.example")).toBe("/overview");
    expect(safeDestination("/signin")).toBe("/overview");
    expect(safeDestination(undefined)).toBe("/overview");
  });
});
