/**
 * Every screen at 200% zoom. A 1440 by 900 desk screen zoomed to 200% gives the page a 720 by
 * 450 CSS-pixel window, so that is the viewport here (the browser's zoom and a viewport this
 * size lay the page out identically). On each screen, for an analyst on the first fund:
 *
 * - nothing runs off the side of the page (wide tables scroll inside their own frame);
 * - the screen's title can be seen: the sticky top bar and NAV strip leave room for the work;
 * - the screen still passes axe in both themes.
 *
 * Runs after the business-day journeys (it uses whatever days they left), but needs none.
 */
import { type Page, expect, test } from "@playwright/test";

import { FUND, expectAccessible, signIn } from "./helpers";

test.use({ viewport: { width: 720, height: 450 } });

const SCREENS: [path: string, title: RegExp][] = [
  ["/overview", /^Morning overview/],
  ["/upload", /^Upload and run/],
  ["/cases", /^Cases/],
  ["/signoff", /sign-off/i],
  ["/mi", /^Management information/],
  ["/audit", /^Audit log/],
  ["/funds", /^Funds/],
];

async function overflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/** How much of the window the sticky chrome (top bar and NAV strip) covers when scrolled down. */
async function chromeShare(page: Page): Promise<number> {
  return page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    let covered = 0;
    for (const el of document.querySelectorAll<HTMLElement>(".chrome, .strip, .topbar")) {
      const style = getComputedStyle(el);
      if (style.position !== "sticky" && style.position !== "fixed") continue;
      const box = el.getBoundingClientRect();
      if (box.bottom > 0 && box.top < window.innerHeight) covered = Math.max(covered, box.bottom);
    }
    window.scrollTo(0, 0);
    return covered / window.innerHeight;
  });
}

test("every screen works at 200% zoom", async ({ page }) => {
  await signIn(page, "analyst1");
  for (const [path, title] of SCREENS) {
    await page.goto(`${path}?fund=${FUND}`);
    const heading = page.getByRole("heading", { level: 1, name: title });
    await expect(heading).toBeVisible();
    await expect(heading).toBeInViewport();
    expect(await overflow(page), `${path} runs off the side at 200% zoom`).toBeLessThanOrEqual(1);
    expect(await chromeShare(page), `${path}: the sticky bars cover too much at 200% zoom`).toBeLessThanOrEqual(0.4);
    await expectAccessible(page, `${path} at 200% zoom`);
  }
});
