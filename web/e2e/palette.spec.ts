/**
 * The command palette and the shortcuts, against the real API, worker and database.
 *
 * Runs on E2E1 after the business-day journeys (which leave days run); run on its own, it
 * loads and runs day one itself first. An analyst:
 *
 * 1. opens the palette with Ctrl+K from the overview (checked with axe in both themes),
 *    finds a case of the day by its id and opens it in the workbench;
 * 2. approves nothing by accident: the palette's decisions name the open case;
 * 3. reaches the audit log with g then l, and finds Ctrl+K in the shortcuts dialog (?).
 */
import fs from "node:fs";
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, FUND, dayCases, dayFiles, expectAccessible, signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

interface DaysList {
  days: { as_of: string; status: string; run_at: string | null }[];
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

test("an analyst jumps to a case with the palette and moves between screens by keyboard", async ({ page }) => {
  await signIn(page, "analyst1");
  const day = await latestRunDay(page);
  const cases = await dayCases(page, day);
  expect(cases.length).toBeGreaterThan(0);
  const target = cases[cases.length - 1]!.case_id;

  await page.goto(`/overview?fund=${FUND}&day=${day}`);
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette).toBeVisible();
  const field = palette.getByRole("combobox");
  await expect(field).toBeFocused();
  await expect(palette.getByRole("group", { name: /^Cases/ })).toBeVisible();
  await expectAccessible(page, "Command palette");

  await field.fill(target);
  await expect(palette.getByRole("option", { selected: true })).toContainText(target);
  await page.keyboard.press("Enter");
  await expect(palette).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`/cases\\?.*case=${target}`));
  await expect(page.getByRole("heading", { level: 2, name: target })).toBeVisible();

  // On the workbench the palette's decisions name the open case; Esc closes it untouched.
  await page.keyboard.press("Control+k");
  await expect(palette).toBeVisible();
  const signedOff = (await (await page.request.get(`/api/funds/${FUND}/days/${day}`)).json()).status === "signed_off";
  if (!signedOff) await expect(palette.getByRole("option", { name: new RegExp(`^Approve ${target}`) })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  await page.keyboard.press("g");
  await page.keyboard.press("l");
  await expect(page.getByRole("heading", { level: 1, name: "Audit log" })).toBeVisible();

  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help.getByText("Jump to a case, screen, fund or day, or run an action")).toBeVisible();
  await expect(help.getByText("Filter the log by case")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
});
