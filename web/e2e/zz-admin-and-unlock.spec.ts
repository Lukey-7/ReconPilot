/**
 * Administration and unlocking a signed-off day, against the real API, worker and database.
 *
 * Runs last (its name sorts after the other journeys) on a fund it creates itself, so the
 * other journeys' funds and days are untouched.
 *
 * 1. An administrator opens Administration from the user menu, adds a user, changes their
 *    role and deactivates them; adds a fund, changes its materiality and calendar, and finds
 *    AI off. Both tabs are checked with axe in both themes.
 * 2. The new fund's first day is run, decided and signed off (through the API).
 * 3. The administrator asks to unlock the day, with a reason, on the sign-off screen.
 * 4. An approver confirms: the day is open again, and a second approver signs it off again.
 *    The sign-off screen with the waiting request is checked with axe.
 */
import fs from "node:fs";
import path from "node:path";

import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, dayFiles, expectAccessible, signIn, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

const FUND = "E2E9";
const FUND_NAME = "Unlock Test Fund";
const DAY_LABEL = "Mon 9 Nov 2026";
const REASON = "The custodian restated a closing price for 9 November after release.";

interface QueueCase {
  case_id: string;
  version: number;
  status: string;
  escalated: boolean;
}

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "rp_csrf")?.value ?? "";
}

async function dayStatus(page: Page): Promise<string | undefined> {
  const body = (await (await page.request.get(`/api/funds/${FUND}/days`)).json()) as {
    days: { as_of: string; status: string }[];
  };
  return body.days.find((d) => d.as_of === DAY_ONE)?.status;
}

