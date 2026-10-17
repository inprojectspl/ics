import { describe, expect, it, vi } from "vitest";

import type { AssetSummary } from "../api";
import { buildAssetMenuActions } from "./assetMenuActions";
import { setLocale } from "./i18n";
import type { AssetRowActions } from "./useAssetActions";

const noopActions: AssetRowActions = {
  onUpdate: vi.fn(),
  onVersions: vi.fn(),
  onProject: vi.fn(),
  onBinding: vi.fn(),
  onShare: vi.fn(),
  onDelete: vi.fn(),
};

function mkAsset(over: Partial<AssetSummary> = {}): AssetSummary {
  return {
    id: "a1",
    slug: "doc-one",
    title: "Doc One",
    kind: "md_single",
    size_bytes: 100,
    version: 1,
    security_status: "clean",
    created_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    ...over,
  } as AssetSummary;
}

const keys = (a: AssetSummary, opts = {}) =>
  buildAssetMenuActions(a, noopActions, { onRename: vi.fn(), ...opts }).map((x) => x.key);

describe("buildAssetMenuActions", () => {
  it("gives the owner the full set, including share and delete", () => {
    expect(keys(mkAsset())).toEqual([
      "rename",
      "update",
      "agentView",
      "project",
      "binding",
      "share",
      "delete",
    ]);
  });

  it("withholds owner-only actions from an editor", () => {
    const k = keys(mkAsset({ my_role: "editor" }));
    expect(k).toContain("rename");
    expect(k).toContain("update");
    expect(k).not.toContain("share");
    expect(k).not.toContain("delete");
    expect(k).not.toContain("binding");
    expect(k).not.toContain("project");
  });

  it("leaves a viewer with nothing but version history", () => {
    expect(keys(mkAsset({ my_role: "viewer", version: 3 }))).toEqual(["versions", "diff"]);
    expect(keys(mkAsset({ my_role: "viewer" }))).toEqual([]);
  });

  it("offers version history only once there is more than one version", () => {
    expect(keys(mkAsset({ version: 1 }))).not.toContain("versions");
    expect(keys(mkAsset({ version: 2 }))).toContain("versions");
  });

  it("opens the agent view for editors, on the version in view", () => {
    const push = vi.spyOn(window.history, "pushState");
    expect(keys(mkAsset({ my_role: "editor" }))).toContain("agentView");
    expect(keys(mkAsset({ my_role: "viewer", version: 3 }))).not.toContain("agentView");

    const open = (opts = {}) =>
      buildAssetMenuActions(mkAsset(), noopActions, { onRename: vi.fn(), ...opts })
        .find((a) => a.key === "agentView")
        ?.onClick();
    open();
    expect(push).toHaveBeenLastCalledWith({}, "", "/v/doc-one/agent");
    open({ previewVersion: 2 });
    expect(push).toHaveBeenLastCalledWith({}, "", "/v/doc-one/agent?ver=2");
    push.mockRestore();
  });

  it("drops the content update while an archived version is previewed", () => {
    expect(keys(mkAsset(), { allowContentEdits: false })).not.toContain("update");
  });

  it("disables sharing of a critical bundle that has no admin bypass", () => {
    const share = buildAssetMenuActions(
      mkAsset({ kind: "html_bundle", security_status: "critical" }),
      noopActions,
      { onRename: vi.fn() },
    ).find((a) => a.key === "share");
    expect(share?.disabled).toBe(true);

    const bypassed = buildAssetMenuActions(
      mkAsset({ kind: "html_bundle", security_status: "critical", security_bypass: true }),
      noopActions,
      { onRename: vi.fn() },
    ).find((a) => a.key === "share");
    expect(bypassed?.disabled).toBe(false);
  });
});

describe("buildAssetMenuActions in English", () => {
  it("labels the actions in the active locale", () => {
    setLocale("en", { persist: false });
    const labels = buildAssetMenuActions(
      mkAsset({ version: 3, security_status: "critical" }),
      noopActions,
      { onRename: vi.fn() },
    ).map((x) => x.label);
    expect(labels).toEqual([
      "Rename",
      "Update content",
      "Versions (3)",
      "Compare versions",
      "Agent view",
      "Assign to project",
      "Connect a GitLab repo",
      "Share",
      "Delete",
    ]);
  });

  it("explains a blocked share in English", () => {
    setLocale("en", { persist: false });
    const share = buildAssetMenuActions(mkAsset({ security_status: "critical" }), noopActions, {
      onRename: vi.fn(),
    }).find((a) => a.key === "share");
    expect(share?.disabledHint).toBe("Needs administrator approval (security review)");
  });
});
