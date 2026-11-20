/**
 * A whole business day worked from the keyboard alone, on the second fund (E2E2), against
 * the real API, worker and database. No mouse click anywhere: every field, button and link
 * is reached with Tab (or a shortcut, or the command palette) and used with the keys a
 * person would press.
 *
 * 1. The analyst signs in, loads day one's files through the file input and runs the day
 *    (unless the funds journey already did, when the suite runs in full), hearing the run
 *    finish in the live region, and moves to the cases: focus lands on each screen's title.
 * 2. The analyst approves, rejects with a note and reclassifies from the keyboard; each
 *    result is announced. The escalated cases are left to an approver.
 * 3. An approver decides the escalated cases; a second approver opens the sign-off dialog
 *    (focus moves in, is held there, and Esc returns it to the button), signs off, and
 *    focus lands on the result.
 * 4. The next business day opens: its files go in and it runs, from the keyboard.
 *
 * Self-contained: it reads the fund's state from the API and does whatever is left to do.
 */
import { type Locator, type Page, expect, test } from "@playwright/test";

import { DAY_ONE, DAY_TWO, PASSWORD, SECOND_FUND as FUND, dayFiles } from "./helpers";

test.describe.configure({ mode: "serial" });

interface DayRow {
  as_of: string;
  status: string;
}

interface QueueRow {
  case_id: string;
  category: string;
  escalated: boolean;
  status: string;
}

const announcer = (page: Page) => page.getByTestId("announcer");

async function isFocused(locator: Locator): Promise<boolean> {
  return locator.evaluate((el) => el === document.activeElement || el.contains(document.activeElement)).catch(() => false);
}

/** Press Tab (or Shift+Tab) until `target` has focus, proving it can be reached from the keyboard. */
async function tabTo(page: Page, target: Locator, max = 60, key: "Tab" | "Shift+Tab" = "Tab"): Promise<void> {
  for (let i = 0; i < max; i++) {
    if (await isFocused(target)) return;
    await page.keyboard.press(key);
  }
  expect(await isFocused(target), `could not reach ${target.toString()} with Tab`).toBe(true);
}

async function signInByKeyboard(page: Page, username: string): Promise<void> {
  await page.goto(`/signin`);
  await tabTo(page, page.getByLabel("Username"));
  await page.keyboard.type(username);
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Password")).toBeFocused();
  await page.keyboard.type(PASSWORD);
  await page.keyboard.press("Enter");
  await expect(page).not.toHaveURL(/\/signin/);
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
}

/** Ctrl+K, type, Enter: the palette's first match. */
async function palette(page: Page, query: string, option: RegExp): Promise<void> {
  await page.keyboard.press("Control+k");
  const dialog = page.getByRole("dialog", { name: "Command palette" });
  await expect(dialog.getByRole("combobox")).toBeFocused();
  await page.keyboard.type(query);
  await expect(dialog.getByRole("option", { selected: true })).toHaveText(option);
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
}

async function signOutByKeyboard(page: Page): Promise<void> {
  await palette(page, "Sign out", /Sign out/);
  await expect(page).toHaveURL(/\/signin/);
}

/** g then a screen's key, and focus on the new screen's title. */
async function goTo(page: Page, key: string, title: RegExp): Promise<void> {
  await page.keyboard.press("Escape"); // leave any field first
  await page.keyboard.press("g");
  await page.keyboard.press(key);
  const heading = page.getByRole("heading", { level: 1, name: title });
  await expect(heading).toBeFocused();
}

async function days(page: Page): Promise<DayRow[]> {
  return ((await (await page.request.get(`/api/funds/${FUND}/days`)).json()) as { days: DayRow[] }).days;
}

async function dayStatus(page: Page, asOf: string): Promise<string | undefined> {
  return (await days(page)).find((d) => d.as_of === asOf)?.status;
}

async function queue(page: Page, asOf: string): Promise<QueueRow[]> {
  return (await (await page.request.get(`/api/funds/${FUND}/days/${asOf}/cases`)).json()) as QueueRow[];
}

/** Choose the day's files through the file input, opened with the keyboard, then run the day. */
async function uploadAndRunByKeyboard(page: Page, asOf: string): Promise<void> {
  const input = page.getByLabel(/Choose the day/);
  await tabTo(page, input);
  const chooser = page.waitForEvent("filechooser");
  await page.keyboard.press("Space");
  await (await chooser).setFiles(dayFiles(asOf));
  await expect(page.locator(".up-validation").getByText(/^The files are valid/)).toBeVisible();

  const run = page.getByRole("button", { name: "Run the day" });
  await tabTo(page, run);
  await page.keyboard.press("Enter");
  await expect(announcer(page)).toHaveText(/The run has finished: .*open cases?\. The cases are ready\./, {
    timeout: 60_000,
  });
}

/** Open a case with the palette: its id, then Enter. */
async function openCase(page: Page, caseId: string): Promise<void> {
  await palette(page, caseId, new RegExp(caseId));
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
}