async function approve(page: Page, escalated: boolean): Promise<void> {
  const headers = { "X-CSRF-Token": await csrf(page) };
  const cases = (await (await page.request.get(`/api/funds/${FUND}/days/${DAY_ONE}/cases`)).json()) as QueueCase[];
  for (const c of cases.filter((c) => c.escalated === escalated && c.status === "PENDING")) {
    const response = await page.request.post(`/api/funds/${FUND}/cases/${c.case_id}/decision`, {
      headers,
      data: { decision: "approve", version: c.version, note: "" },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
}

test("an administrator manages a user and a fund", async ({ page }) => {
  await signIn(page, "admin1");
  await expect(page).toHaveURL(/fund=/); // the overview has settled on a fund
  // The menu closes if focus moves while the screen settles; open it again until the entry is clicked.
  await expect(async () => {
    if (!(await page.getByRole("menuitem", { name: "Administration" }).isVisible())) {
      await page.locator(".user-btn").click();
    }
    await page.getByRole("menuitem", { name: "Administration" }).click({ timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Administration: users" })).toBeVisible();
  const users = page.getByRole("table", { name: /Every user/ });
  await expect(users.getByRole("row", { name: /Admin One/ })).toContainText("You");
  await expectAccessible(page, "Administration: users");

  await page.getByRole("button", { name: "Add a user" }).click();
  const add = page.getByRole("dialog", { name: "Add a user" });
  await add.getByLabel("Username").fill("temp9");
  await add.getByLabel("Name", { exact: true }).fill("Temporary Nine");
  await add.getByLabel("Role").selectOption("viewer");
  await add.getByLabel("Password", { exact: true }).fill("Harbour-Lantern-9052");
  await add.getByLabel("Password again").fill("Harbour-Lantern-9052");
  await add.getByRole("button", { name: "Add user" }).click();
  await expect(add).toBeHidden();
  const row = users.getByRole("row", { name: /Temporary Nine/ });
  await expect(row).toContainText("Viewer");

  await row.getByRole("button", { name: /Manage/ }).click();
  const manage = page.getByRole("dialog", { name: /Manage Temporary Nine/ });
  await manage.getByLabel("Role").selectOption("analyst");
  await manage.getByRole("button", { name: "Change role" }).click();
  await expect(manage.getByText("Temporary Nine is now analyst.", { exact: false })).toBeVisible();
  await manage.getByRole("button", { name: "Deactivate" }).click();
  await expect(manage.getByText(/deactivated and can no longer sign in/)).toBeVisible();
  await manage.getByRole("button", { name: "Done" }).click();
  await expect(row).toContainText("Deactivated");

  await page.getByRole("navigation", { name: "Administration" }).getByRole("link", { name: "Funds" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Administration: funds" })).toBeVisible();
  await page.getByRole("button", { name: "Add a fund" }).click();
  const newFund = page.getByRole("dialog", { name: "Add a fund" });
  await newFund.getByLabel("Fund code").fill(FUND);
  await newFund.getByLabel("Fund name").fill(FUND_NAME);
  await newFund.getByLabel("First business day").fill(DAY_ONE);
  await newFund.getByRole("button", { name: "Add fund" }).click();
  await expect(newFund).toBeHidden();
  await expect(page).toHaveURL(new RegExp(`fund=${FUND}`));

  const settings = page.getByRole("region", { name: `Settings for ${FUND}` });
  await settings.getByLabel("Materiality").fill("0.5");
  await settings.getByRole("button", { name: "Save settings" }).click();
  await expect(settings.getByText(/Saved. Applies from the next run/)).toBeVisible();

  const calendar = page.getByRole("region", { name: "Business calendar" });
  await calendar.getByLabel("Add a non-business day").fill("2026-12-25");
  await calendar.getByRole("button", { name: "Add" }).click();
  await expect(calendar.getByRole("list", { name: "Non-business days" })).toContainText("Fri 25 Dec 2026");

  const ai = page.getByRole("region", { name: "AI second opinion" });
  await expect(ai.getByText("Off", { exact: true })).toBeVisible();
  await expectAccessible(page, "Administration: funds");

  // Every change is in the audit log under the administrator's name.
  const log = (await (await page.request.get(`/api/audit?fund=${FUND}&limit=200`)).json()) as {
    entries: { action: string; actor: string }[];
  };
  const actions = log.entries.map((e) => e.action);
  expect(actions).toEqual(expect.arrayContaining(["FUND_CREATED", "FUND_SETTINGS_CHANGED", "FUND_CALENDAR_CHANGED"]));
  await signOut(page);
});

test("the new fund's first day is run, decided and signed off", async ({ page }) => {
  await signIn(page, "analyst1");
  const headers = { "X-CSRF-Token": await csrf(page) };
  const form = new FormData();
  for (const file of dayFiles(DAY_ONE)) {
    form.append("files", new Blob([fs.readFileSync(file)], { type: "text/csv" }), path.basename(file));
  }
  const upload = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/files`, { headers, multipart: form });
  expect(upload.ok(), await upload.text()).toBeTruthy();
  expect((await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/run`, { headers })).status()).toBe(202);
  await expect.poll(() => dayStatus(page), { timeout: 60_000 }).toBe("ready");
  await approve(page, false);
  await signOut(page);
  await signIn(page, "approver1");
  await approve(page, true);
  await signOut(page);
  await signIn(page, "approver2");
  const signoff = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/signoff`, {
    headers: { "X-CSRF-Token": await csrf(page) },
  });
  expect(signoff.ok(), await signoff.text()).toBeTruthy();
  await signOut(page);
});

test("an administrator asks to unlock the signed-off day, with a reason", async ({ page }) => {
  await signIn(page, "admin1");
  await page.goto(`/signoff?fund=${FUND}&day=${DAY_ONE}`);
  const panel = page.getByRole("region", { name: "Unlock this day" });
  await panel.getByRole("button", { name: "Ask to unlock…" }).click();
  const dialog = page.getByRole("dialog", { name: `Ask to unlock ${DAY_LABEL}?` });
  await dialog.getByLabel("Reason").fill(REASON);
  await dialog.getByRole("button", { name: "Ask to unlock" }).click();
  await expect(dialog).toBeHidden();
  const waiting = page.getByRole("region", { name: "Unlock requested" });
  await expect(waiting).toContainText(REASON);
  await expect(waiting.getByRole("button", { name: /Confirm/ })).toHaveCount(0); // never their own
  expect(await dayStatus(page)).toBe("signed_off");
  await signOut(page);
});

test("a different approver confirms; the day must be signed off again", async ({ page }) => {
  await signIn(page, "approver1");
  await page.goto(`/signoff?fund=${FUND}&day=${DAY_ONE}`);
  const waiting = page.getByRole("region", { name: "Unlock requested" });
  await expect(waiting).toContainText("admin1 asked to unlock");
  await expectAccessible(page, "Sign-off with an unlock waiting");
  await waiting.getByRole("button", { name: "Confirm unlock…" }).click();
  const dialog = page.getByRole("dialog", { name: `Unlock ${DAY_LABEL}?` });
  await dialog.getByLabel("Note (optional)").fill("Agreed: the restated price is confirmed by the custodian.");
  await dialog.getByRole("button", { name: "Unlock the day" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(`${DAY_LABEL} is unlocked. It must be signed off again.`)).toBeVisible();
  await expect.poll(() => dayStatus(page)).toBe("ready");
  await signOut(page);

  await signIn(page, "approver2");
  await page.goto(`/signoff?fund=${FUND}&day=${DAY_ONE}`);
  await page.getByRole("button", { name: "Sign off NAV" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Sign off NAV" }).click();
  await expect.poll(() => dayStatus(page)).toBe("signed_off");
  const log = (await (await page.request.get(`/api/audit?fund=${FUND}&limit=200`)).json()) as { entries: { action: string }[] };
  const actions = log.entries.map((e) => e.action);
  expect(actions).toEqual(expect.arrayContaining(["UNLOCK_REQUESTED", "DAY_UNLOCKED"]));
  expect(actions.filter((a) => a === "DAY_SIGNED_OFF")).toHaveLength(2);
  await signOut(page);
});
