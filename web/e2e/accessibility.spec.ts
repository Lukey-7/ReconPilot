/**
 * The pages the journeys pass through without stopping, checked with axe in both themes,
 * and the focus rules every screen shares:
 *
 * - sign-in, before and after a failed attempt (the error takes focus and is announced);
 * - a page that does not exist;
 * - the shortcuts dialog (?): focus moves in, Esc closes it and gives focus back;
 * - moving to another screen puts focus on its title and names it in the browser tab.
 *
 * Needs no day to have been run, so it can run first or on its own.
 */
import { expect, test } from "@playwright/test";

import { FUND, expectAccessible, signIn } from "./helpers";

test("sign-in passes axe in both themes, and a failed attempt takes focus", async ({ page }) => {
  await page.goto("/signin");
  await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
  await expect(page).toHaveTitle("Sign in · ReconPilot");
  await expectAccessible(page, "Sign-in");

  // An account that does not exist, so no real user's failure count moves.
  await page.getByLabel("Username").fill("no-such-user");
  await page.getByLabel("Password").fill("not the password at all");
  await page.getByRole("button", { name: "Sign in" }).click();
  const error = page.getByRole("alert");
  await expect(error).toBeVisible();
  await expect(error).toBeFocused();
  await expectAccessible(page, "Sign-in, failed");
});

test("a page that does not exist passes axe and says so", async ({ page }) => {
  await signIn(page, "analyst1");
  await page.goto("/no-such-page");
  await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  await expect(page).toHaveTitle("Page not found · ReconPilot");
  await expectAccessible(page, "Page not found");
});

test("focus follows the person: screen titles after a move, and in and out of the shortcuts dialog", async ({
  page,
}) => {
  await signIn(page, "analyst1");
  await page.goto(`/overview?fund=${FUND}`);
  const overview = page.getByRole("heading", { level: 1, name: "Morning overview" });
  await expect(overview).toBeFocused();
  await expect(page).toHaveTitle("Morning overview · ReconPilot");

  // A link in the top bar moves to the audit log: focus goes to its title, not the top of the page.
  await page.getByRole("navigation", { name: "Screens" }).getByRole("link", { name: "Audit log" }).click();
  const audit = page.getByRole("heading", { level: 1, name: /^Audit log/ });
  await expect(audit).toBeFocused();
  await expect(page).toHaveTitle(/^Audit log.* · ReconPilot$/);

  // The shortcuts dialog takes focus, holds it, passes axe, and Esc gives focus back.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  expect(await help.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  for (let i = 0; i < 3; i++) {
    await page.keyboard.press("Tab");
    expect(await help.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await expectAccessible(page, "Keyboard shortcuts");
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
  await expect(audit).toBeFocused();
});
