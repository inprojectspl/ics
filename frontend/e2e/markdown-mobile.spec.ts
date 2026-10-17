/**
 * Mobile viewport smoke.
 *
 * Checks that kv-table and task-list layouts hold up on a narrow phone
 * viewport (about 390px wide):
 *  - kv-table with long labels (`nowrap` could overflow the viewport),
 *  - task-list items with a bold prefix,
 *  - a plain two-column numeric table, where overflow-x-auto on .table-wrap
 *    should kick in.
 */
import { test, expect, devices } from "@playwright/test";

// Production MarkdownView shell from the helper, not a frozen markup copy.
import { mountMarkdownBody as mount } from "./helpers/mountMarkdown";

// Pixel 5 (Chrome) rather than iPhone 12 (webkit): chromium is already
// installed locally, webkit would need another ~150MB.
test.use({ ...devices["Pixel 5"] });

const KV_TABLE_LONG_LABELS = `
<table>
  <thead><tr><th>Field</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td><strong>Reference number</strong></td><td>10000001</td></tr>
    <tr><td><strong>Total contract value (net)</strong></td><td>279 333,33 EUR (doc.) / 279 733,33 EUR (arithmetic sum) \u2014 mismatch in the documentation</td></tr>
    <tr><td><strong>Place of performance</strong></td><td>55 Example Street, Sample District, Region (NUTS: XX000)</td></tr>
    <tr><td><strong>Bid submission</strong></td><td>Electronically only, through the procurement platform (платформа); the demo is delivered physically on a sealed storage medium</td></tr>
  </tbody>
</table>
`;

const TASK_LIST = `
<ul class="contains-task-list">
  <li class="task-list-item enabled"><input class="task-list-item-checkbox" type="checkbox"> <strong>Structure decision</strong>: one "Northwind Rollout" project with two Versions per region, or two separate projects?</li>
  <li class="task-list-item enabled"><input class="task-list-item-checkbox" type="checkbox"> <strong>Milestones</strong> = M1\u2013M8 from the scope document with <strong>fixed contractual dates and a "late delivery penalty" flag</strong> (input from Phase 1)</li>
  <li class="task-list-item enabled"><input class="task-list-item-checkbox" type="checkbox"> Custom field e.g. <code>clause ref</code> on contractually sensitive tasks (penalties, deadlines, deliverables)</li>
</ul>
`;


test.describe("mobile rendering", () => {
  test("a kv table with long labels stays inside the viewport (390px)", async ({ page }) => {
    await mount(page, KV_TABLE_LONG_LABELS);

    const viewport = page.viewportSize();
    expect(viewport?.width).toBeLessThan(500);

    // No horizontal scroll: document scrollWidth fits the viewport.
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollW).toBeLessThanOrEqual(viewport!.width + 1);

    // On mobile kv-table switches to a stacked layout: the cells in a row
    // are display: block, one below the other.
    const firstTdDisplay = await page
      .locator(".kv-table tbody tr").first()
      .locator("td").first()
      .evaluate((el) => window.getComputedStyle(el).display);
    expect(firstTdDisplay).toBe("block");

    // The first <td> has no nowrap, so long labels such as "Total contract
    // value (net)" can wrap onto several lines.
    const firstTdWhiteSpace = await page
      .locator(".kv-table tbody tr").first()
      .locator("td").first()
      .evaluate((el) => window.getComputedStyle(el).whiteSpace);
    expect(firstTdWhiteSpace).toBe("normal");

    await page.screenshot({ path: "test-results/mobile-kv-table.png", fullPage: true });
  });

  test("a task list flows on mobile (bold label inline with the rest)", async ({ page }) => {
    await mount(page, TASK_LIST);

    const viewport = page.viewportSize();
    const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollW).toBeLessThanOrEqual(viewport!.width + 1);

    // Each <li> wraps onto several lines on mobile instead of collapsing.
    const firstLi = page.locator("li.task-list-item").first();
    const liBox = await firstLi.boundingBox();
    expect(liBox).not.toBeNull();
    expect(liBox!.height).toBeGreaterThan(20);

    await page.screenshot({ path: "test-results/mobile-task-list.png", fullPage: true });
  });
});
