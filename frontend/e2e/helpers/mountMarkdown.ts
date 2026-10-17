/**
 * Shared mount fixture for the markdown specs.
 *
 * The shell is built in the browser from classes imported from the dev
 * server (`mt.prose` from markdown-theme.ts), so it always matches what
 * production renders. A frozen copy of the markup goes stale after theme
 * changes, and without `.md-container` the breakout (100cqw) is measured
 * against the viewport. Structure mirrors MarkdownView.tsx:
 * <div.md-container><article.mt.prose>{children}</article></div>.
 */
import type { Page } from "@playwright/test";

/**
 * Mounts children inside the production MarkdownView shell.
 * `innerHtml` is the <article> content, usually `<div class="markdown-body"
 * lang="en">...</div>`, though the title spec adds its own title row.
 * When a .markdown-body is present, it is hydrated the way MarkdownView does.
 */
async function mountInProseShell(page: Page, innerHtml: string): Promise<void> {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await page.evaluate(async (inner) => {
    const { mt } = await import("/src/styles/markdown-theme.ts");
    document.body.innerHTML = `
      <div class="md-container">
        <article class="${mt.prose}">${inner}</article>
      </div>
    `;
    const root = document.querySelector(".markdown-body") as HTMLElement | null;
    if (root) {
      const mod = await import("/src/lib/hydrateMarkdown.ts");
      mod.hydrateMarkdown(root, null);
    }
  }, innerHtml);
}

/** Shortcut for the common case: a bare markdown-body with content. */
export async function mountMarkdownBody(page: Page, bodyHtml: string): Promise<void> {
  await mountInProseShell(page, `<div class="markdown-body" lang="en">${bodyHtml}</div>`);
}
