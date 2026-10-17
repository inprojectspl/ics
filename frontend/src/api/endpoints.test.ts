/**
 * Request contract of the endpoint wrappers: method, URL (query string
 * building, encoding, optional params) and JSON body. A wrong verb or a
 * dropped query param here silently breaks a whole screen, so every wrapper
 * is pinned once.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as admin from "./admin";
import * as assets from "./assets";
import * as auth from "./auth";
import * as bindings from "./bindings";
import * as projects from "./projects";
import * as relations from "./relations";
import * as shares from "./shares";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

interface Sent {
  url: string;
  method: string;
  body: unknown;
}

function lastCall(): Sent {
  const call = fetchMock.mock.calls.at(-1)!;
  const init = (call[1] ?? {}) as RequestInit;
  const raw = init.body;
  return {
    url: call[0] as string,
    method: init.method ?? "GET",
    body: typeof raw === "string" ? JSON.parse(raw) : raw,
  };
}

type Case = [name: string, call: () => Promise<unknown>, method: string, url: string, body?: unknown];

const file = new File(["# a"], "a.md", { type: "text/markdown" });

const cases: Case[] = [
  // auth
  ["me", () => auth.me(), "GET", "/api/auth/me"],
  ["setMyLocale", () => auth.setMyLocale("en"), "PATCH", "/api/auth/me"],
  ["myQuota", () => auth.myQuota(), "GET", "/api/auth/me/quota"],
  ["authConfig", () => auth.authConfig(), "GET", "/api/auth/config"],
  ["login", () => auth.login("a@x.io", "pw"), "POST", "/api/auth/login", { email: "a@x.io", password: "pw" }],
  ["logout", () => auth.logout(), "POST", "/api/auth/logout"],
  ["listTokens", () => auth.listTokens(), "GET", "/api/auth/tokens"],
  ["createToken", () => auth.createToken("ci", "2026-12-01T00:00:00Z"), "POST", "/api/auth/tokens", { name: "ci", expires_at: "2026-12-01T00:00:00Z" }],
  ["revokeToken", () => auth.revokeToken("t1"), "DELETE", "/api/auth/tokens/t1"],
  ["adminRevokeUserTokens", () => admin.adminRevokeUserTokens("u1"), "POST", "/api/admin/users/u1/tokens/revoke", {}],
  ["passwordResetRequest", () => auth.passwordResetRequest("a@x.io"), "POST", "/api/auth/password-reset/request", { email: "a@x.io" }],
  ["passwordResetConfirm", () => auth.passwordResetConfirm("t", "pw"), "POST", "/api/auth/password-reset/confirm", { token: "t", new_password: "pw" }],
  ["setupFromToken", () => auth.setupFromToken("t", "pw", "Ann"), "POST", "/api/auth/setup", { token: "t", password: "pw", display_name: "Ann" }],

  // projects
  ["listProjects no params", () => projects.listProjects(), "GET", "/api/projects"],
  ["listProjects paged", () => projects.listProjects({ page: 2, page_size: 25 }), "GET", "/api/projects?page=2&page_size=25"],
  ["createProject", () => projects.createProject("P"), "POST", "/api/projects", { name: "P", description: null }],
  ["createProject with description", () => projects.createProject("P", "d"), "POST", "/api/projects", { name: "P", description: "d" }],
  ["getProject", () => projects.getProject("p1"), "GET", "/api/projects/p1"],
  [
    "getProject sorted",
    () => projects.getProject("p1", { key: "title", order: "asc" }),
    "GET",
    "/api/projects/p1?sort=title&order=asc",
  ],
  ["getProjectGraph", () => projects.getProjectGraph("p1"), "GET", "/api/projects/p1/graph"],
  [
    "getProjectGraph with tasks",
    () => projects.getProjectGraph("p1", { tasks: true }),
    "GET",
    "/api/projects/p1/graph?include=tasks",
  ],
  [
    "getProjectHygiene",
    () => projects.getProjectHygiene("p1", "no_doc_type", 2),
    "GET",
    "/api/projects/p1/hygiene?list=no_doc_type&page=2",
  ],
  ["markDuplicate", () => projects.markDuplicate("p1", "a", "b"), "POST", "/api/projects/p1/hygiene/duplicates/mark", { source_id: "a", target_id: "b" }],
  ["dismissDuplicate", () => projects.dismissDuplicate("p1", "a", "b"), "POST", "/api/projects/p1/hygiene/duplicates/dismiss", { source_id: "a", target_id: "b" }],
  ["patchProject", () => projects.patchProject("p1", { name: "N" }), "PATCH", "/api/projects/p1", { name: "N" }],
  ["deleteProject", () => projects.deleteProject("p1"), "DELETE", "/api/projects/p1"],
  ["inviteProjectMember", () => projects.inviteProjectMember("p1", "b@x.io", "viewer"), "POST", "/api/projects/p1/members", { email: "b@x.io", role: "viewer" }],
  ["patchProjectMember", () => projects.patchProjectMember("p1", "u2", "editor"), "PATCH", "/api/projects/p1/members/u2", { role: "editor" }],
  ["kickProjectMember", () => projects.kickProjectMember("p1", "u2"), "DELETE", "/api/projects/p1/members/u2"],
  ["leaveProject", () => projects.leaveProject("p1"), "POST", "/api/projects/p1/leave", {}],
  ["transferProjectOwner", () => projects.transferProjectOwner("p1", "u2"), "POST", "/api/projects/p1/transfer-owner", { user_id: "u2" }],
  ["acceptProjectInvite", () => projects.acceptProjectInvite("t"), "POST", "/api/projects/accept-invite", { token: "t" }],

  // admin
  ["adminUsersList no params", () => admin.adminUsersList(), "GET", "/api/admin/users"],
  ["adminUsersList drops empty filters", () => admin.adminUsersList({ q: "", role: "admin", page: 3 }), "GET", "/api/admin/users?role=admin&page=3"],
  ["adminUserGet", () => admin.adminUserGet("u1"), "GET", "/api/admin/users/u1"],
  ["adminUserInvite", () => admin.adminUserInvite({ email: "c@x.io", role: "user" }), "POST", "/api/admin/users", { email: "c@x.io", role: "user" }],
  ["adminUserPatch", () => admin.adminUserPatch("u1", { html_autobypass: true }), "PATCH", "/api/admin/users/u1", { html_autobypass: true }],
  ["adminUserLock without reason", () => admin.adminUserLock("u1", 60), "POST", "/api/admin/users/u1/lock", { minutes: 60, reason: null }],
  ["adminUserLock with reason", () => admin.adminUserLock("u1", 60, "spam"), "POST", "/api/admin/users/u1/lock", { minutes: 60, reason: "spam" }],
  ["adminUserUnlock", () => admin.adminUserUnlock("u1"), "DELETE", "/api/admin/users/u1/lock"],
  ["adminUserPasswordReset", () => admin.adminUserPasswordReset("u1"), "POST", "/api/admin/users/u1/password-reset", {}],
  ["adminUserReinvite", () => admin.adminUserReinvite("u1"), "POST", "/api/admin/users/u1/reinvite", {}],
  ["adminUserDelete", () => admin.adminUserDelete("u1"), "DELETE", "/api/admin/users/u1"],
  ["adminCdnList", () => admin.adminCdnList(), "GET", "/api/admin/cdn-allowlist"],
  ["adminCdnAdd without note", () => admin.adminCdnAdd("cdn.x.io"), "POST", "/api/admin/cdn-allowlist", { host: "cdn.x.io", note: null }],
  ["adminCdnAdd with note", () => admin.adminCdnAdd("cdn.x.io", "fonts"), "POST", "/api/admin/cdn-allowlist", { host: "cdn.x.io", note: "fonts" }],
  ["adminCdnRemove", () => admin.adminCdnRemove("c1"), "DELETE", "/api/admin/cdn-allowlist/c1"],
  ["adminReviewQueue", () => admin.adminReviewQueue(), "GET", "/api/admin/review"],
  ["adminReviewDetail", () => admin.adminReviewDetail("a1"), "GET", "/api/admin/assets/a1/review"],
  ["adminGrantBypass", () => admin.adminGrantBypass("a1", "ok"), "POST", "/api/admin/assets/a1/security-bypass", { reason: "ok" }],
  ["adminRevokeBypass", () => admin.adminRevokeBypass("a1"), "DELETE", "/api/admin/assets/a1/security-bypass"],
  ["listAuditActions", () => admin.listAuditActions(), "GET", "/api/admin/audit/actions"],
  ["adminListDocTypes", () => admin.adminListDocTypes(), "GET", "/api/admin/doc-types"],
  ["adminCreateDocType", () => admin.adminCreateDocType({ key: "runbook", label_pl: "Runbook", label_en: "Runbook" }), "POST", "/api/admin/doc-types", { key: "runbook", label_pl: "Runbook", label_en: "Runbook" }],
  ["adminUpdateDocType", () => admin.adminUpdateDocType("runbook", { archived: true }), "PATCH", "/api/admin/doc-types/runbook", { archived: true }],
  ["listAudit no params", () => admin.listAudit(), "GET", "/api/admin/audit"],
  ["listAudit drops empty filters", () => admin.listAudit({ action: "", actor: "a", before_id: 7 }), "GET", "/api/admin/audit?actor=a&before_id=7"],

  // assets
  ["listAssets", () => assets.listAssets(), "GET", "/api/assets?page=1&page_size=200"],
  ["listAssets paged", () => assets.listAssets(3, 50), "GET", "/api/assets?page=3&page_size=50"],
  ["searchAssets default limit", () => assets.searchAssets("a b"), "GET", "/api/assets/search?q=a%20b&limit=50"],
  ["searchAssets custom limit", () => assets.searchAssets("q", 5), "GET", "/api/assets/search?q=q&limit=5"],
  [
    "listAssets sorted",
    () => assets.listAssets(1, 200, { key: "versions", order: "desc" }),
    "GET",
    "/api/assets?page=1&page_size=200&sort=versions&order=desc",
  ],
  [
    "searchAssets sorted",
    () => assets.searchAssets("q", 5, { key: "created", order: "asc" }),
    "GET",
    "/api/assets/search?q=q&limit=5&sort=created&order=asc",
  ],
  ["getDoc current", () => assets.getDoc("s"), "GET", "/api/assets/by-slug/s/doc"],
  ["getDoc archived", () => assets.getDoc("s", 3), "GET", "/api/assets/by-slug/s/doc?version=3"],
  ["getEntry", () => assets.getEntry("s"), "GET", "/api/assets/by-slug/s/entry"],
  ["getAssetSummary", () => assets.getAssetSummary("s"), "GET", "/api/assets/by-slug/s/summary"],
  ["getSource entry", () => assets.getSource("s"), "GET", "/api/assets/by-slug/s/source"],
  ["getSource path", () => assets.getSource("s", "a b.md"), "GET", "/api/assets/by-slug/s/source?path=a%20b.md"],
  ["getGraph", () => assets.getGraph("s"), "GET", "/api/assets/by-slug/s/graph"],
  ["getCollectionFile archived", () => assets.getCollectionFile("s", "n/x.md", 2), "GET", "/api/assets/by-slug/s/file?path=n%2Fx.md&version=2"],
  ["getAssetHtmlGrant", () => assets.getAssetHtmlGrant("s"), "GET", "/api/assets/by-slug/s/html-grant"],
  ["pinAsset", () => assets.pinAsset("a1"), "POST", "/api/assets/a1/pin"],
  ["unpinAsset", () => assets.unpinAsset("a1"), "DELETE", "/api/assets/a1/pin"],
  ["renameAsset", () => assets.renameAsset("a1", "T"), "PATCH", "/api/assets/a1", { title: "T" }],
  ["deleteAsset", () => assets.deleteAsset("a1"), "DELETE", "/api/assets/a1"],
  ["patchMeta", () => assets.patchMeta("a1", { doc_type: "design", summary: null }), "PATCH", "/api/assets/a1/meta", { doc_type: "design", summary: null }],
  ["markReviewed", () => assets.markReviewed("a1"), "POST", "/api/assets/a1/reviewed", {}],
  ["listDocTypes", () => assets.listDocTypes(), "GET", "/api/doc-types?include_archived=true"],
  ["linkTitles", () => assets.linkTitles(["abc", "d e"]), "GET", "/api/assets/link-titles?slug=abc&slug=d%20e"],
  ["getAssetMeta", () => assets.getAssetMeta("s"), "GET", "/api/assets/by-slug/s/meta"],
  ["setTags", () => assets.setTags("a1", ["x"]), "PUT", "/api/assets/a1/tags", { tags: ["x"] }],
  ["editContent entry", () => assets.editContent("a1", "x"), "PUT", "/api/assets/a1/content", { content: "x", path: null }],
  ["editContent path", () => assets.editContent("a1", "x", "n.md"), "PUT", "/api/assets/a1/content", { content: "x", path: "n.md" }],
  ["editContent change note", () => assets.editContent("a1", "x", undefined, "Fix typo"), "PUT", "/api/assets/a1/content", { content: "x", path: null, change_note: "Fix typo" }],
  ["deleteVaultFile", () => assets.deleteVaultFile("a1", "n/x.md"), "DELETE", "/api/assets/a1/files?path=n%2Fx.md"],
  ["createEmptyVaultFile", () => assets.createEmptyVaultFile("a1", "n.md"), "POST", "/api/assets/a1/files/empty", { path: "n.md" }],
  ["moveVaultFile", () => assets.moveVaultFile("a1", "a.md", "b.md"), "PATCH", "/api/assets/a1/files/move", { from_path: "a.md", to_path: "b.md" }],
  ["listVersions", () => assets.listVersions("a1"), "GET", "/api/assets/a1/versions"],
  ["restoreVersion", () => assets.restoreVersion("a1", 2), "POST", "/api/assets/a1/versions/2/restore"],
  ["diffVersions", () => assets.diffVersions("a1", 1, 2), "GET", "/api/assets/a1/versions/1/diff/2"],
  ["diffVersionFile", () => assets.diffVersionFile("a1", 1, 2, "a b.md"), "GET", "/api/assets/a1/versions/1/diff/2?path=a%20b.md"],

  // bindings
  ["listBindings", () => bindings.listBindings("a1"), "GET", "/api/bindings?asset_id=a1"],
  ["listNotificationProviders", () => bindings.listNotificationProviders(), "GET", "/api/bindings/providers"],
  ["createBinding bare", () => bindings.createBinding("a1"), "POST", "/api/bindings", { asset_id: "a1", gitlab_project_url: null, webhook_url: null, provider: null }],
  [
    "createBinding with webhook",
    () => bindings.createBinding("a1", { gitlabUrl: "https://g/x", webhook: { url: "https://h", provider: "google_chat" } }),
    "POST",
    "/api/bindings",
    { asset_id: "a1", gitlab_project_url: "https://g/x", webhook_url: "https://h", provider: "google_chat" },
  ],
  ["patchBinding leaves untouched fields out", () => bindings.patchBinding("b1", {}), "PATCH", "/api/bindings/b1", {}],
  ["patchBinding clears webhook pair", () => bindings.patchBinding("b1", { webhook: null }), "PATCH", "/api/bindings/b1", { webhook_url: null, provider: null }],
  [
    "patchBinding sets both fields",
    () => bindings.patchBinding("b1", { gitlab_project_url: null, webhook: { url: "https://h", provider: "google_chat" } }),
    "PATCH",
    "/api/bindings/b1",
    { gitlab_project_url: null, webhook_url: "https://h", provider: "google_chat" },
  ],
  ["rotateBinding", () => bindings.rotateBinding("b1"), "POST", "/api/bindings/b1/rotate"],
  ["deleteBinding", () => bindings.deleteBinding("b1"), "DELETE", "/api/bindings/b1"],

  // relations
  ["listRelations", () => relations.listRelations("s"), "GET", "/api/assets/by-slug/s/relations"],
  [
    "listRelations filtered",
    () => relations.listRelations("s", { types: ["derived_from", "supersedes"], direction: "in" }),
    "GET",
    "/api/assets/by-slug/s/relations?types=derived_from&types=supersedes&direction=in",
  ],
  ["getNeighbourhood", () => relations.getNeighbourhood("s"), "GET", "/api/assets/by-slug/s/neighbourhood"],
  [
    "getNeighbourhood with depth",
    () => relations.getNeighbourhood("s", { depth: 2 }),
    "GET",
    "/api/assets/by-slug/s/neighbourhood?depth=2",
  ],
  [
    "getNeighbourhood with types",
    () => relations.getNeighbourhood("s", { types: ["references", "derived_from"] }),
    "GET",
    "/api/assets/by-slug/s/neighbourhood?types=references&types=derived_from",
  ],
  [
    "findGraphPath",
    () => relations.findGraphPath("s", { from: ["a1"], projects: ["p1"], types: ["references"] }),
    "POST",
    "/api/assets/by-slug/s/path",
    { from: ["a1"], projects: ["p1"], types: ["references"] },
  ],
  ["addRelation", () => relations.addRelation("a1", { relation_type: "references", target_slug: "b" }), "POST", "/api/assets/a1/relations", { relation_type: "references", target_slug: "b" }],
  ["patchRelation", () => relations.patchRelation("r1", { refresh_target_version: true }), "PATCH", "/api/relations/r1", { refresh_target_version: true }],
  ["deleteRelation", () => relations.deleteRelation("r1"), "DELETE", "/api/relations/r1"],
  ["getOutline", () => relations.getOutline("s"), "GET", "/api/assets/by-slug/s/outline"],
  ["getContextPack", () => relations.getContextPack({ wp: "4711" }), "GET", "/api/context?wp=4711"],
  [
    "getContextPack with options",
    () =>
      relations.getContextPack({
        wp: "n-1",
        system: "project_standard",
        ancestors: ["4700", "4650"],
        project: "apollo",
        depth: 2,
        budgetTokens: 4000,
        include: ["references", "deliverables"],
      }),
    "GET",
    "/api/context?wp=n-1&system=project_standard&ancestors=4700%2C4650&project=apollo&depth=2&budget_tokens=4000&include=references&include=deliverables",
  ],
  ["listExternalRefs", () => relations.listExternalRefs("a1"), "GET", "/api/assets/a1/external-refs"],
  ["addExternalRef", () => relations.addExternalRef("a1", { system: "openproject", entity: "work_package", external_id: "42" }), "POST", "/api/assets/a1/external-refs", { system: "openproject", entity: "work_package", external_id: "42" }],
  ["deleteExternalRef", () => relations.deleteExternalRef("x1"), "DELETE", "/api/external-refs/x1"],

  // project links
  ["getProjectExternalRefs", () => projects.getProjectExternalRefs("p"), "GET", "/api/projects/p/external-refs"],
  ["putProjectExternalRefs", () => projects.putProjectExternalRefs("p", [{ system: "openproject", external_id: "acme" }]), "PUT", "/api/projects/p/external-refs", { refs: [{ system: "openproject", external_id: "acme" }] }],
  ["getKeyDocuments", () => projects.getKeyDocuments("p"), "GET", "/api/projects/p/key-documents"],
  ["putKeyDocuments", () => projects.putKeyDocuments("p", [{ asset_id: "a1", reason: null }]), "PUT", "/api/projects/p/key-documents", { documents: [{ asset_id: "a1", reason: null }] }],

  // shares
  ["listProjectShares", () => shares.listProjectShares("a1"), "GET", "/api/assets/a1/project-shares"],
  ["putProjectShare", () => shares.putProjectShare("a1", "p2", "editor"), "PUT", "/api/assets/a1/project-shares", { project_id: "p2", role: "editor" }],
  ["deleteProjectShare", () => shares.deleteProjectShare("a1", "p2"), "DELETE", "/api/assets/a1/project-shares/p2"],
  ["listShares", () => shares.listShares("a1"), "GET", "/api/assets/a1/shares"],
  ["createShare", () => shares.createShare("a1", { mode: "public" }), "POST", "/api/assets/a1/shares", { mode: "public" }],
  ["revokeShare", () => shares.revokeShare("sh1"), "DELETE", "/api/shares/sh1"],
  ["getShareInfo", () => shares.getShareInfo("t"), "GET", "/api/share/t/info"],
  ["shareAuth", () => shares.shareAuth("t", "pw"), "POST", "/api/share/t/auth", { password: "pw" }],
  ["shareMagicClaim", () => shares.shareMagicClaim("t", "m1"), "POST", "/api/share/t/magic-claim", { m: "m1" }],
  ["getShareDoc archived", () => shares.getShareDoc("t", 4), "GET", "/api/share/t/doc?version=4"],
  ["getShareGraph", () => shares.getShareGraph("t"), "GET", "/api/share/t/graph"],
  ["getShareVersions", () => shares.getShareVersions("t"), "GET", "/api/share/t/versions"],
  ["getShareCollectionFile", () => shares.getShareCollectionFile("t", "n/x.md"), "GET", "/api/share/t/file?path=n%2Fx.md"],
  ["getShareHtmlGrant", () => shares.getShareHtmlGrant("t", 2), "GET", "/api/share/t/html-grant?version=2"],
  ["listAssetShares", () => shares.listAssetShares("s"), "GET", "/api/assets/by-slug/s/shares"],
  ["createAssetShare", () => shares.createAssetShare("s", "d@x.io", "editor"), "POST", "/api/assets/by-slug/s/shares", { email: "d@x.io", role: "editor" }],
  ["deleteAssetShare", () => shares.deleteAssetShare("s", "u2"), "DELETE", "/api/assets/by-slug/s/shares/u2"],
  ["patchAssetProject", () => shares.patchAssetProject("s", null), "PATCH", "/api/assets/by-slug/s/project", { project_id: null }],
];

describe("endpoint wrappers", () => {
  it.each(cases)("%s", async (_name, call, method, url, body) => {
    await call();
    const sent = lastCall();
    expect(sent.method).toBe(method);
    expect(sent.url).toBe(url);
    if (body !== undefined) expect(sent.body).toEqual(body);
  });

  it("forwards the abort signal of listAudit", async () => {
    const ctrl = new AbortController();
    await admin.listAudit({}, ctrl.signal);
    expect((fetchMock.mock.calls[0]![1] as RequestInit).signal).toBe(ctrl.signal);
  });
});

describe("multipart uploads", () => {
  function sentForm(): FormData {
    return lastCall().body as FormData;
  }

  it("uploadMarkdown defaults to org_sso and carries the file", async () => {
    await assets.uploadMarkdown(file);
    expect(lastCall().url).toBe("/api/assets?share_mode=org_sso");
    expect(sentForm().get("file")).toBeInstanceOf(File);
  });

  it("uploadMarkdown assigns the project when given", async () => {
    await assets.uploadMarkdown(file, "public", "p 1");
    expect(lastCall().url).toBe("/api/assets?share_mode=public&project_id=p%201");
  });

  it("uploadPdf posts the file to the pdf endpoint", async () => {
    await assets.uploadPdf(file, "public", "p1");
    expect(lastCall()).toMatchObject({
      method: "POST",
      url: "/api/assets/pdf?share_mode=public&project_id=p1",
    });
    expect(sentForm().get("file")).toBeInstanceOf(File);
  });

  it("uploadDocument posts the file to the document endpoint", async () => {
    await assets.uploadDocument(file, "org_sso");
    expect(lastCall()).toMatchObject({
      method: "POST",
      url: "/api/assets/document?share_mode=org_sso",
    });
    expect(sentForm().get("file")).toBeInstanceOf(File);
  });

  it("uploadCollection pairs every file with its path", async () => {
    await assets.uploadCollection([
      { file, path: "a.md" },
      { file, path: "n/b.md" },
    ]);
    expect(lastCall().url).toBe("/api/assets/collection?share_mode=org_sso");
    expect(sentForm().getAll("paths")).toEqual(["a.md", "n/b.md"]);
    expect(sentForm().getAll("files")).toHaveLength(2);
  });

  it("uploadHtmlBundle posts to the html endpoint", async () => {
    await assets.uploadHtmlBundle([{ file, path: "index.html" }], "org_sso", "p1");
    expect(lastCall().url).toBe("/api/assets/html?share_mode=org_sso&project_id=p1");
    expect(sentForm().getAll("paths")).toEqual(["index.html"]);
  });

  it("uploadVersion posts files and paths to the versions endpoint", async () => {
    await assets.uploadVersion("a1", [{ file, path: "a.md" }]);
    expect(lastCall()).toMatchObject({ method: "POST", url: "/api/assets/a1/versions" });
    expect(sentForm().getAll("paths")).toEqual(["a.md"]);
  });

  it("uploadVersion sends the change note only when given", async () => {
    await assets.uploadVersion("a1", [{ file, path: "a.md" }]);
    expect(sentForm().has("change_note")).toBe(false);
    await assets.uploadVersion("a1", [{ file, path: "a.md" }], "New chapter");
    expect(sentForm().get("change_note")).toBe("New chapter");
  });

  it("addVaultFile sends the target path only when given", async () => {
    await assets.addVaultFile("a1", file);
    expect(sentForm().has("path")).toBe(false);
    await assets.addVaultFile("a1", file, "n/a.md");
    expect(lastCall().url).toBe("/api/assets/a1/files");
    expect(sentForm().get("path")).toBe("n/a.md");
  });
});

describe("static URLs", () => {
  it("encode each path segment but keep separators", () => {
    expect(assets.staticUrl("s", "img/a b.png")).toBe("/api/assets/by-slug/s/static/img/a%20b.png");
    expect(shares.shareStaticUrl("t", "img/a b.png")).toBe("/api/share/t/static/img/a%20b.png");
  });

  it("point the PDF viewer at the current or an archived version", () => {
    expect(assets.pdfUrl("s")).toBe("/api/assets/by-slug/s/pdf");
    expect(assets.pdfUrl("s", 3)).toBe("/api/assets/by-slug/s/pdf?version=3");
    expect(shares.sharePdfUrl("t", 2)).toBe("/api/share/t/pdf?version=2");
  });
});
