/**
 * Management information and the exports, against the real API, worker and database.
 *
 * Runs on E2E1 after the business-day journeys (which leave day one signed off and day two
 * run); run on its own, it loads and runs day one itself first. A viewer, who may read and
 * export but not act:
 *
 * 1. opens MI from the screen list and finds the server's figures: the open breaks by cause
 *    and age adding up to the day's open cases, the trend with one bar per run day, and
 *    the measure switch;
 * 2. downloads the exception report and mi.csv under the server's file names, with the
 *    engine's tidy columns, and finds both downloads in the day's audit trail.
 *
 * The screen is checked with axe in both themes, its expanders open.
 */
import fs from "node:fs";
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, FUND, dayFiles, expectAccessible, signIn, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

interface DaysList {
  days: { as_of: string; status: string; run_at: string | null }[];
}

interface MiBody {
  has_run: boolean;
  run_days: number;
  by_cause_age: { rows: { cause: string; count: number }[]; total: { count: number; gross: number; net: number } };
  trend: { as_of: string }[];
}

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "rp_csrf")?.value ?? "";
}

/** The fund's latest day with a finished run; loads and runs day one first if there is none. */
async function latestRunDay(page: Page): Promise<string> {
  const listed = async () => ((await (await page.request.get(`/api/funds/${FUND}/days`)).json()) as DaysList).days;
  let ran = (await listed()).find((d) => d.run_at && ["ready", "signed_off"].includes(d.status));
  if (!ran) {
    const headers = { "X-CSRF-Token": await csrf(page) };
    const form = new FormData();
    for (const file of dayFiles(DAY_ONE)) {
      form.append("files", new Blob([fs.readFileSync(file)], { type: "text/csv" }), path.basename(file));
    }
    const upload = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/files`, { headers, multipart: form });
    expect(upload.ok(), await upload.text()).toBeTruthy();
    const run = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/run`, { headers });
    expect(run.status()).toBe(202);
    await expect
      .poll(async () => (await listed()).find((d) => d.as_of === DAY_ONE)?.status, { timeout: 60_000 })
      .toBe("ready");
    ran = (await listed()).find((d) => d.as_of === DAY_ONE);
  }
  return ran!.as_of;
}

test("a viewer reads MI from the server's figures and switches the trend's measure", async ({ page }) => {
  await signIn(page, "analyst1");
  const day = await latestRunDay(page);
  await signOut(page);

  await signIn(page, "viewer1");
  await page.goto(`/overview?fund=${FUND}&day=${day}`);
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();
  const miLink = page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: /MI/ });
  await expect(miLink).toHaveAttribute("href", `/mi?fund=${FUND}&day=${day}`);
  await miLink.click();
  await expect(page).toHaveURL(new RegExp(`/mi\\?(?=.*fund=${FUND})(?=.*day=${day})`));
  await expect(page.getByRole("heading", { level: 1, name: "Management information" })).toBeVisible();

  const body = (await (await page.request.get(`/api/funds/${FUND}/days/${day}/mi`)).json()) as MiBody;
  const cases = (await (await page.request.get(`/api/funds/${FUND}/days/${day}/cases`)).json()) as unknown[];
  expect(body.has_run).toBe(true);
  expect(body.by_cause_age.total.count).toBe(cases.length);

  const byCause = page.getByRole("region", { name: "Open breaks by cause and age" });
  const matrix = byCause.getByRole("table").first();
  await expect(matrix.getByRole("row")).toHaveCount(body.by_cause_age.rows.length + 2);
  await expect(matrix.getByRole("row", { name: /All causes/ })).toContainText(String(body.by_cause_age.total.count));

  const trend = page.getByRole("region", { name: "Trend" });
  await expect(trend.locator(".mi-bar")).toHaveCount(body.run_days);
  await trend.getByRole("button", { name: "Cleared" }).click();
  await expect(trend.getByRole("button", { name: "Cleared" })).toHaveAttribute("aria-pressed", "true");
  await expect(trend.getByRole("img", { name: /^Cleared cases per run day/ })).toBeVisible();

  for (const summary of await page.locator(".mi-more summary").all()) await summary.click();
  await expectAccessible(page, "MI");
});

test("a viewer downloads both exports, and the audit trail records them", async ({ page }) => {
  await signIn(page, "viewer1");
  const days = ((await (await page.request.get(`/api/funds/${FUND}/days`)).json()) as DaysList).days;
  const day = days.find((d) => d.run_at && ["ready", "signed_off"].includes(d.status))!.as_of;
  await page.goto(`/mi?fund=${FUND}&day=${day}`);
  const exports = page.getByRole("group", { name: "Exports for this day" });

  const [report] = await Promise.all([
    page.waitForEvent("download"),
    exports.getByRole("button", { name: /Exception report/ }).click(),
  ]);
  expect(report.suggestedFilename()).toBe(`exceptions_${FUND}_${day}.xlsx`);
  const reportPath = await report.path();
  expect(fs.readFileSync(reportPath).subarray(0, 2).toString()).toBe("PK"); // an Excel workbook is a zip
  await expect(page.getByText(`Downloaded exceptions_${FUND}_${day}.xlsx.`)).toBeVisible();

  const [csv] = await Promise.all([
    page.waitForEvent("download"),
    exports.getByRole("button", { name: /MI data/ }).click(),
  ]);
  expect(csv.suggestedFilename()).toBe(`mi_${FUND}_${day}.csv`);
  const lines = fs.readFileSync(await csv.path(), "utf-8").split("\r\n");
  expect(lines[0]).toBe("as_of,metric,cause,age_bucket,value");
  expect(lines.some((line) => line.startsWith(`${day},open_cases,ALL,ALL,`))).toBe(true);

  const trail = (await (await page.request.get(`/api/funds/${FUND}/days/${day}/audit`)).json()) as {
    entries: { actor: string; action: string; payload: { export?: string } }[];
    chain_ok: boolean;
  };
  const downloads = trail.entries.filter((e) => e.action === "EXPORT_DOWNLOADED" && e.actor === "viewer1");
  expect(downloads.map((e) => e.payload.export).slice(-2)).toEqual(["exception_report", "mi_csv"]);
  expect(trail.chain_ok).toBe(true);
});
