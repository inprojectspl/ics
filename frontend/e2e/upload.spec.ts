import { test, expect } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

test.describe("upload flow", () => {
  test("uploading a .md file adds an asset to the list", async ({ page }) => {
    await login(page);

    // The file input of the upload dialog behind the primary action.
    await page.getByRole("button", { name: "Upload" }).first().click();
    const fileInput = page.getByRole("dialog", { name: "Upload documents" }).locator('input[type="file"]').first();
    const title = `e2e-test-${Date.now()}`;
    const content = `# ${title}\n\nE2E generated file.\n`;
    await fileInput.setInputFiles({
      name: `${title}.md`,
      mimeType: "text/markdown",
      buffer: Buffer.from(content),
    });

    // The title may show up in a toast or in the list, depending on the UI,
    // so match it anywhere on the page.
    await expect(page.getByText(title)).toBeVisible({ timeout: 10_000 });
  });
});
