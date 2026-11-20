/**
 * A recruiter's two-minute visit to the public demo, against a real demo instance (its own
 * database, the AI answers from the pre-filled cache, the worker and the cleanup job):
 *
 * 1. "Try the demo" on the sign-in page, under the notice that the data is synthetic, makes
 *    them a fund whose week is already worked up to Friday, and opens Friday's overview;
 * 2. as the analyst they open the top case, read the AI's second opinion and the drafted
 *    custodian query, and decide every pending case;
 * 3. they switch to an approver for the escalated cases, who is then barred from signing
 *    off by the four-eyes rule, and to the other approver, who signs off the NAV;
 * 4. they generate the next business day, which is validated and run with the breaks
 *    carried from Friday;
 * 5. as the viewer they can read but not act, and the audit log's chain verifies;
 * 6. a second visitor gets a fund of their own and cannot see the first one's;
 * 7. after signing out, the first visitor carries on with their own fund from the same browser.
 *
 * Every screen is checked with axe in both themes on the way.
 */
import { type Page, expect, test } from "@playwright/test";

import { expectAccessible } from "../helpers";

const FRIDAY = "2026-11-13";
const MONDAY = "2026-11-16";
const MONDAY_LABEL = "Mon 16 Nov 2026";

interface QueueRow {
  case_id: string;
  status: string;
  escalated: boolean;
}

const strip = (page: Page) => page.getByRole("region", { name: "NAV and release status" });
/** The overview's lead card: NAV per share, NAV and the release status (the strip is not shown there). */
const overviewLead = (page: Page) => page.getByRole("region", { name: "Release status" });
const banner = (page: Page) => page.getByRole("note", { name: "Demo notice" });
const decisionOutcome = (page: Page) => page.locator(".wb-outcome-done");
const decisionButton = (page: Page, name: RegExp) => page.locator(".wb-decision").getByRole("button", { name });

async function openCase(page: Page, caseId: string): Promise<void> {
  await page.getByRole("row", { name: new RegExp(caseId) }).click();
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
}

async function workAs(page: Page, label: string): Promise<void> {
  const select = page.getByLabel("Working as");
  await select.selectOption({ label });
  await expect(select.locator("option:checked")).toHaveText(label);
  await expect(page.locator(".user-btn .user-name")).toHaveText(label.split(" · ")[0]!);
}

async function cases(page: Page, fund: string, asOf: string): Promise<QueueRow[]> {
  const response = await page.request.get(`/api/funds/${fund}/days/${asOf}/cases`);
  expect(response.ok()).toBeTruthy();
  return (await response.json()) as QueueRow[];
}

