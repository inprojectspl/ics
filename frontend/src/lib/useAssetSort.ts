import { useCallback, useMemo, useState } from "react";

import type { AssetSort } from "../api";
import { DEFAULT_ASSET_SORT, parseAssetSort } from "./assetSort";

/** Asset lists that remember their own sort choice. */
export type AssetListScope = "home" | "project";

function readStored(key: string): AssetSort {
  try {
    const raw = window.localStorage.getItem(key);
    return (raw && parseAssetSort(JSON.parse(raw))) || DEFAULT_ASSET_SORT;
  } catch {
    // Blocked storage or a hand-edited value: fall back to the default.
    return DEFAULT_ASSET_SORT;
  }
}

/**
 * Sort choice of one asset list, remembered per user (the key includes the
 * user id, so a shared browser does not carry one person's choice over to
 * another) and per list scope.
 */
export function useAssetSort(scope: AssetListScope, userId: string) {
  const key = `ics.assetSort.${scope}.${userId}`;
  // Read once per storage key; a picked value is kept together with the key
  // it belongs to, so a different user or scope falls back to its own
  // stored choice without an effect.
  const stored = useMemo(() => readStored(key), [key]);
  const [picked, setPicked] = useState<{ key: string; sort: AssetSort } | null>(null);
  const sort = picked?.key === key ? picked.sort : stored;

  const setSort = useCallback(
    (next: AssetSort) => {
      setPicked({ key, sort: next });
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Storage unavailable: the choice still applies for this visit.
      }
    },
    [key],
  );

  return { sort, setSort };
}
