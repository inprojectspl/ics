import { test, expect, devices, type Page } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";
// One very long line without spaces: the raw view must wrap it, not scroll the page.
const LONG = "x".repeat(600);
const SOURCE = `# Agent notes\n\nSome **bold** text.\n\n${LONG}\n`;

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

async function uploadNote(page: Page): Promise<string> {
  return page.evaluate(async (source) => {
    const fd = new FormData();
    fd.append("file", new File([source], `e2e-agent-${Date.now()}.md`, { type: "text/markdown" }));
    const r = await fetch("/api/assets?share_mode=org_sso", { method: "POST", body: fd });
    return (await r.json()).slug as string;
  }, SOURCE);
}

async function expectNoHorizontalScroll(page: Page) {
  const width = page.viewportSize()?.width ?? 0;
  const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollW).toBeLessThanOrEqual(width + 1);
}

test.describe("agent view", () => {
  test("opens the agent view from the document menu", async ({ page }) => {
    await login(page);
    const slug = await uploadNote(page);

    await page.goto(`/v/${slug}`);
    await page.getByRole("button", { name: /^Document actions/ }).click();
    await page.getByRole("menuitem", { name: "Agent view" }).click();
    await expect(page).toHaveURL(new RegExp(`/v/${slug}/agent$`));
    await expect(page.getByRole("heading", { name: "Agent notes" })).toBeVisible();
    await expect(page.getByText(`ics_asset_read(slug_or_id="${slug}")`)).toBeVisible();

    await page.getByRole("radio", { name: "Raw text" }).click();
    await expect(page.getByLabel("Raw text")).toContainText("Some **bold** text.");
  });
});

test.describe("agent view on a phone", () => {
  // Everything of Pixel 5 but the browser type, which may only be set per file.
  const { defaultBrowserType: _browser, ...pixel } = devices["Pixel 5"];
  test.use(pixel);

  test("fits the screen width in both modes", async ({ page }) => {
    await login(page);
    const slug = await uploadNote(page);

    await page.goto(`/v/${slug}/agent`);
    await expect(page.getByRole("heading", { name: "Agent notes" })).toBeVisible();
    await expectNoHorizontalScroll(page);

    await page.getByRole("radio", { name: "Raw text" }).click();
    await expect(page.getByRole("radio", { name: "Raw text" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await expect(page.getByLabel("Raw text")).toContainText(LONG.slice(0, 50));
    await expectNoHorizontalScroll(page);
    await page.screenshot({ path: "test-results/agent-view-mobile.png", fullPage: true });
  });
});
