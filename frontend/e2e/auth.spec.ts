import { test, expect } from "@playwright/test";

// Login flow: valid credentials land on the document list, bad ones show an error.
//
// Assumes the seeded dev user `admin@example.com` with the password from
// compose.dev (env ICS_BOOTSTRAP_ADMIN_PASSWORD); `make dev` bootstraps it.

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

test.describe("auth flow", () => {
  test("login with the right password lands on the dashboard", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel(/e-?mail/i).fill(DEV_USER);
    await page.getByLabel(/password/i).fill(DEV_PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();

    // The dashboard heading only renders once the session is valid.
    await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
      timeout: 10_000,
    });
  });

  test("login with a wrong password shows an error", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel(/e-?mail/i).fill(DEV_USER);
    await page.getByLabel(/password/i).fill("WrongPassword!");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByText(/wrong|invalid|401/i)).toBeVisible({
      timeout: 5_000,
    });
  });
});
