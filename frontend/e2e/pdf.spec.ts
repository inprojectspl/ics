import { readFileSync } from "node:fs";
import { test, expect } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";
const SAMPLE = readFileSync(new URL("./fixtures/sample.pdf", import.meta.url));

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

/** True once page `n` has non-blank pixels (pdf.js drew it) and a text layer. */
async function pageIsDrawn(page: import("@playwright/test").Page, n: number) {
  const pdfPage = page.locator(`.pdfViewer .page[data-page-number="${n}"]`);
  // Pages draw lazily, when they come near the viewport.
  await pdfPage.scrollIntoViewIfNeeded({ timeout: 15_000 });
  const canvas = pdfPage.locator("canvas").first();
  await expect(canvas).toBeVisible({ timeout: 15_000 });
  await expect
    .poll(
      () =>
        canvas.evaluate((el: HTMLCanvasElement) => {
          const ctx = el.getContext("2d");
          if (!ctx || el.width === 0) return false;
          const { data } = ctx.getImageData(0, 0, el.width, el.height);
          for (let i = 0; i < data.length; i += 4) {
            if ((data[i] ?? 255) < 128) return true;
          }
          return false;
        }),
      { timeout: 15_000 },
    )
    .toBe(true);
  // The text layer makes the page's text selectable and searchable.
  await expect(pdfPage.locator(".textLayer")).not.toBeEmpty({ timeout: 15_000 });
}

test.describe("PDF documents", () => {
  test("uploads a .pdf file, previews its pages and opens the public link", async ({ page, browser }) => {
    await login(page);
    const title = `e2e-pdf-${Date.now()}`;
    await page.getByRole("button", { name: "Upload" }).first().click();
    await page.getByRole("dialog", { name: "Upload documents" }).locator('input[type="file"]').first().setInputFiles({
      name: `${title}.pdf`,
      mimeType: "application/pdf",
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
    expect(asset.kind).toBe("pdf_doc");

    // Owner view.
    await page.goto(`/v/${asset.slug}`);
    await pageIsDrawn(page, 1);
    await pageIsDrawn(page, 2);
    await expect(page.getByText("of 2", { exact: true })).toBeVisible();

    // Full screen covers the app; Esc returns to the page.
    const reader = page.getByRole("region", { name: "PDF preview" });
    await page.getByRole("button", { name: "Full screen" }).click();
    await expect(reader).toHaveCSS("position", "fixed");
    await page.keyboard.press("Escape");
    await expect(reader).not.toHaveCSS("position", "fixed");

    // The same PDF behind the public link, for a visitor without a session.
    const context = await browser.newContext({ locale: "en-US" });
    const visitor = await context.newPage();
    await visitor.goto(new URL(asset.share as string).pathname);
    await pageIsDrawn(visitor, 1);
    await context.close();
  });
});
