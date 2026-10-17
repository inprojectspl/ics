/**
 * The MarkdownView heading shows asset.title rather than the slug, and long
 * titles (especially without spaces) must not overflow the viewport on mobile.
 *
 * A slug is kebab-case, so hyphens give break opportunities; `asset.title`
 * is free-form and may be one long run without spaces. The h1 uses
 * text-display = 3.5rem (56px), so on a 390px viewport even a medium-length
 * word causes horizontal scroll.
 */
import { test, expect, devices } from "@playwright/test";

test.use({ ...devices["Pixel 5"] });

const LONG_TITLES = [
  // Realistic user input after a rename:
  "Questions for the product team about the security architecture and the 2026 roadmap",
  // One long word without spaces, break-words must kick in:
  "VeryLongFileNameWithoutSpacesThatTheUserEnteredOnRename",
  // CamelCase with numbers:
  "QuestionsForTheProductTeam2026SecurityArchitectureRoadmap",
];

async function mount(page: import("@playwright/test").Page, title: string) {
  // The MarkdownView replica is built in the browser with classes from the
  // runtime mt (same 60-character threshold as MarkdownView.tsx).
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.evaluate(async (t) => {
    const { mt } = await import("/src/styles/markdown-theme.ts");
    const titleClass = t.length > 60 ? mt.titleSmall : mt.title;
    document.body.innerHTML = `
      <div class="md-container">
        <article class="${mt.prose}">
          <div class="flex items-start gap-4">
            <h1 class="${titleClass} has-anchor flex-1 min-w-0">${t}</h1>
          </div>
          <div class="markdown-body" lang="en"><p>Body content.</p></div>
        </article>
      </div>
    `;
  }, title);
}

test.describe("MarkdownView title: mobile overflow", () => {
  for (const title of LONG_TITLES) {
    test(`a long title causes no horizontal scroll: "${title.slice(0, 40)}..."`, async ({
      page,
    }) => {
      await mount(page, title);

      const viewport = page.viewportSize();
      expect(viewport?.width).toBeLessThan(500);

      const scrollW = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollW).toBeLessThanOrEqual(viewport!.width + 1);

      // The h1 must not overflow the viewport's right edge.
      const h1Box = await page.locator("h1.has-anchor").boundingBox();
      expect(h1Box).not.toBeNull();
      expect(h1Box!.x + h1Box!.width).toBeLessThanOrEqual(viewport!.width + 1);

      await page.screenshot({
        path: `test-results/title-mobile-${title.slice(0, 20).replace(/\s/g, "_")}.png`,
        fullPage: true,
      });
    });
  }
});
