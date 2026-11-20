/**
 * A whole business day worked in the browser, by the people who work it, against the real
 * API, worker and database:
 *
 * 1. the analyst uploads the day's generated files, sees them validated and runs the day;
 * 2. the analyst opens a case from the overview, then works the queue: approves, rejects
 *    with a note and reclassifies, leaving the escalated case to an approver;
 * 3. an approver decides the escalated case, and is then barred from signing off by the
 *    four-eyes rule;
 * 4. a second approver signs off the NAV, the day locks and the next business day opens;
 *    its files are uploaded and run, and yesterday's open cases carry into it;
 * 5. a viewer can read every screen but act on none.
 *
 * Every screen is checked with axe in the dark and light themes along the way. The tests
 * share one database and run in order.
 */
import { type Page, expect, test } from "@playwright/test";

import { DAY_ONE, DAY_TWO, FUND, dayCases, dayFiles, expectAccessible, signIn, signOut } from "./helpers";

test.describe.configure({ mode: "serial" });

const DAY_ONE_LABEL = "Mon 9 Nov 2026";
const DAY_TWO_LABEL = "Tue 10 Nov 2026";

const strip = (page: Page) => page.getByRole("region", { name: "NAV and release status" });
const decisionOutcome = (page: Page) => page.locator(".wb-outcome-done");
const decisionButton = (page: Page, name: RegExp) => page.locator(".wb-decision").getByRole("button", { name });

async function openCase(page: Page, caseId: string): Promise<void> {
  await page.getByRole("row", { name: new RegExp(caseId) }).click();
  await expect(page.getByRole("heading", { level: 2, name: caseId })).toBeVisible();
}

