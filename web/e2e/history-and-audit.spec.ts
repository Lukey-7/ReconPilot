/**
 * History across days and the audit log, against the real API, worker and database.
 *
 * Runs on E2E1 after the business-day journeys, which leave day one signed off and day two
 * run with cases carried from day one (files run in name order). Run on its own, it works
 * those two days through the API first.
 *
 * 1. An analyst opens a carried case on day two and finds it across both days, opens it as
 *    it stood on day one, and reads the overview trend's impact per day, gross beside net.
 * 2. A viewer, who may read, verify and export but not act, filters the audit log to one
 *    case's approval, opens the entry with the server's check of it, verifies the whole
 *    chain and exports the CSV (file name and columns checked).
 *
 * The audit log screen is checked with axe in both themes.
 */
import fs from "node:fs";
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, DAY_TWO, FUND, dayCases, dayFiles, expectAccessible, signIn, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

const DAY_ONE_LABEL = "Mon 9 Nov 2026";

interface DaysList {
  days: { as_of: string; status: string; run_at: string | null }[];
}

interface QueueCase {
  case_id: string;
  version: number;
  status: string;
  escalated: boolean;
}

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "rp_csrf")?.value ?? "";
}

async function days(page: Page): Promise<DaysList["days"]> {
  return ((await (await page.request.get(`/api/funds/${FUND}/days`)).json()) as DaysList).days;
}

async function dayStatus(page: Page, asOf: string): Promise<string | undefined> {
  return (await days(page)).find((d) => d.as_of === asOf)?.status;
}

/** Upload and run a day through the API as the signed-in analyst, and wait for the run. */
async function loadAndRun(page: Page, asOf: string): Promise<void> {
  const headers = { "X-CSRF-Token": await csrf(page) };
  const form = new FormData();
  for (const file of dayFiles(asOf)) {
    form.append("files", new Blob([fs.readFileSync(file)], { type: "text/csv" }), path.basename(file));
  }
  const upload = await page.request.post(`/api/funds/${FUND}/days/${asOf}/files`, { headers, multipart: form });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  const run = await page.request.post(`/api/funds/${FUND}/days/${asOf}/run`, { headers });
  expect(run.status()).toBe(202);
  await expect.poll(() => dayStatus(page, asOf), { timeout: 60_000 }).toBe("ready");
}

