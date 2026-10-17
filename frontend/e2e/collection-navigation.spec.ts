/**
 * The collection reader follows the address: a file opened from the tree adds
 * a history entry, and back/forward show the file the address names (the
 * entry file when it names none), with matching content.
 */
import { test, expect, type Page } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

async function uploadCollection(page: Page, stamp: string): Promise<string> {
  return page.evaluate(async (stamp) => {
    const form = new FormData();
    const files: Record<string, string> = {
      "index.md": `# Entry ${stamp}\n`,
      "second.md": `# Second ${stamp}\n`,
    };
    for (const [path, body] of Object.entries(files)) {
      form.append("files", new File([body], path, { type: "text/markdown" }));
      form.append("paths", path);
    }
    form.append("entry_path", "index.md");
    const r = await fetch("/api/assets/collection", { method: "POST", body: form });
    if (!r.ok) throw new Error(`upload failed: ${r.status} ${await r.text()}`);
    return (await r.json()).slug as string;
  }, stamp);
}

test("back and forward in a collection keep the address and the content in step", async ({ page }) => {
  await login(page);
  const stamp = `${Date.now()}`;
  const slug = await uploadCollection(page, stamp);
  const entry = page.getByRole("heading", { name: `Entry ${stamp}` });
  const second = page.getByRole("heading", { name: `Second ${stamp}` });

  await page.goto(`/v/${slug}`);
  await expect(entry).toBeVisible();

  await page
    .getByRole("navigation", { name: "Collection file tree" })
    .getByRole("button", { name: "second", exact: true })
    .click();
  await expect(second).toBeVisible();
  await expect(page).toHaveURL(/[?&]p=second\.md/);

  await page.goBack();
  await expect(page).not.toHaveURL(/[?&]p=/);
  await expect(entry).toBeVisible();
  await expect(second).toHaveCount(0);

  await page.goForward();
  await expect(page).toHaveURL(/[?&]p=second\.md/);
  await expect(second).toBeVisible();
  await expect(entry).toHaveCount(0);
});
