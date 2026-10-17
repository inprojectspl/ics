/**
 * E2E layout test for Markdown table rendering.
 *
 * Mounts backend-generated HTML (synthetic tables shaped like real documents)
 * with the compiled CSS from the dev server, then
 * checks computed styles and bounding boxes: the kv table gets the kv layout,
 * the numbered one does not, and neither collapses onto a single line.
 *
 * Requires `npm run dev` on :5173 (the dev server serves the compiled CSS).
 */
import { test, expect } from "@playwright/test";

// Shared mount: the production MarkdownView shell (md-container + mt.prose
// imported from the dev server), so the fixture cannot drift from the app.
import { mountMarkdownBody } from "./helpers/mountMarkdown";

const KV_TABLE_HTML = `
<table>
  <thead><tr><th>Field</th><th>Value</th></tr></thead>
  <tbody>
    <tr><td><strong>Reference number</strong></td><td>10000001</td></tr>
    <tr><td><strong>Public notice</strong></td><td><a href="x">000001-2026</a></td></tr>
    <tr><td><strong>Procedure</strong></td><td>Open (открита процедура), sections 18(1) and 73(1) of the procurement act</td></tr>
    <tr><td><strong>Subject of the contract</strong></td><td>Доставки (supplies) under section 3(1)(2) of the act</td></tr>
    <tr><td><strong>Place of performance</strong></td><td>55 Example Street, Sample District, Region (NUTS: XX000)</td></tr>
  </tbody>
</table>
`;

const NUMBERED_TABLE_HTML = `
<table>
  <thead><tr><th>Iteration</th><th>Scope</th></tr></thead>
  <tbody>
    <tr><td>1</td><td>Technical analysis of 12 repositories</td></tr>
    <tr><td>2</td><td>Business context (requirements, regulator guidelines)</td></tr>
    <tr><td>3</td><td>Legal layer (statute, mapping onto code)</td></tr>
    <tr><td>4</td><td>Integration of 3 new repositories</td></tr>
    <tr><td>5</td><td>Consolidation, ADRs, final documentation</td></tr>
  </tbody>
</table>
`;

test.describe("Markdown table rendering", () => {
  test("a kv table with bold prefixes gets .kv-table and does not collapse into one line", async ({
    page,
  }) => {
    await mountMarkdownBody(page, KV_TABLE_HTML);

    const table = page.locator("table");
    await expect(table).toHaveClass(/kv-table/);

    // kv-table hides its `<thead>`.
    const theadDisplay = await page
      .locator(".kv-table thead")
      .evaluate((el) => window.getComputedStyle(el).display);
    expect(theadDisplay).toBe("none");

    // The first <td> of every row is nowrap and bold.
    const firstCells = page.locator(".kv-table tbody td:first-child");
    const count = await firstCells.count();
    expect(count).toBe(5);
    for (let i = 0; i < count; i++) {
      const whiteSpace = await firstCells
        .nth(i)
        .evaluate((el) => window.getComputedStyle(el).whiteSpace);
      expect(whiteSpace).toBe("nowrap");
    }

    // Five rows of 20-50px each give the table a real height.
    const tableBox = await table.boundingBox();
    expect(tableBox).not.toBeNull();
    expect(tableBox!.height).toBeGreaterThan(120);

    // The second column must not overflow the prose container. Compare with
    // the actual .markdown-body width rather than a magic number, so the
    // assertion survives changes to --reading-width.
    const proseW = await page
      .locator(".markdown-body")
      .evaluate((el) => el.getBoundingClientRect().width);
    const tableW = tableBox!.width;
    expect(tableW).toBeLessThanOrEqual(proseW + 1);

    await page.screenshot({ path: "test-results/kv-table.png", fullPage: true });
  });

  test("a numbered | 1 | text | table does not get .kv-table and renders its rows", async ({
    page,
  }) => {
    await mountMarkdownBody(page, NUMBERED_TABLE_HTML);

    const table = page.locator("table");
    await expect(table).not.toHaveClass(/kv-table/);

    // A regular table keeps its thead visible.
    const theadDisplay = await page
      .locator("table thead")
      .evaluate((el) => window.getComputedStyle(el).display);
    expect(theadDisplay).not.toBe("none");

    // 5 body rows plus the thead make 6 visible rows, so the height must be
    // far more than one line of text. A collapsed table would be under 50px.
    const tableBox = await table.boundingBox();
    expect(tableBox).not.toBeNull();
    expect(tableBox!.height).toBeGreaterThan(150);

    // Rows stack vertically, not inline: each first cell's Y must be
    // strictly greater than the previous one.
    const ys: number[] = await page
      .locator("table tbody td:first-child")
      .evaluateAll((els) => els.map((el) => el.getBoundingClientRect().top));
    expect(ys.length).toBe(5);
    for (let i = 1; i < ys.length; i++) {
      const prev = ys[i - 1] ?? 0;
      const curr = ys[i] ?? 0;
      expect(curr).toBeGreaterThan(prev);
    }

    // Every cell in a non-final row has a bottom border, and the last row has
    // none. Guards against `td.last:border-b-0`: Tailwind's `:last-child`
    // targets the last column, not the last row.
    const innerRowBorders: number[] = await page
      .locator("table tbody tr:not(:last-child) td")
      .evaluateAll((els) =>
        els.map((el) => parseFloat(window.getComputedStyle(el).borderBottomWidth)),
      );
    expect(innerRowBorders.length).toBeGreaterThan(0);
    for (const w of innerRowBorders) {
      expect(w).toBeGreaterThan(0);
    }

    const lastRowBorders: number[] = await page
      .locator("table tbody tr:last-child td")
      .evaluateAll((els) =>
        els.map((el) => parseFloat(window.getComputedStyle(el).borderBottomWidth)),
      );
    for (const w of lastRowBorders) {
      expect(w).toBe(0);
    }

    await page.screenshot({ path: "test-results/numbered-table.png", fullPage: true });
  });
});