/** Approve the day's pending cases as the signed-in user: escalated ones only, or only the others. */
async function approve(page: Page, asOf: string, escalated: boolean): Promise<void> {
  const headers = { "X-CSRF-Token": await csrf(page) };
  const cases = (await (await page.request.get(`/api/funds/${FUND}/days/${asOf}/cases`)).json()) as QueueCase[];
  for (const c of cases.filter((c) => c.escalated === escalated && (escalated || c.status === "PENDING"))) {
    const response = await page.request.post(`/api/funds/${FUND}/cases/${c.case_id}/decision`, {
      headers,
      data: { decision: "approve", version: c.version, note: "" },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
}

/** Day one signed off and day two run, as the business-day journeys leave them; worked here when run alone. */
async function ensureTwoDays(page: Page): Promise<void> {
  await signIn(page, "analyst1");
  const ran = (await days(page)).find((d) => d.as_of === DAY_TWO && d.run_at);
  if (ran) {
    await signOut(page);
    return;
  }
  if ((await dayStatus(page, DAY_ONE)) === undefined) await loadAndRun(page, DAY_ONE);
  if ((await dayStatus(page, DAY_ONE)) !== "signed_off") {
    await approve(page, DAY_ONE, false);
    await signOut(page);
    await signIn(page, "approver1");
    await approve(page, DAY_ONE, true);
    await signOut(page);
    await signIn(page, "approver2");
    const signoff = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/signoff`, {
      headers: { "X-CSRF-Token": await csrf(page) },
    });
    expect(signoff.ok(), await signoff.text()).toBeTruthy();
    await signOut(page);
    await signIn(page, "analyst1");
  }
  await loadAndRun(page, DAY_TWO);
  await signOut(page);
}

/** A case on day two carried from day one (its id names day one, not day two). */
async function carriedCase(page: Page): Promise<string> {
  const carried = (await dayCases(page, DAY_TWO)).filter((c) => !c.case_id.includes(DAY_TWO.replaceAll("-", "")));
  expect(carried.length).toBeGreaterThan(0);
  return carried[0]!.case_id;
}

test("an analyst follows a carried case across days and reads the trend's impact per day", async ({ page }) => {
  await ensureTwoDays(page);
  await signIn(page, "analyst1");
  const caseId = await carriedCase(page);

  await page.goto(`/cases?fund=${FUND}&day=${DAY_TWO}&case=${caseId}`);
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
  const across = page.getByRole("region", { name: "Across days" });
  await expect(across).toContainText(`first seen ${DAY_ONE_LABEL}`);
  const rows = across.getByRole("row");
  await expect(rows).toHaveCount(3); // the header and one row per day
  await expect(rows.nth(2)).toHaveAttribute("aria-current", "date");
  await expect(rows.nth(1)).toContainText(/Approved|Rejected|Reclassified/); // decided before day one was signed off

  await across.getByRole("link", { name: DAY_ONE_LABEL }).click();
  await expect(page).toHaveURL(new RegExp(`day=${DAY_ONE}.*case=${caseId}|case=${caseId}.*day=${DAY_ONE}`));
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
  await expect(page.getByRole("region", { name: "Across days" }).getByRole("row").nth(1)).toHaveAttribute(
    "aria-current",
    "date",
  );

  await page.goto(`/overview?fund=${FUND}&day=${DAY_TWO}`);
  const trend = page.getByRole("region", { name: "Trend" });
  await trend.getByText("Show the figures").click();
  const table = trend.getByRole("table");
  await expect(table.getByRole("columnheader", { name: "Open impact" })).toBeVisible();
  await expect(table.getByRole("row", { name: new RegExp(DAY_ONE_LABEL) })).toContainText(/net [+−]?[\d,]+\.\d\d/);
  await table.getByRole("link", { name: DAY_ONE_LABEL }).click();
  await expect(page).toHaveURL(new RegExp(`/overview\\?fund=${FUND}&day=${DAY_ONE}`));
  await expect(page.getByText(`End-to-End Test Fund, ${DAY_ONE_LABEL}`)).toBeVisible();
});

test("a viewer filters the audit log to a case, checks an entry, verifies the chain and exports it", async ({
  page,
}) => {
  await signIn(page, "viewer1");
  const approvals = (await (
    await page.request.get(`/api/audit?fund=${FUND}&action=CASE_APPROVED`)
  ).json()) as { entries: { case_id: string }[] };
  const caseId = approvals.entries[0]!.case_id;
  await page.goto(`/overview?fund=${FUND}&day=${DAY_TWO}`);
  const link = page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: /Audit log/ });
  await expect(link).toHaveAttribute("href", `/audit?fund=${FUND}&day=${DAY_TWO}`);
  await link.click();
  await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();
  await expect(page.getByRole("table", { name: /Audit log entries/ })).toBeVisible();

  const filters = page.getByRole("search", { name: "Filter the audit log" });
  await filters.getByRole("combobox", { name: /^Action/ }).selectOption({ label: "Approved" });
  const caseField = filters.getByRole("searchbox", { name: "Case" });
  await caseField.fill(caseId);
  await caseField.press("Enter");
  await expect(page).toHaveURL(new RegExp(`case=${caseId}`));
  const table = page.getByRole("table", { name: /Audit log entries/ });
  const rows = table.locator("tbody tr");
  const matching = (await (
    await page.request.get(`/api/audit?fund=${FUND}&action=CASE_APPROVED&case=${caseId}`)
  ).json()) as { total: number };
  const count = matching.total;
  expect(count).toBeGreaterThan(0);
  await expect(page.getByText(`1 to ${count} of ${count} ${count === 1 ? "entry" : "entries"}, newest first`)).toBeVisible();
  await expect(rows).toHaveCount(count);
  for (let i = 0; i < count; i += 1) {
    await expect(rows.nth(i)).toContainText("Approved");
    await expect(rows.nth(i)).toContainText(caseId);
  }

  await rows.first().getByRole("button", { name: /show its full record/ }).click();
  await expect(page.getByText("Its hash recomputes from what it records.")).toBeVisible();
  await expect(page.getByText(/It names the hash of entry #\d+\./)).toBeVisible();

  await page.getByRole("button", { name: "Verify chain" }).click();
  await expect(page.getByText("Chain intact.")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Chain intact." })).toContainText("by you");

  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
  const today = new Date().toISOString().slice(0, 10);
  expect(download.suggestedFilename()).toBe(`audit_${FUND}_${today}.csv`);
  const lines = fs.readFileSync(await download.path(), "utf-8").split("\r\n").filter(Boolean);
  expect(lines[0]).toBe("seq,ts,actor,role,action,fund,case_id,payload,prev_hash,hash");
  expect(lines.length).toBe(count + 1);
  expect(lines.slice(1).every((line) => line.includes(",CASE_APPROVED,") && line.includes(caseId))).toBe(true);
  await expect(page.getByText(`Downloaded audit_${FUND}_${today}.csv.`)).toBeVisible();

  // The verification and the export are themselves in the log.
  await filters.getByRole("button", { name: "Clear filters" }).click();
  await filters.getByRole("combobox", { name: /^Entries/ }).selectOption({ label: "Every fund and sign-ins" });
  const latest = page.getByRole("table", { name: /Audit log entries/ }).locator("tbody tr");
  await expect(latest.nth(0)).toContainText("Export downloaded");
  await expect(latest.nth(1)).toContainText("Chain verified");
  await latest.nth(1).getByRole("button", { name: /show its full record/ }).click();
  await expect(page.getByText(/"intact": true/)).toBeVisible();

  await expectAccessible(page, "Audit log");
});
