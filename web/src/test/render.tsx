/**
 * Render the real app (every provider and route) at a URL, against `mockApi`.
 * `fixtures` builds API answers for tests only; nothing here is used by the app itself.
 */
import { render } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { MemoryRouter, useLocation } from "react-router";

import { AppProviders, AppRoutes } from "../app/App";
import type { Day, DaysList, FundSummary, ReleaseForMe, User } from "../api/types";
import type { RouteAnswer } from "./mockApi";

export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
}

let currentLocation = "";
function LocationProbe() {
  const location = useLocation();
  currentLocation = `${location.pathname}${location.search}`;
  return null;
}

/** The router's current path and query, as the app last rendered it. */
export function location(): string {
  return currentLocation;
}

export function renderApp(url: string, extra?: ReactElement) {
  const client = testQueryClient();
  const result = render(
    <MemoryRouter initialEntries={[url]}>
      <AppProviders client={client}>
        <AppRoutes />
        <LocationProbe />
        {extra}
      </AppProviders>
    </MemoryRouter>,
  );
  return { ...result, client };
}

// --------------------------------------------------------------------------- fixtures

export const analyst: User = { username: "analyst1", display_name: "Priya Shah", role: "analyst", is_admin: false };
export const approver: User = { username: "approver2", display_name: "Tom Reed", role: "approver", is_admin: false };

export const fundA: FundSummary = {
  code: "GEF1",
  name: "Global Equity Fund",
  base_currency: "USD",
  start_date: "2026-11-09",
  latest_day: "2026-11-10",
  latest_status: "ready",
};
export const fundB: FundSummary = {
  code: "INC2",
  name: "Income Fund",
  base_currency: "USD",
  start_date: "2026-11-09",
  latest_day: "2026-11-09",
  latest_status: "signed_off",
};

export function daysList(fund: string, days: { as_of: string; status: string }[], nextDay: string | null = null): DaysList {
  return {
    fund,
    start_date: "2026-11-09",
    latest_day: days[0]?.as_of ?? null,
    next_day: nextDay,
    days: days.map((d) => ({
      as_of: d.as_of,
      status: d.status,
      nav_per_share: null,
      open_cases: null,
      run_at: null,
      signed_off_by: d.status === "signed_off" ? "approver2" : null,
      signed_off_at: d.status === "signed_off" ? "2026-11-09T18:02:00+00:00" : null,
    })),
  };
}

export function dayRecord(fund: string, asOf: string, overrides: Partial<Day> = {}): Day {
  return {
    fund,
    as_of: asOf,
    status: "ready",
    previous_business_day: null,
    files: [],
    validation: null,
    error: null,
    run_by: "analyst1",
    run_at: "2026-11-10T08:00:00+00:00",
    signed_off_by: null,
    signed_off_at: null,
    nav: {
      nav: 251234567.89,
      nav_per_share: 102.345678,
      prior_nav_per_share: 102.3,
      detail: {
        gross_assets: 250000000,
        cash: 1500000,
        liabilities: 265432.11,
        nav: 251234567.89,
        nav_per_share: 102.345678,
        prior_nav_per_share: 102.3,
        movement: 0.000446,
      },
    },
    checks: [],
    release: { ready: false, reasons: [] },
    summary: null,
    job: null,
    ...overrides,
  };
}

export function releaseFor(fund: string, asOf: string, overrides: Partial<ReleaseForMe> = {}): ReleaseForMe {
  return {
    fund,
    as_of: asOf,
    day_status: "ready",
    signed_off: false,
    ready: false,
    reasons: [
      { code: "PENDING_DECISIONS", message: "3 cases still pending a decision.", case_ids: ["C1", "C2", "C3"] },
      { code: "MATERIAL_NOT_APPROVED", message: "1 material case not approved or reclassified.", case_ids: ["C1"] },
    ],
    checks: [],
    signable_by_me: false,
    blocking_for_me: [],
    ...overrides,
  };
}

/** The routes a signed-in session needs for one fund with one ready day. */
export function signedInRoutes(user: User = analyst): Record<string, RouteAnswer> {
  return {
    "GET /api/auth/me": { body: user },
    "GET /api/funds": { body: [fundA, fundB] },
    "GET /api/funds/GEF1/days": {
      body: daysList("GEF1", [
        { as_of: "2026-11-10", status: "ready" },
        { as_of: "2026-11-09", status: "signed_off" },
      ]),
    },
    "GET /api/funds/INC2/days": { body: daysList("INC2", [{ as_of: "2026-11-09", status: "signed_off" }], "2026-11-10") },
    "GET /api/funds/GEF1/days/2026-11-10": { body: dayRecord("GEF1", "2026-11-10") },
    "GET /api/funds/GEF1/days/2026-11-10/release": { body: releaseFor("GEF1", "2026-11-10") },
    "GET /api/funds/GEF1/days/2026-11-09": {
      body: dayRecord("GEF1", "2026-11-09", {
        status: "signed_off",
        signed_off_by: "approver2",
        signed_off_at: "2026-11-09T18:02:00+00:00",
      }),
    },
    "GET /api/funds/GEF1/days/2026-11-09/release": {
      body: releaseFor("GEF1", "2026-11-09", { day_status: "signed_off", signed_off: true, ready: true, reasons: [] }),
    },
    "GET /api/funds/INC2/days/2026-11-09": {
      body: dayRecord("INC2", "2026-11-09", { status: "signed_off", signed_off_by: "approver1" }),
    },
    "GET /api/funds/INC2/days/2026-11-09/release": {
      body: releaseFor("INC2", "2026-11-09", { signed_off: true, ready: true, reasons: [] }),
    },
  };
}
