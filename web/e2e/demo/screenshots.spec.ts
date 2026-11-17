/**
 * The README's screenshots, taken from the running demo (`npm run screenshots`): a fresh
 * visitor's fund at Friday, worked through the real screens, saved to docs/images/. Skipped
 * unless asked for, so `npm run test:e2e:demo` does not rewrite the images.
 *
 * Each picture is taken at a 1440 by 900 desk screen with motion reduced, so nothing is
 * caught mid-animation. Every figure in them comes from the API, as on any visit.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { type Page, expect, test } from "@playwright/test";

const FRIDAY = "2026-11-13";
const IMAGES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../docs/images");

test.skip(
  process.env.npm_lifecycle_event !== "screenshots" && !process.env.RP_SCREENSHOTS,
  "screenshots are taken only by `npm run screenshots`",
);

interface QueueRow {
  case_id: string;
  status: string;
  escalated: boolean;
  ai_flag: string;
  security_name: string | null;
}

async function cases(page: Page, fund: string): Promise<QueueRow[]> {
  return (await (await page.request.get(`/api/funds/${fund}/days/${FRIDAY}/cases`)).json()) as QueueRow[];
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 30_000 });
  // The focus ring on a screen's title is for keyboard users; a picture does not need it.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.screenshot({ path: path.join(IMAGES, `${name}.png`) });
}

async function workAs(page: Page, label: string): Promise<void> {
  await page.getByLabel("Working as").selectOption({ label });
  await expect(page.locator(".user-btn .user-name")).toHaveText(label.split(" · ")[0]!);
}

async function openCase(page: Page, caseId: string): Promise<void> {
  await page.getByRole("row", { name: new RegExp(caseId) }).click();
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
}

test("the README's screenshots", async ({ page }) => {
  fs.mkdirSync(IMAGES, { recursive: true });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });

  await page.goto("/signin");
  await page.getByRole("button", { name: "Try the demo" }).click();
  await expect(page).toHaveURL(/\/overview\?fund=DEMO-/, { timeout: 30_000 });
  const fund = new URL(page.url()).searchParams.get("fund")!;
  await expect(page.getByRole("heading", { name: /Every break accounted for/ })).toBeVisible();
  await shoot(page, "overview");

  // Dark is the default whatever the system prefers; light is the theme button's choice.
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await expect(page.locator("html")).toHaveCSS("color-scheme", "light");
  await shoot(page, "overview-light");
  await page.evaluate(() => document.documentElement.removeAttribute("data-theme"));
  await expect(page.locator("html")).toHaveCSS("color-scheme", "dark");

  await page.getByRole("link", { name: /^Upload/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^Upload and run/ })).toBeVisible();
  await shoot(page, "upload");

  // The largest case still waiting for a decision (one where the AI disagrees with the
  // rules, if there is one), with the AI's second opinion beside the rules'.
  const queue = await cases(page, fund);
  const pending = queue.filter((q) => q.status === "PENDING");
  const shown = pending.find((q) => q.ai_flag) ?? pending[0] ?? queue[0]!;
  await page.getByRole("link", { name: /^Cases/ }).click();
  await openCase(page, shown.case_id);
  await expect(page.getByRole("article", { name: "AI second opinion" })).not.toContainText("No AI second opinion");
  await shoot(page, "case-workbench");

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Command palette" });
  await expect(palette.getByRole("combobox")).toBeFocused();
  await page.keyboard.type((shown.security_name ?? "Price").split(" ")[0]!);
  await expect(palette.getByRole("option").first()).toBeVisible();
  await page.screenshot({ path: path.join(IMAGES, "command-palette.png") });
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();

  await page.getByRole("link", { name: /^MI/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: /^Management information/ })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Trend" })).toBeVisible({ timeout: 30_000 });
  await shoot(page, "mi");

  // The analyst decides the ordinary cases; one approver the escalated ones, who is then
  // barred from signing off by the four-eyes rule.
  await page.getByRole("link", { name: /^Cases/ }).click();
  for (const c of queue.filter((q) => q.status === "PENDING" && !q.escalated)) {
    await openCase(page, c.case_id);
    await page.locator(".wb-decision").getByRole("button", { name: /^Approve/ }).click();
    await expect(page.locator(".wb-outcome-done")).toContainText(`Approved ${c.case_id}.`);
  }
  await workAs(page, "Tom Reed · Approver");
  for (const c of queue.filter((q) => q.status === "PENDING" && q.escalated)) {
    await openCase(page, c.case_id);
    await page.getByLabel(/^Note/).fill("Cause and NAV impact confirmed against the custodian statement.");
    await page.locator(".wb-decision").getByRole("button", { name: /^Approve/ }).click();
    await expect(page.locator(".wb-outcome-done")).toContainText(`Approved ${c.case_id}.`);
  }
  await page.getByRole("link", { name: /^Sign-off/ }).click();
  await expect(page.getByText("Four-eyes rule")).toBeVisible();
  await shoot(page, "sign-off");

  await page.getByRole("link", { name: /^Audit log/ }).click();
  await page.getByRole("button", { name: "Verify chain" }).click();
  await expect(page.getByText("Chain intact.")).toBeVisible();
  await shoot(page, "audit-log");
});
