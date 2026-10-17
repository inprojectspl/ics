import type { AssetSort, AssetSortKey, AssetSummary, SortOrder } from "../api";
import { nameCollator, type MessageKey } from "./i18n";

/**
 * Sort model for asset lists, mirroring `app/services/asset_sort.py` (the
 * key alone orders rows; pins do not). The client re-sorts what it holds so a
 * new choice applies before the refetch.
 */

// Re-exported so list code takes the whole sort model from one module.
export type { AssetSort, AssetSortKey, SortOrder };

export const ASSET_SORT_KEYS: readonly AssetSortKey[] = [
  "updated",
  "created",
  "title",
  "versions",
  "kind",
];

// Natural reading of each key: newest first, A-Z, most versions first.
export const DEFAULT_ORDER: Record<AssetSortKey, SortOrder> = {
  updated: "desc",
  created: "desc",
  title: "asc",
  versions: "desc",
  kind: "asc",
};

export const DEFAULT_ASSET_SORT: AssetSort = { key: "updated", order: "desc" };

export const SORT_LABEL: Record<AssetSortKey, MessageKey> = {
  updated: "assetSort.updated",
  created: "assetSort.created",
  title: "assetSort.title",
  versions: "assetSort.versions",
  kind: "assetSort.kind",
};

/** Label of each direction, phrased for the key ("newest first", "A-Z"). */
export function orderLabel(key: AssetSortKey, order: SortOrder): MessageKey {
  switch (key) {
    case "updated":
    case "created":
      return order === "desc" ? "assetSort.newestFirst" : "assetSort.oldestFirst";
    case "title":
      return order === "asc" ? "assetSort.aToZ" : "assetSort.zToA";
    case "kind":
      // Raw kind names order html_bundle < md_collection < md_single < pdf_doc.
      return order === "asc" ? "assetSort.kindHtmlFirst" : "assetSort.kindDocsFirst";
    case "versions":
      return order === "desc" ? "assetSort.mostFirst" : "assetSort.fewestFirst";
  }
}

function isAssetSortKey(v: unknown): v is AssetSortKey {
  return typeof v === "string" && (ASSET_SORT_KEYS as readonly string[]).includes(v);
}

/** Validates a stored value; anything malformed yields `null`. */
export function parseAssetSort(raw: unknown): AssetSort | null {
  if (typeof raw !== "object" || raw === null) return null;
  const { key, order } = raw as Record<string, unknown>;
  if (!isAssetSortKey(key) || (order !== "asc" && order !== "desc")) return null;
  return { key, order };
}

// The server serialises every timestamp with the same `isoformat()` shape,
// so string order is time order and the comparator parses nothing.
function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** When the content last changed. Tag, rename and scan writes move only
 * `updated_at`, so they do not count; older payloads without the field fall
 * back to it. */
export function lastChange(a: AssetSummary): string {
  return a.content_updated_at ?? a.updated_at;
}

function compareKey(
  a: AssetSummary,
  b: AssetSummary,
  key: AssetSortKey,
  collator: Intl.Collator,
): number {
  switch (key) {
    case "updated":
      return cmp(lastChange(a), lastChange(b));
    case "created":
      return cmp(a.created_at, b.created_at);
    case "title":
      return collator.compare(a.title ?? a.slug, b.title ?? b.slug);
    case "versions":
      return a.version - b.version;
    case "kind":
      return cmp(a.kind, b.kind);
  }
}

/** Returns a sorted copy; the input array is left untouched. */
export function sortAssets(assets: readonly AssetSummary[], sort: AssetSort): AssetSummary[] {
  const sign = sort.order === "asc" ? 1 : -1;
  // App language, not the browser's: titles sort like the rest of the UI.
  const collator = nameCollator();
  return [...assets].sort((a, b) => {
    const primary = compareKey(a, b, sort.key, collator) * sign;
    if (primary !== 0) return primary;
    // Same secondary as the server: the most recent change breaks ties.
    return cmp(lastChange(b), lastChange(a)) || cmp(a.id, b.id) * sign;
  });
}
