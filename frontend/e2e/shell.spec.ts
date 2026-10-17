/**
 * The app shell (DESIGN.md 2, 17): one navigation in the sidebar, the
 * reader's breadcrumb back to its project, the phone drawer, the remembered
 * collapsed rail, the command palette and the pre-paint dark theme.
 */
import { test, expect, type Page } from "@playwright/test";

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({ timeout: 15_000 });
}

/** A project with one document, through the API. */
async function seedProjectDoc(page: Page): Promise<{ project: string; projectSlug: string; title: string; slug: string }> {
  return page.evaluate(async () => {
    const stamp = Date.now().toString(36);
    const project = `E2E project ${stamp}`;
    const p = await (
      await fetch("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: project }),
      })
    ).json();
    const title = `e2e-shell-${stamp}`;
    const fd = new FormData();
    fd.append("file", new File([`# ${title}\n\n## Introduction\n\nBody.\n\n## Next\n\nMore.\n`], `${title}.md`, { type: "text/markdown" }));
    const a = await (await fetch(`/api/assets?share_mode=org_sso&project_id=${p.id}`, { method: "POST", body: fd })).json();
    return { project, projectSlug: p.slug as string, title, slug: a.slug as string };
  });
}

test.describe("shell on a desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("Documents -> document -> project in one navigation", async ({ page }) => {
    await login(page);
    const seeded = await seedProjectDoc(page);
    await page.reload();

    // One primary navigation, in the sidebar; the bar has no section links.
    const nav = page.getByRole("navigation", { name: "Main navigation" });
    await expect(nav.getByRole("link", { name: "Documents" })).toBeVisible();
    await expect(page.locator("header").getByRole("link", { name: "Projects" })).toHaveCount(0);

    await page.getByRole("link", { name: seeded.title }).first().click();
    await expect(page).toHaveURL(new RegExp(`/v/${seeded.slug}`));
    const crumbs = page.getByRole("navigation", { name: "Document path" });
    await expect(crumbs.getByRole("link", { name: seeded.project })).toBeVisible();

    // The contents of the document open in the inspector and jump to a section.
    await page.getByRole("button", { name: /Show the document panel/ }).click();
    await page.getByRole("tab", { name: "Contents" }).click();
    await page.getByRole("link", { name: "Next" }).click();
    await expect(page).toHaveURL(/#next$/);

    await crumbs.getByRole("link", { name: seeded.project }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${seeded.projectSlug}$`));
    await expect(page.getByRole("heading", { name: seeded.project, level: 1 })).toBeVisible();
    await expect(nav.getByRole("link", { name: seeded.project })).toHaveAttribute("aria-current", "page");
  });

  test("a collapsed sidebar stays collapsed after navigation and reload", async ({ page }) => {
    await login(page);
    await page.getByRole("button", { name: "Collapse menu" }).click();
    await expect(page.getByRole("button", { name: "Expand menu" })).toBeVisible();
    await page.goto("/projects");
    await expect(page.getByRole("button", { name: "Expand menu" })).toBeVisible();
    // The rail keeps every section reachable through its flyout.
    await page.getByRole("button", { name: "Projects", exact: true }).click();
    await expect(page.getByRole("menu", { name: "Projects" })).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Expand menu" }).click();
    await expect(page.getByRole("button", { name: "Collapse menu" })).toBeVisible();
  });

  test("the command palette opens with a shortcut and goes to a project", async ({ page }) => {
    await login(page);
    const seeded = await seedProjectDoc(page);
    await page.reload();
    // The shortcut belongs to the shell, which mounts once the session is known.
    await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible();
    await page.keyboard.press(process.platform === "darwin" ? "Meta+k" : "Control+k");
    const palette = page.getByRole("dialog", { name: "Search and go" });
    await expect(palette).toBeVisible();
    await page.keyboard.type(seeded.project);
    await expect(palette.getByRole("option", { name: seeded.project })).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/projects/${seeded.projectSlug}$`));
  });

  test("dark mode applies from the first frame", async ({ page }) => {
    await login(page);
    await page.evaluate(() => localStorage.setItem("ics-theme", "dark"));
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(bg).toBe("rgb(16, 20, 25)");
    await page.evaluate(() => localStorage.setItem("ics-theme", "light"));
  });
});

test.describe("shell on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

  test("navigation in the drawer and no horizontal scroll", async ({ page }) => {
    await login(page);
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(391);

    const open = page.getByRole("button", { name: "Open menu" });
    await open.click();
    const drawer = page.getByRole("dialog", { name: "Main navigation" });
    await expect(drawer).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(open).toBeFocused();

    await open.click();
    await drawer.getByRole("link", { name: "All projects" }).click();
    await expect(page).toHaveURL(/\/projects$/);
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("heading", { name: "Projects", level: 1 })).toBeVisible();
  });
});
