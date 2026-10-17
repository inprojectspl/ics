import { describe, expect, it } from "vitest";

import type { AssetSummary } from "../api";
import { DEFAULT_ORDER, orderLabel, parseAssetSort, sortAssets } from "./assetSort";

function asset(over: Partial<AssetSummary>): AssetSummary {
  return {
    id: over.id ?? over.title ?? "x",
    slug: "s",
    title: "T",
    kind: "md_single",
    size_bytes: 0,
    version: 1,
    security_status: "clean",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    pinned_at: null,
    ...over,
  };
}

const alpha = asset({
  title: "alpha",
  version: 3,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-10T00:00:00Z",
});
const bravo = asset({
  title: "Bravo",
  kind: "html_bundle",
  version: 61,
  created_at: "2026-01-02T00:00:00Z",
  updated_at: "2026-01-03T00:00:00Z",
});
const charlie = asset({
  title: "charlie",
  kind: "md_collection",
  version: 1,
  created_at: "2026-01-03T00:00:00Z",
  updated_at: "2026-01-06T00:00:00Z",
});
const all = [bravo, charlie, alpha];
const titles = (list: AssetSummary[]) => list.map((a) => a.title);

describe("sortAssets", () => {
  it.each([
    [{ key: "updated", order: "desc" }, ["alpha", "charlie", "Bravo"]],
    [{ key: "updated", order: "asc" }, ["Bravo", "charlie", "alpha"]],
    [{ key: "created", order: "desc" }, ["charlie", "Bravo", "alpha"]],
    [{ key: "title", order: "asc" }, ["alpha", "Bravo", "charlie"]],
    [{ key: "title", order: "desc" }, ["charlie", "Bravo", "alpha"]],
    [{ key: "versions", order: "desc" }, ["Bravo", "alpha", "charlie"]],
    [{ key: "kind", order: "asc" }, ["Bravo", "charlie", "alpha"]],
  ] as const)("orders by %o", (sort, expected) => {
    expect(titles(sortAssets(all, sort))).toEqual(expected);
  });

  it("does not lift pinned assets above the chosen order", () => {
    const pinned = { ...charlie, pinned_at: "2026-02-01T00:00:00Z" };
    expect(titles(sortAssets([alpha, pinned, bravo], { key: "title", order: "asc" }))).toEqual([
      "alpha",
      "Bravo",
      "charlie",
    ]);
  });

  it("breaks ties by the most recent change and leaves the input untouched", () => {
    const older = asset({ id: "1", title: "same", updated_at: "2026-01-01T00:00:00Z" });
    const newer = asset({ id: "2", title: "same", updated_at: "2026-01-05T00:00:00Z" });
    const input = [older, newer];
    expect(sortAssets(input, { key: "title", order: "asc" })).toEqual([newer, older]);
    expect(input).toEqual([older, newer]);
  });

  it("orders by the content change, not by a metadata-only row update", () => {
    const edited = asset({
      id: "1",
      title: "edited",
      updated_at: "2026-01-02T00:00:00Z",
      content_updated_at: "2026-01-02T00:00:00Z",
    });
    const retagged = asset({
      id: "2",
      title: "retagged",
      updated_at: "2026-01-09T00:00:00Z",
      content_updated_at: "2026-01-01T00:00:00Z",
    });
    expect(titles(sortAssets([retagged, edited], { key: "updated", order: "desc" }))).toEqual([
      "edited",
      "retagged",
    ]);
  });
});

describe("parseAssetSort", () => {
  it("accepts a valid value and rejects anything else", () => {
    expect(parseAssetSort({ key: "versions", order: "asc" })).toEqual({
      key: "versions",
      order: "asc",
    });
    expect(parseAssetSort({ key: "size", order: "asc" })).toBeNull();
    expect(parseAssetSort({ key: "title", order: "up" })).toBeNull();
    expect(parseAssetSort("title")).toBeNull();
    expect(parseAssetSort(null)).toBeNull();
  });
});

describe("defaults and labels", () => {
  it("reads each key in its natural direction", () => {
    expect(DEFAULT_ORDER).toEqual({
      updated: "desc",
      created: "desc",
      title: "asc",
      versions: "desc",
      kind: "asc",
    });
    expect(orderLabel("updated", "desc")).toBe("assetSort.newestFirst");
    expect(orderLabel("title", "asc")).toBe("assetSort.aToZ");
    expect(orderLabel("versions", "asc")).toBe("assetSort.fewestFirst");
    expect(orderLabel("kind", "desc")).toBe("assetSort.kindDocsFirst");
  });
});
