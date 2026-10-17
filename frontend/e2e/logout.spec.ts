import { test, expect } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

test.describe("logout flow", () => {
  test("logout: /me returns 401 after logging out", async ({ page, request }) => {
    await page.goto("/");
    await page.getByLabel(/e-?mail/i).fill(DEV_USER);
    await page.getByLabel(/password/i).fill(DEV_PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
      timeout: 10_000,
    });

    // dev_stub_sso has no logout button, so call the API directly.
    // In prod this goes through the user menu.
    await page.evaluate(() => fetch("/api/auth/logout", { method: "POST", credentials: "include" }));

    const meRes = await request.get("/api/auth/me");
    expect(meRes.status()).toBe(401);
  });
});
