import { readFileSync } from "node:fs";
import { test, expect, type Page } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";
// A Heading1 paragraph "Field guide" and a body paragraph about wombats.
const SAMPLE = readFileSync(new URL("./fixtures/sample.docx", import.meta.url));
const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

/** The converted text is rendered as HTML, not an image of the pages. */
async function showsConvertedText(page: Page) {
  await expect(page.getByRole("heading", { name: /field guide/i })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/wombats/)).toBeVisible();
}

test.describe("Office documents", () => {
  test("uploads a .docx file, previews its text and opens the public link", async ({ page, browser }) => {
    await login(page);
    const title = `e2e-docx-${Date.now()}`;
    // Uploads start from the one primary action of the list.
    await page.getByRole("button", { name: "Upload" }).first().click();
    await page.getByRole("dialog", { name: "Upload documents" }).locator('input[type="file"]').first().setInputFiles({
      name: `${title}.docx`,
      mimeType: DOCX_MIME,
      buffer: SAMPLE,
    });
    await expect(page.getByText(title).first()).toBeVisible({ timeout: 10_000 });

    const asset = await page.evaluate(async (t) => {
      const list = await fetch("/api/assets").then((r) => r.json());
      const item = list.items.find((i: { title: string }) => i.title === t);
      const r = await fetch(`/api/assets/${item.id}/shares`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "public" }),
      });
      return { slug: item.slug as string, kind: item.kind as string, share: (await r.json()).url };
    }, title);
    expect(asset.kind).toBe("office_doc");

    // Owner view.
    await page.goto(`/v/${asset.slug}`);
    await showsConvertedText(page);
    await expect(page.getByText(/from a \.docx file/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Download original" })).toBeVisible();

    // The same document behind the public link, for a visitor without a session.
    const context = await browser.newContext({ locale: "en-US" });
    const visitor = await context.newPage();
    await visitor.goto(new URL(asset.share as string).pathname);
    await showsConvertedText(visitor);
    await context.close();
  });
});
