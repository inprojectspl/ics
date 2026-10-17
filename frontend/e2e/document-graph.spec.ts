import { test, expect, type Page } from "@playwright/test";

// Document graph (ADR-0015, ADR-0016): relations added in the UI, the
// superseded banner and the document type filter on the home list.
//
// Assumes the seeded admin (`ICS_BOOTSTRAP_ADMIN_*`) and the starting doc
// type vocabulary from the migrations. Every test creates its own documents
// with unique titles, so reruns against the same database do not collide.

const DEV_USER = process.env.E2E_USER ?? "admin@example.com";
const DEV_PASSWORD = process.env.E2E_PASSWORD ?? "AdminPass123!";

type Created = { id: string; slug: string; title: string };

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel(/e-?mail/i).fill(DEV_USER);
  await page.getByLabel(/password/i).fill(DEV_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible({
    timeout: 10_000,
  });
}

/** One word per test run: full text search matches whole tokens. */
function uniqueToken(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
}

/** Uploads a Markdown document through the API with the page's session cookie. */
async function createDoc(page: Page, title: string): Promise<Created> {
  const r = await page.request.post("/api/assets?share_mode=org_sso", {
    multipart: {
      file: {
        name: `${title}.md`,
        mimeType: "text/markdown",
        buffer: Buffer.from(`# ${title}\n\n## Scope\n\nE2E test body.\n`),
      },
    },
  });
  expect(r.ok(), await r.text()).toBeTruthy();
  const body = (await r.json()) as { id: string; slug: string };
  return { id: body.id, slug: body.slug, title };
}

test.describe("document graph", () => {
  test("a derived_from relation added in the UI shows on both documents", async ({ page }) => {
    await login(page);
    const token = uniqueToken("goals");
    const goals = await createDoc(page, `Goals ${token}`);
    const spec = await createDoc(page, `Spec ${uniqueToken("spec")}`);

    // The tab is the main article; the side panel repeats a compact copy.
    const view = page.getByRole("article");
    await page.goto(`/v/${spec.slug}?tab=relations`);
    await expect(view.getByText("The document has no relations yet.")).toBeVisible({
      timeout: 10_000,
    });
    await view.getByRole("button", { name: "Add relation" }).click();

    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Document").fill(token);
    const results = dialog.getByRole("list", { name: "Documents found" });
    await results.getByRole("button", { name: goals.title }).click();
    await expect(dialog.getByLabel("Type")).toHaveValue("derived_from");
    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await expect(dialog).toBeHidden();

    // From the derived document: "Derived from" the goals.
    await expect(view.getByRole("heading", { name: /Derived from/ })).toBeVisible();
    await expect(view.getByRole("link", { name: goals.title })).toBeVisible();

    // From the goals: "Basis for" the specification.
    await page.goto(`/v/${goals.slug}?tab=relations`);
    await expect(view.getByRole("heading", { name: /Basis for/ })).toBeVisible({
      timeout: 10_000,
    });
    await expect(view.getByRole("link", { name: spec.title })).toBeVisible();
  });

  test("a supersedes relation shows a banner linking to the successor on the older document", async ({ page }) => {
    await login(page);
    const older = await createDoc(page, `Policy v1 ${uniqueToken("old")}`);
    const newer = await createDoc(page, `Policy v2 ${uniqueToken("new")}`);
    const r = await page.request.post(`/api/assets/${newer.id}/relations`, {
      data: { relation_type: "supersedes", target_id: older.id },
    });
    expect(r.status(), await r.text()).toBe(201);

    await page.goto(`/v/${older.slug}`);
    const banner = page.getByRole("alert").filter({ hasText: /This document (was|has been) replaced/ });
    await expect(banner).toBeVisible({ timeout: 10_000 });
    await expect(banner).toContainText(newer.title);

    await banner.getByRole("link", { name: "Open the current document" }).click();
    await expect(page).toHaveURL(new RegExp(`/v/${newer.slug}`));
    await expect(page.getByRole("heading", { name: newer.title, level: 1 }).first()).toBeVisible();

    // The successor itself is current: no banner there.
    await expect(page.getByRole("alert").filter({ hasText: /This document (was|has been) replaced/ })).toHaveCount(0);
  });

  test("the ?f=doctype filter narrows the document list", async ({ page }) => {
    await login(page);
    const design = await createDoc(page, `Design ${uniqueToken("design")}`);
    const runbook = await createDoc(page, `Runbook ${uniqueToken("ops")}`);
    for (const [doc, docType] of [
      [design, "design"],
      [runbook, "runbook"],
    ] as const) {
      const r = await page.request.patch(`/api/assets/${doc.id}/meta`, { data: { doc_type: docType } });
      expect(r.ok(), await r.text()).toBeTruthy();
    }

    await page.goto("/");
    await expect(page.getByRole("link", { name: design.title })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: runbook.title })).toBeVisible();

    await page.goto("/?f=doctype:design");
    await expect(page.getByRole("link", { name: design.title })).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole("link", { name: runbook.title })).toHaveCount(0);

    // The active filter shows as a removable chip under the toolbar.
    const chips = page.getByRole("group", { name: "Active filters" });
    await expect(chips.getByRole("button", { name: /^Remove filter: Design/ })).toHaveCount(1);
  });
});
