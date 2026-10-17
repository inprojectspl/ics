import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, within } from "@testing-library/react";

import type { AssetSummary, Me, ProjectDetail as Project } from "../api";
import { t } from "../lib/i18n";
import { ProjectDetail } from "./ProjectDetail";
import { renderWithClient } from "../test-utils";

const getProject = vi.fn();

vi.mock("../api", () => ({
  api: {
    getProject: (...a: unknown[]) => getProject(...a),
    deleteAsset: vi.fn(),
    renameAsset: vi.fn(),
    pinAsset: vi.fn(),
    unpinAsset: vi.fn(),
    listProjects: vi.fn().mockResolvedValue({ items: [], total: 0, page: 1, page_size: 200 }),
    listDocTypes: vi.fn().mockResolvedValue([]),
    getKeyDocuments: vi.fn().mockResolvedValue([]),
    getProjectExternalRefs: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock("../components/WatchToggle", () => ({ ProjectWatchToggle: () => null }));
vi.mock("../components/Toast", () => ({ useToast: () => ({ toast: vi.fn() }), useErrorToast: () => vi.fn() }));
vi.mock("../components/ConfirmDialog", () => ({ useConfirm: () => vi.fn() }));
vi.mock("../lib/useAssetUpload", () => ({
  useAssetUpload: () => ({ uploading: false, onDrop: vi.fn(), onPicked: vi.fn() }),
}));

const me = { id: "u1", email: "me@example.com", display_name: "Me", role: "user" } as Me;

function asset(title: string, over: Partial<AssetSummary>): AssetSummary {
  return {
    id: title,
    slug: title.toLowerCase(),
    title,
    kind: "md_single",
    size_bytes: 10,
    version: 1,
    security_status: "clean",
    active_share_modes: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    ...over,
  };
}

const assets = [
  asset("Zeta", { version: 61, updated_at: "2026-01-02T00:00:00Z" }),
  asset("Alpha", { version: 2, updated_at: "2026-01-09T00:00:00Z" }),
  asset("Mid", { version: 7, updated_at: "2026-01-05T00:00:00Z" }),
];

function proj(list: AssetSummary[] = assets): Project {
  return {
    id: "p1",
    slug: "alpha",
    name: "Alpha project",
    description: null,
    created_by: "u1",
    created_at: "2026-01-01T00:00:00Z",
    my_role: "owner",
    member_count: 1,
    asset_count: list.length,
    members: [],
    assets: list,
  } as Project;
}

function rowTitles(): string[] {
  return screen
    .getAllByRole("listitem")
    .map((li) => within(li).queryByRole("link")?.textContent ?? "")
    .filter((t) => ["Alpha", "Mid", "Zeta"].includes(t));
}

beforeEach(() => {
  window.localStorage.clear();
  getProject.mockReset().mockResolvedValue(proj());
});

describe("ProjectDetail sorting", () => {
  it("lists the most recently changed files first by default", async () => {
    renderWithClient(<ProjectDetail me={me} slug="alpha" />);
    await screen.findByRole("link", { name: "Alpha" });
    expect(rowTitles()).toEqual(["Alpha", "Mid", "Zeta"]);
    expect(getProject).toHaveBeenCalledWith("alpha", { key: "updated", order: "desc" });
  });

  it("re-sorts on a new key, asks the server for it and remembers it", async () => {
    renderWithClient(<ProjectDetail me={me} slug="alpha" />);
    await screen.findByRole("link", { name: "Alpha" });

    fireEvent.click(screen.getByRole("button", { name: /Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Number of versions" }));

    expect(rowTitles()).toEqual(["Zeta", "Mid", "Alpha"]);
    expect(getProject).toHaveBeenLastCalledWith("alpha", { key: "versions", order: "desc" });
    expect(JSON.parse(window.localStorage.getItem("ics.assetSort.project.u1") ?? "null")).toEqual({
      key: "versions",
      order: "desc",
    });

    fireEvent.click(screen.getByRole("button", { name: /Sort by:/ }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: t("assetSort.fewestFirst") }));
    expect(rowTitles()).toEqual(["Alpha", "Mid", "Zeta"]);
  });

  it("starts from the remembered choice", async () => {
    window.localStorage.setItem(
      "ics.assetSort.project.u1",
      JSON.stringify({ key: "title", order: "desc" }),
    );
    renderWithClient(<ProjectDetail me={me} slug="alpha" />);
    await screen.findByRole("link", { name: "Alpha" });
    expect(rowTitles()).toEqual(["Zeta", "Mid", "Alpha"]);
    expect(screen.getByRole("button", { name: /^Sort by: Title/ })).toBeInTheDocument();
  });

  it("keeps a favourite in the chosen order", async () => {
    getProject.mockResolvedValue(
      proj([...assets.slice(0, 2), { ...assets[2]!, pinned_at: "2026-01-01T00:00:00Z" }]),
    );
    renderWithClient(<ProjectDetail me={me} slug="alpha" />);
    await screen.findByRole("link", { name: "Alpha" });
    expect(rowTitles()).toEqual(["Alpha", "Mid", "Zeta"]);
    expect(screen.queryByRole("region", { name: "Favourites" })).not.toBeInTheDocument();
  });
});
