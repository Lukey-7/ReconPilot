/**
 * Several funds and the upload screen, against the real API, worker and database, on the
 * second fund (E2E2) so the business-day journeys on E2E1 are untouched:
 *
 * 1. the analyst opens the funds screen, reads both funds and the settings read-only,
 *    switches to the second fund, and finds it again after signing in afresh;
 * 2. the analyst loads part of the first day's files and sees, per file, what is missing,
 *    then the rest; runs the day and sees the run in the day's history;
 * 3. the next business day cannot take files while the first is not signed off: the
 *    screen says so in plain words and leads to the sign-off; the server agrees.
 *
 * The analyst's stored fund is cleared at the end, so the order of the spec files does
 * not matter. Every new view is checked with axe in both themes.
 */
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, DAY_TWO, SECOND_FUND, dayFiles, expectAccessible, signIn, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

const DAY_ONE_LABEL = "Mon 9 Nov 2026";
const DAY_TWO_LABEL = "Tue 10 Nov 2026";

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "rp_csrf")?.value ?? "";
}

test.afterAll(async ({ browser }) => {
  // Leave analyst1 with no stored fund, as the server started.
  const page = await browser.newPage();
  await signIn(page, "analyst1");
  await page.request.put("/api/auth/me/preferences", { data: { fund: null }, headers: { "X-CSRF-Token": await csrf(page) } });
  await page.close();
});

test("the analyst reads every fund's settings, switches fund, and the choice follows them", async ({ page }) => {
  await signIn(page, "analyst1");
  await page.getByRole("link", { name: /^Funds/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Funds" })).toBeVisible();
  const list = page.getByRole("list", { name: /Every fund/ });
  await expect(list.getByRole("listitem")).toHaveCount(2);
  await expect(list.getByRole("listitem").filter({ hasText: "E2E1" })).toContainText("Working");
  const settings = page.getByRole("region", { name: /Settings for E2E1/ });
  await expect(settings.getByText("Read-only")).toBeVisible();
  await expect(settings.getByText("1.00 bp of NAV")).toBeVisible();
  await expect(settings.getByText("Engine default")).toHaveCount(4);
  await expect(page.getByRole("main").getByRole("textbox")).toHaveCount(0);
  await expectAccessible(page, "Funds");

  await page.getByRole("button", { name: `Work this fund: ${SECOND_FUND}` }).click();
  await expect(page).toHaveURL(new RegExp(`fund=${SECOND_FUND}`));
  await expect(page.getByRole("region", { name: new RegExp(`Settings for ${SECOND_FUND}`) })).toBeVisible();
  await expect(page.getByRole("combobox", { name: /^Fund/ })).toHaveValue(SECOND_FUND);
  await signOut(page);

  // A fresh session, with no fund in the address, opens the fund the analyst chose.
  await signIn(page, "analyst1");
  await page.goto("/overview");
  await expect(page).toHaveURL(new RegExp(`/overview\\?fund=${SECOND_FUND}`));
  await expect(page.getByRole("combobox", { name: /^Fund/ })).toHaveValue(SECOND_FUND);

  // Other users keep their own choice.
  await signOut(page);
  await signIn(page, "viewer1");
  await page.goto("/overview");
  await expect(page).toHaveURL(/\/overview\?fund=E2E1/);
  await signOut(page);
});

test("the analyst loads the files in two goes, sees each file's checks, and runs the day", async ({ page }) => {
  await signIn(page, "analyst1");
  await page.goto(`/upload?fund=${SECOND_FUND}`);
  await expect(page.getByRole("heading", { level: 1, name: "Upload and run" })).toBeVisible();
  await expect(page.getByText(`No files have been uploaded for ${DAY_ONE_LABEL} yet.`)).toBeVisible();

  const files = dayFiles(DAY_ONE);
  const first = files.filter((f) => ["fund.csv", "securities.csv"].includes(path.basename(f)));
  await page.getByLabel(/Choose the day/).setInputFiles(first);
  await expect(page.getByText(/problems? blocks? the run/)).toBeVisible();
  const checklist = page.getByRole("table", { name: `Files held for ${DAY_ONE_LABEL}` });
  await expect(checklist.getByRole("row", { name: /^book_trades\.csv/ })).toContainText("Missing, needed for the run");
  await expect(checklist.getByRole("row", { name: /^fund\.csv/ })).toContainText("analyst1");
  await expect(page.getByRole("button", { name: "Run the day" })).toHaveCount(0);
  await expectAccessible(page, "Upload and run, files missing");

  await page.getByLabel(/Choose the day/).setInputFiles(files.filter((f) => !first.includes(f)));
  await expect(page.locator(".up-validation").getByText(/^The files are valid/)).toBeVisible();
  await expect(checklist.getByText("Missing, needed for the run")).toHaveCount(0);
  await page.getByRole("button", { name: "Run the day" }).click();
  await expect(page.getByRole("link", { name: "Work the cases" })).toBeVisible({ timeout: 60_000 });

  const runs = page.getByRole("table", { name: `Runs of ${DAY_ONE_LABEL}, newest first` });
  await expect(runs.getByRole("row")).toHaveCount(2);
  await expect(runs).toContainText("analyst1");
  await expect(runs).toContainText("Finished");
  await expect(runs).toContainText(/open cases? \(/);
  await expect(page.getByText(`${DAY_TWO_LABEL} opens for its files once ${DAY_ONE_LABEL} is signed off.`)).toBeVisible();
  await expectAccessible(page, "Upload and run, with run history");
});

test("the next day says plainly that the previous day is not signed off", async ({ page }) => {
  await signIn(page, "analyst1");
  await page.goto(`/upload?fund=${SECOND_FUND}&day=${DAY_TWO}`);
  await expect(page.getByText(`${DAY_ONE_LABEL} is not signed off yet.`)).toBeVisible();
  await expect(
    page.getByText(
      `Days are worked in order, so ${DAY_TWO_LABEL}’s files can be loaded only after that day’s NAV is signed off.`,
      { exact: false },
    ),
  ).toBeVisible();
  await expect(page.getByLabel(/Choose the day/)).toHaveCount(0);
  await expectAccessible(page, "Upload and run, previous day not signed off");

  // The server refuses the same upload in its own words.
  const refused = await page.request.post(`/api/funds/${SECOND_FUND}/days/${DAY_TWO}/files`, {
    headers: { "X-CSRF-Token": await csrf(page) },
    multipart: { files: { name: "fund.csv", mimeType: "text/csv", buffer: Buffer.from("key,value\n") } },
  });
  expect(refused.status()).toBe(409);
  expect((await refused.json()).detail).toBe(`Sign off ${DAY_ONE} first.`);

  await page.getByRole("link", { name: `Open the sign-off for ${DAY_ONE_LABEL}` }).click();
  await expect(page).toHaveURL(new RegExp(`/signoff\\?fund=${SECOND_FUND}&day=${DAY_ONE}`));
  await expect(page.getByRole("heading", { level: 1, name: /sign-off/i })).toBeVisible();
  await signOut(page);
});