test("an analyst loads, runs and works the day from the keyboard", async ({ page }) => {
  await signInByKeyboard(page, "analyst1");
  await page.goto(`/upload?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("heading", { level: 1, name: "Upload and run" })).toBeFocused();

  const status = await dayStatus(page, DAY_ONE);
  if (!status || status === "uploaded" || status === "validated") {
    await uploadAndRunByKeyboard(page, DAY_ONE);
    const work = page.getByRole("link", { name: "Work the cases" });
    await tabTo(page, work);
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Cases" })).toBeFocused();
  } else {
    await goTo(page, "q", /^Cases/);
  }
  test.skip((await dayStatus(page, DAY_ONE)) === "signed_off", "day one is already signed off");

  const pending = (await queue(page, DAY_ONE)).filter((c) => c.status === "PENDING");
  const ordinary = pending.filter((c) => !c.escalated);
  expect(ordinary.length).toBeGreaterThan(0);
  const [first, second, third, ...rest] = ordinary;

  // a: approve.
  await openCase(page, first!.case_id);
  await page.keyboard.press("a");
  await expect(announcer(page)).toHaveText(new RegExp(`^Decision recorded: Approved ${first!.case_id}\\.`));
  await expect(page.locator(".wb-outcome-done")).toHaveText(`Approved ${first!.case_id}. Recorded in the audit log.`);

  // r: to the note, write it, Ctrl+Enter rejects.
  if (second) {
    await openCase(page, second.case_id);
    await page.keyboard.press("r");
    await expect(page.getByLabel(/^Note/)).toBeFocused();
    await page.keyboard.type("Custodian confirms its own booking error.");
    await page.keyboard.press("Control+Enter");
    await expect(announcer(page)).toHaveText(new RegExp(`^Decision recorded: Rejected ${second.case_id}\\.`));
  }

  // c: to the cause, an arrow picks another, Shift+Tab back to the note, Ctrl+Enter reclassifies.
  if (third) {
    await openCase(page, third.case_id);
    await page.keyboard.press("c");
    const cause = page.getByLabel("Reclassify as");
    await expect(cause).toBeFocused();
    const before = await cause.inputValue();
    await page.keyboard.press("ArrowDown");
    if ((await cause.inputValue()) === before) await page.keyboard.press("ArrowUp");
    expect(await cause.inputValue()).not.toBe(before);
    await tabTo(page, page.getByLabel(/^Note/), 6, "Shift+Tab"); // the note sits above the buttons
    await page.keyboard.type("The dates show a different cause.");
    await page.keyboard.press("Control+Enter");
    await expect(announcer(page)).toHaveText(new RegExp(`^Decision recorded: Reclassified ${third.case_id} as `));
  }

  for (const c of rest) {
    await openCase(page, c.case_id);
    await page.keyboard.press("a");
    await expect(announcer(page)).toHaveText(new RegExp(`^Decision recorded: Approved ${c.case_id}\\.`));
  }
  await signOutByKeyboard(page);
});

test("an approver decides the escalated cases from the keyboard", async ({ page }) => {
  await signInByKeyboard(page, "approver1");
  await page.goto(`/cases?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("heading", { level: 1, name: "Cases" })).toBeFocused();
  const escalated = (await queue(page, DAY_ONE)).filter((c) => c.escalated && c.status === "PENDING");
  for (const c of escalated) {
    await openCase(page, c.case_id);
    await page.keyboard.press("a");
    await expect(announcer(page)).toHaveText(new RegExp(`^Decision recorded: Approved ${c.case_id}\\.`));
  }
  await signOutByKeyboard(page);
});

test("a second approver signs off through the dialog, and the next day is loaded and run", async ({ page }) => {
  await signInByKeyboard(page, "approver2");
  await page.goto(`/overview?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeFocused();
  await goTo(page, "s", /sign-off/i);

  const signButton = page.locator(".so-sign").getByRole("button", { name: "Sign off NAV" });
  await expect(signButton).toBeEnabled();
  await tabTo(page, signButton);

  // The dialog takes focus (on Cancel, the safe choice), holds it, and Esc gives it back.
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Sign off the NAV?" });
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  for (let i = 0; i < 4; i++) {
    await page.keyboard.press("Tab");
    expect(await isFocused(dialog)).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(signButton).toBeFocused();

  // Again, and this time sign off: focus moves to the result, which is read out.
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Sign off NAV" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  const result = page.locator(".so-msg").filter({ hasText: "The day is locked" });
  await expect(result).toBeFocused();

  // The next business day is open: go to it and load and run it.
  const next = page.getByRole("button", { name: "Go to the next day" });
  await tabTo(page, next);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/signoff\\?.*day=${DAY_TWO}`)); // the screen moves to that day
  // The address changes a moment before the app has drawn the new day; wait for the app, as a person would.
  await expect(page.getByLabel("Business day")).toHaveValue(DAY_TWO);
  await goTo(page, "u", /^Upload and run/);
  await expect(page).toHaveURL(new RegExp(`day=${DAY_TWO}`));
  await uploadAndRunByKeyboard(page, DAY_TWO);
  expect(await dayStatus(page, DAY_TWO)).toBe("ready");
  await signOutByKeyboard(page);
});