async function uploadAndRun(page: Page, asOf: string, label: string): Promise<void> {
  await expect(page.getByRole("heading", { level: 1, name: "Upload and run" })).toBeVisible();
  await expect(page.getByText(`No files have been uploaded for ${label} yet.`)).toBeVisible();
  await page.getByLabel(/Choose the day/).setInputFiles(dayFiles(asOf));
  await expect(page.locator(".up-validation").getByText(/^The files are valid/)).toBeVisible();
  await expect(page.getByRole("table", { name: `Files held for ${label}` }).getByRole("row")).toHaveCount(
    dayFiles(asOf).length + 1,
  );
  await page.getByRole("button", { name: "Run the day" }).click();
  await expect(page.getByRole("link", { name: "Work the cases" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/^Run by analyst1, .*open cases?\./)).toBeVisible();
}

test("an analyst uploads the day's files and runs the day", async ({ page }) => {
  await signIn(page, "analyst1");
  await expect(page).toHaveURL(/\/overview\?fund=E2E1/);
  await expect(page.getByRole("main").getByText(/No business day has been loaded for End-to-End Test Fund yet/)).toBeVisible();
  await expectAccessible(page, "Overview, nothing loaded");

  await page.getByRole("link", { name: "Upload the first day’s files" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Upload and run" })).toBeVisible();
  await expect(page.getByText(`End-to-End Test Fund, ${DAY_ONE_LABEL}`)).toBeVisible();
  await expectAccessible(page, "Upload and run, empty");

  await uploadAndRun(page, DAY_ONE, DAY_ONE_LABEL);
  await expect(page).toHaveURL(new RegExp(`day=${DAY_ONE}`));
  await expect(strip(page).getByText("Blocked")).toBeVisible();
  await expectAccessible(page, "Upload and run, after the run");
});

test("the analyst opens a case from the overview and works the queue", async ({ page }) => {
  await signIn(page, "analyst1");
  await page.goto(`/overview?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /Every break accounted for/ })).toBeVisible();
  await expectAccessible(page, "Overview");

  const cases = await dayCases(page, DAY_ONE);
  const escalated = cases.filter((c) => c.escalated);
  const ordinary = cases.filter((c) => !c.escalated);
  expect(escalated.length).toBeGreaterThan(0);
  expect(ordinary.length).toBeGreaterThanOrEqual(3);

  // A case link on the overview opens that case in the workbench.
  const first = cases[0]!;
  await page.getByRole("main").getByRole("link", { name: first.case_id }).first().click();
  await expect(page).toHaveURL(new RegExp(`/cases\\?.*case=${first.case_id}`));
  await expect(page.getByRole("heading", { level: 2, name: first.case_id })).toBeVisible();
  await expectAccessible(page, "Case workbench");

  const [toApprove, toReject, toReclassify, ...rest] = ordinary;

  await openCase(page, toApprove!.case_id);
  await decisionButton(page, /^Approve/).click();
  await expect(decisionOutcome(page)).toHaveText(`Approved ${toApprove!.case_id}. Recorded in the audit log.`);

  await openCase(page, toReject!.case_id);
  await decisionButton(page, /^Reject/).click();
  await expect(page.locator(".wb-outcome-error")).toContainText("A rejection needs a note");
  await page.getByLabel(/^Note/).fill("Custodian confirms its own booking error; no break on our side.");
  await decisionButton(page, /^Reject/).click();
  await expect(decisionOutcome(page)).toHaveText(`Rejected ${toReject!.case_id}. Recorded in the audit log.`);

  await openCase(page, toReclassify!.case_id);
  const causeSelect = page.getByLabel("Reclassify as");
  const current = toReclassify!.category === "TIMING" ? "Missing trade" : "Late settlement";
  await causeSelect.selectOption({ label: current });
  await page.getByLabel(/^Note/).fill("Trade and settlement dates show a late settlement.");
  await decisionButton(page, /^Reclassify/).click();
  await expect(decisionOutcome(page)).toHaveText(
    `Reclassified ${toReclassify!.case_id} as ${current}. Recorded in the audit log.`,
  );

  for (const c of rest) {
    await openCase(page, c.case_id);
    await page.keyboard.press("a");
    await expect(decisionOutcome(page)).toHaveText(`Approved ${c.case_id}. Recorded in the audit log.`);
  }

  // Only the escalated cases are left, and they need an approver.
  await openCase(page, escalated[0]!.case_id);
  await expect(page.getByText(/Escalated: an approver must decide this case before sign-off/)).toBeVisible();
  await expectAccessible(page, "Case workbench, escalated case");

  await page.getByRole("link", { name: /^Sign-off/ }).click();
  await expect(page.getByRole("heading", { level: 1, name: /sign-off/i })).toBeVisible();
  await expect(page.getByText("Only an approver can sign off")).toBeVisible();
  await expectAccessible(page, "Sign-off, analyst");
  await signOut(page);
});

test("an approver decides the escalated case and four-eyes keeps them from signing off", async ({ page }) => {
  await signIn(page, "approver1");
  const escalated = (await dayCases(page, DAY_ONE)).filter((c) => c.escalated);
  await page.goto(`/cases?fund=${FUND}&day=${DAY_ONE}`);
  for (const c of escalated) {
    await openCase(page, c.case_id);
    await page.getByLabel(/^Note/).fill("Dividend confirmed against the custodian's corporate-action notice.");
    await decisionButton(page, /^Approve/).click();
    await expect(decisionOutcome(page)).toHaveText(`Approved ${c.case_id}. Recorded in the audit log.`);
  }
  await expect(strip(page).getByText("Ready to sign off")).toBeVisible();

  await page.getByRole("link", { name: /^Sign-off/ }).click();
  await expect(page.getByText("Four-eyes rule")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off NAV" })).toBeDisabled();
  await expectAccessible(page, "Sign-off, four-eyes");
  await signOut(page);
});

test("a second approver signs off and the next business day opens", async ({ page }) => {
  await signIn(page, "approver2");
  await page.goto(`/signoff?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("button", { name: "Sign off NAV" })).toBeEnabled();
  await expectAccessible(page, "Sign-off, ready");

  await page.getByRole("button", { name: "Sign off NAV" }).click();
  const dialog = page.getByRole("dialog", { name: "Sign off the NAV?" });
  await expect(dialog).toBeVisible();
  await expectAccessible(page, "Sign-off, confirmation");
  await dialog.getByRole("button", { name: "Sign off NAV" }).click();
  await expect(dialog).toBeHidden();

  // The strip and the day list move on without a reload.
  await expect(page.getByText(/^Signed off\. The NAV was signed off by approver2/)).toBeVisible();
  await expect(strip(page).getByText("Signed off")).toBeVisible();
  await expect(page.getByLabel("Business day").locator("option", { hasText: `${DAY_ONE_LABEL} · Signed off` })).toHaveCount(1);
  await expect(page.getByLabel("Business day").locator("option", { hasText: `${DAY_TWO_LABEL} · No files yet` })).toHaveCount(1);
  await expect(page.getByText(`The next business day, ${DAY_TWO_LABEL}, is open for its files.`)).toBeVisible();
  await expectAccessible(page, "Sign-off, signed off");

  // A signed-off day is locked.
  const refused = await page.request.post(`/api/funds/${FUND}/days/${DAY_ONE}/run`, {
    headers: { "X-CSRF-Token": (await page.context().cookies()).find((c) => c.name === "rp_csrf")?.value ?? "" },
  });
  expect(refused.status()).toBe(409);

  await page.getByRole("button", { name: "Go to the next day" }).click();
  await expect(page).toHaveURL(new RegExp(`day=${DAY_TWO}`));
  await page.getByRole("link", { name: /^Upload/ }).click();
  await signOut(page);

  // The analyst carries on with the next day.
  await signIn(page, "analyst1");
  await page.goto(`/upload?fund=${FUND}&day=${DAY_TWO}`);
  await uploadAndRun(page, DAY_TWO, DAY_TWO_LABEL);
  const carried = (await dayCases(page, DAY_TWO)).filter((c) => !c.case_id.includes(DAY_TWO.replaceAll("-", "")));
  expect(carried.length).toBeGreaterThan(0);
  await page.getByRole("link", { name: "Open the overview" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();
  await expectAccessible(page, "Overview, second day");
});

test("a viewer reads every screen but cannot act", async ({ page }) => {
  await signIn(page, "viewer1");
  await page.goto(`/overview?fund=${FUND}&day=${DAY_ONE}`);
  await expect(page.getByRole("heading", { level: 1, name: "Morning overview" })).toBeVisible();

  await page.goto(`/cases?fund=${FUND}&day=${DAY_TWO}`);
  const first = (await dayCases(page, DAY_TWO))[0]!;
  await openCase(page, first.case_id);
  await expect(decisionButton(page, /^Approve/)).toHaveCount(0);
  await expectAccessible(page, "Case workbench, viewer");

  await page.goto(`/signoff?fund=${FUND}&day=${DAY_TWO}`);
  await expect(page.getByText("Read-only")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off NAV" })).toHaveCount(0);

  await page.goto(`/upload?fund=${FUND}&day=${DAY_TWO}`);
  await expect(page.getByText(/Viewers can follow the day but cannot upload files or run it/)).toBeVisible();
  await expect(page.getByLabel(/Choose the day/)).toHaveCount(0);
  await expectAccessible(page, "Upload and run, viewer");
});
