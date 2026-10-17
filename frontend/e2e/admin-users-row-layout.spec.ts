/**
 * On `/admin/users`, rows of `external` users carry a stack of `shrink-0`
 * pills (role, auth method, optionally blocked and unverified). The row uses
 * `flex-wrap` with the email at `basis-full` on mobile, so the pills wrap
 * below it instead of squeezing a truncated email to about 0px.
 *
 * On every viewport (mobile, tablet, desktop) the emails in the first rows
 * must stay at least 80 px wide, enough to recognise the account.
 */
import { test, expect } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

const VIEWPORTS = [
  { name: "mobile-pixel5", width: 393, height: 851 },
  { name: "mobile-narrow", width: 360, height: 800 },
  { name: "tablet", width: 768, height: 900 },
  { name: "desktop", width: 1280, height: 900 },
] as const;

for (const vp of VIEWPORTS) {
  test(`admin/users: an external user's email stays visible (${vp.name} ${vp.width}x${vp.height})`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width: vp.width, height: vp.height });

    await page.goto("/");
    await page.getByLabel(/e-?mail/i).fill(DEV_USER);
    await page.getByLabel(/password/i).fill(DEV_PASSWORD);
    await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/auth/me") && r.ok()),
      page.getByRole("button", { name: /sign in/i }).click(),
    ]);
    await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
      timeout: 15_000,
    });

    // The filter needs an external user; a fresh CI database has only the admin.
    const email = `external.partner.${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}@partner.example.org`;
    const invited = await page.request.post("/api/admin/users", { data: { email, role: "external" } });
    expect(invited.status(), await invited.text()).toBe(201);

    await page.goto("/admin/users");
    await page.waitForLoadState("networkidle");

    // The external filter yields the rows with the most badges.
    await page.getByRole("button", { name: /^Filter by role/ }).click();
    await page.getByRole("menuitemradio", { name: "External client" }).click();
    // networkidle can settle before the filtered list is fetched; wait for its rows.
    const rowName = page.locator("li button.text-item").first();
    await expect(rowName).toBeVisible({ timeout: 15_000 });

    const emailWidths = await page.evaluate(() => {
      const codes = Array.from(document.querySelectorAll("li button.text-item"));
      return codes.slice(0, 5).map((code) => ({
        email: code.textContent,
        width: code.getBoundingClientRect().width,
      }));
    });
    expect(emailWidths.length, "user list is empty after the external filter").toBeGreaterThan(0);

    for (const e of emailWidths) {
      expect(e.width, `email "${e.email}" squeezed to ${e.width}px`).toBeGreaterThan(80);
    }
  });
}
