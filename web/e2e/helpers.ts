/**
 * Shared steps for the browser journeys: signing in and out, the generated day files, the
 * day's cases as the API reports them, and the accessibility check run on every screen.
 */
import fs from "node:fs";
import path from "node:path";

import AxeBuilder from "@axe-core/playwright";
import { type Page, expect } from "@playwright/test";

/** The funds and users scripts/e2e_server.py creates. */
export const FUND = "E2E1";
export const SECOND_FUND = "E2E2";
export const PASSWORD = process.env.RP_E2E_PASSWORD ?? "Ledger-Walrus-4817";
export const DAY_ONE = "2026-11-09";
export const DAY_TWO = "2026-11-10";

/** The CSV files the server generated for `asOf`, ready for a file input. */
export function dayFiles(asOf: string): string[] {
  const dataDir = process.env.RP_E2E_DATA_DIR;
  if (!dataDir) throw new Error("RP_E2E_DATA_DIR is not set; run the tests through playwright.config.ts");
  const folder = path.join(dataDir, "days", asOf);
  return fs
    .readdirSync(folder)
    .filter((name) => name.endsWith(".csv"))
    .map((name) => path.join(folder, name));
}

export async function signIn(page: Page, username: string): Promise<void> {
  await page.goto("/signin");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/signin/);
  await expect(page.locator(".user-btn")).toBeVisible();
}

export async function signOut(page: Page): Promise<void> {
  await page.locator(".user-btn").click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin/);
}

export interface QueueRow {
  case_id: string;
  category: string;
  material: boolean;
  escalated: boolean;
  status: string;
}

/** The day's open cases as the API reports them to the signed-in user. */
export async function dayCases(page: Page, asOf: string): Promise<QueueRow[]> {
  const response = await page.request.get(`/api/funds/${FUND}/days/${asOf}/cases`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as QueueRow[];
}

/**
 * Wait until no finite animation is running: axe blends text into its background by the
 * opacity it has mid-animation (a screen fading in), which would report false failures.
 */
async function settled(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      document
        .getAnimations()
        .every((a) => a.playState !== "running" || a.effect?.getComputedTiming().iterations === Infinity),
    undefined,
    { timeout: 5_000 },
  ).catch(() => undefined); // still moving after 5 s: let axe judge the page as it is
}

/**
 * Run axe (WCAG 2.0 to 2.2, A and AA) on the page as it stands, in the dark theme and then
 * the light one, and fail on any serious or critical violation.
 */
export async function expectAccessible(page: Page, screen: string): Promise<void> {
  // Dark is the default whatever the system prefers; light is the theme button's choice
  // (data-theme="light" on <html>), so the light pass sets that and the end puts it back.
  const chosen = await page.locator("html").getAttribute("data-theme");
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const colorScheme of ["dark", "light"] as const) {
    await showTheme(page, colorScheme);
    await expect(page.locator("html")).toHaveCSS("color-scheme", colorScheme);
    await settled(page);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    const summary = serious.map((v) => ({
      rule: v.id,
      impact: v.impact,
      help: v.help,
      targets: v.nodes.slice(0, 5).map((n) => `${n.target.join(" ")}: ${n.failureSummary ?? ""}`),
    }));
    expect(summary, `${screen} (${colorScheme} theme) has serious accessibility violations`).toEqual([]);
  }
  await showTheme(page, chosen === "light" ? "light" : "dark");
}

/** Show the page in a theme as the theme button would: light by data-theme, dark by default. */
export async function showTheme(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.evaluate((t) => {
    if (t === "light") document.documentElement.setAttribute("data-theme", "light");
    else document.documentElement.removeAttribute("data-theme");
  }, theme);
}
