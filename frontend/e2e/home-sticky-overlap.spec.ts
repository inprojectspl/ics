/**
 * The app shell keeps its chrome in place while the page scrolls: the
 * global bar stays at the top above the content (the content never paints
 * over it), the sidebar stays full height beside it, and nothing makes the
 * page scroll sideways. Guards against the sidebar poking through the
 * sticky navbar.
 */
import { test, expect } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

// A short viewport (1440x680) mimics a zoomed-in laptop screen.
test.use({ viewport: { width: 1440, height: 680 } });

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/auth/me") && r.ok()),
    page.getByRole("button", { name: /sign in/i }).click(),
  ]);
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({ timeout: 30_000 });
}

async function ensureEnoughAssets(page: import("@playwright/test").Page, minCount: number) {
  const current = await page.evaluate(async () => {
    const r = await fetch("/api/assets?page_size=100", { credentials: "include" });
    return r.ok ? ((await r.json()).items?.length ?? 0) : 0;
  });
  for (let i = current; i < minCount; i++) {
    const ok = await page.evaluate(async (idx) => {
      const fd = new FormData();
      fd.append("file", new Blob([`# Dummy ${idx}\n\nLorem ipsum.\n`], { type: "text/markdown" }), `e2e-scroll-${Date.now()}-${idx}.md`);
      return (await fetch("/api/assets", { method: "POST", credentials: "include", body: fd })).ok;
    }, i);
    expect(ok, `seed asset #${i}`).toBe(true);
  }
}

test("shell: the global bar and the sidebar stay in place while scrolling", async ({ page }) => {
  test.setTimeout(90_000);
  await login(page);
  await ensureEnoughAssets(page, 30);
  await page.reload();
  await page.waitForLoadState("networkidle");

  const scrollable = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  expect(scrollable, "the list must have something to scroll").toBeGreaterThan(200);
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await page.waitForTimeout(200);

  const topbar = await page.locator("main").locator("xpath=preceding::header[1]").boundingBox();
  const sidebar = await page.locator("aside").first().boundingBox();
  expect(topbar).not.toBeNull();
  expect(sidebar).not.toBeNull();
  expect(topbar!.y).toBeCloseTo(0, 0);
  expect(sidebar!.y).toBeCloseTo(0, 0);
  expect(sidebar!.height).toBeGreaterThanOrEqual(679);

  // Inside the bar the top-most element is the bar itself, never a list row.
  const hits = await page.evaluate(({ x0, x1, y }) => {
    const out: boolean[] = [];
    for (let x = x0; x < x1; x += 120) {
      const el = document.elementFromPoint(x, y);
      out.push(Boolean(el?.closest("header")));
    }
    return out;
  }, { x0: Math.ceil(topbar!.x) + 4, x1: Math.floor(topbar!.x + topbar!.width) - 4, y: Math.floor(topbar!.height / 2) });
  expect(hits.every(Boolean), "content paints over the global bar").toBe(true);

  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollW).toBeLessThanOrEqual(1441);
  await page.screenshot({ path: "test-results/shell-scrolled.png" });
});