test("a recruiter's two-minute visit", async ({ page, browser }) => {
  let fund = "";

  await test.step("Try the demo opens a fund of their own at Friday", async () => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/signin/);
    await expect(banner(page)).toContainText("Every figure here is synthetic");
    await expect(page.getByRole("heading", { level: 1, name: "Try the demo" })).toBeVisible();
    await expect(page.getByLabel("Password")).toHaveCount(0);
    await expectAccessible(page, "Sign-in, demo");

    const started = Date.now();
    await page.getByRole("button", { name: "Try the demo" }).click();
    await expect(page).toHaveURL(new RegExp(`/overview\\?fund=DEMO-[A-Z0-9]{6}&day=${FRIDAY}`), { timeout: 30_000 });
    expect(Date.now() - started).toBeLessThan(30_000);
    fund = new URL(page.url()).searchParams.get("fund")!;
    await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();
    await expect(banner(page)).toBeVisible();
    await expect(page.getByLabel("Working as").locator("option:checked")).toHaveText("Priya Shah · Analyst");
    await expect(overviewLead(page).getByText("Blocked", { exact: true })).toBeVisible();
    await expect(overviewLead(page).getByTestId("ov-nps")).toHaveText(/^\d[\d,]*\.\d{6}$/);
    await expect(overviewLead(page).getByText(/^NAV [\d,]+\.\d{2} USD$/)).toBeVisible();
    await expect(strip(page)).toHaveCount(0);
    await expect(page.getByRole("heading", { name: /Every break accounted for/ })).toBeVisible();
    await expectAccessible(page, "Overview, demo");
  });

  await test.step("the analyst reads the AI's opinion and decides the pending cases", async () => {
    const queue = await cases(page, fund, FRIDAY);
    const pending = queue.filter((c) => c.status === "PENDING" && !c.escalated);
    expect(pending.length).toBeGreaterThan(0);

    await page.getByRole("link", { name: /^Cases/ }).click();
    await openCase(page, queue[0]!.case_id);
    const ai = page.getByRole("article", { name: "AI second opinion" });
    await expect(ai).toBeVisible();
    await expect(ai).not.toContainText("No AI second opinion");
    await expect(page.getByRole("heading", { name: "Draft custodian query" })).toBeVisible();
    await expectAccessible(page, "Case workbench, demo");

    for (const c of pending) {
      await openCase(page, c.case_id);
      await decisionButton(page, /^Approve/).click();
      await expect(decisionOutcome(page)).toHaveText(`Approved ${c.case_id}. Recorded in the audit log.`);
    }
  });

  await test.step("one approver decides the escalated cases; four-eyes bars them from signing off", async () => {
    await workAs(page, "Tom Reed · Approver");
    const escalated = (await cases(page, fund, FRIDAY)).filter((c) => c.escalated);
    expect(escalated.length).toBeGreaterThan(0);
    for (const c of escalated) {
      await openCase(page, c.case_id);
      await page.getByLabel(/^Note/).fill("Cause and NAV impact confirmed against the custodian statement.");
      await decisionButton(page, /^Approve/).click();
      await expect(decisionOutcome(page)).toHaveText(`Approved ${c.case_id}. Recorded in the audit log.`);
    }
    await expect(strip(page).getByText("Ready to sign off")).toBeVisible();
    await page.getByRole("link", { name: /^Sign-off/ }).click();
    await expect(page.getByText("Four-eyes rule")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign off NAV" })).toBeDisabled();
  });

  await test.step("the other approver signs off the NAV", async () => {
    await workAs(page, "Ann Lee · Approver");
    await expect(page.getByRole("button", { name: "Sign off NAV" })).toBeEnabled();
    await expectAccessible(page, "Sign-off, demo");
    await page.getByRole("button", { name: "Sign off NAV" }).click();
    const dialog = page.getByRole("dialog", { name: "Sign off the NAV?" });
    await dialog.getByRole("button", { name: "Sign off NAV" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/^Signed off\. The NAV was signed off by ann\./)).toBeVisible();
    await expect(strip(page).getByText("Signed off")).toBeVisible();
  });

  await test.step("the next business day is generated and run", async () => {
    await expect(page.getByText(`The next business day, ${MONDAY_LABEL}, can now be generated`)).toBeVisible();
    await page.getByRole("link", { name: "Go to the next day" }).click();
    await expect(page).toHaveURL(new RegExp(`/upload\\?.*day=${MONDAY}`));
    await expect(page.getByRole("heading", { level: 1, name: "Upload and run" })).toBeVisible();
    await expect(page.getByText("In the demo, days are generated rather than uploaded.")).toBeVisible();
    await expectAccessible(page, "Upload and run, demo");
    await page.getByRole("button", { name: `Generate ${MONDAY_LABEL}` }).click();
    await expect(page).toHaveURL(new RegExp(`day=${MONDAY}`));
    await expect(page.getByRole("link", { name: "Work the cases" })).toBeVisible({ timeout: 60_000 });
    const monday = await cases(page, fund, MONDAY);
    expect(monday.some((c) => !c.case_id.includes(MONDAY.replaceAll("-", "")))).toBe(true);  // carried from Friday
  });

  await test.step("the viewer reads but cannot act, and the audit chain verifies", async () => {
    await workAs(page, "Vic Moss · Viewer");
    await page.getByRole("link", { name: /^Cases/ }).click();
    await openCase(page, (await cases(page, fund, MONDAY))[0]!.case_id);
    await expect(decisionButton(page, /^Approve/)).toHaveCount(0);

    await page.getByRole("link", { name: /^Audit log/ }).click();
    await page.getByRole("button", { name: "Verify chain" }).click();
    await expect(page.getByText("Chain intact.")).toBeVisible();
    await expectAccessible(page, "Audit log, demo");
  });

  await test.step("a second visitor gets a fund of their own and cannot see the first", async () => {
    const other = await browser.newContext();
    try {
      const page2 = await other.newPage();
      await page2.goto("/signin");
      await page2.getByRole("button", { name: "Try the demo" }).click();
      await expect(page2).toHaveURL(/\/overview\?fund=DEMO-/, { timeout: 30_000 });
      const fund2 = new URL(page2.url()).searchParams.get("fund")!;
      expect(fund2).not.toBe(fund);
      await expect(page2.getByLabel("Fund").locator("option")).toHaveCount(1);
      expect((await page2.request.get(`/api/funds/${fund}`)).status()).toBe(404);
      // The second visitor's Friday is still waiting: the first visitor's sign-off is not theirs.
      const days = await (await page2.request.get(`/api/funds/${fund2}/days`)).json();
      expect(days.latest_day).toBe(FRIDAY);
    } finally {
      await other.close();
    }
  });

  await test.step("after signing out, the visitor carries on with their own fund", async () => {
    await page.locator(".user-btn").click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/signin/);
    await expect(page.getByRole("button", { name: "Start a new demo" })).toBeVisible();
    await page.getByRole("button", { name: `Carry on with ${fund}` }).click();
    await expect(page).toHaveURL(new RegExp(`/overview\\?fund=${fund}&day=${MONDAY}`));
    await expect(page.getByLabel("Working as").locator("option:checked")).toHaveText("Priya Shah · Analyst");
  });
});
