import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, type DocTypeInfo } from "../api";
import { t } from "./i18n";
import { qk } from "./queries";

// Admins change the vocabulary rarely; one fetch per session is enough.
const STALE_MS = 10 * 60_000;
const NONE: DocTypeInfo[] = [];

function useAllDocTypes(): DocTypeInfo[] {
  const { data } = useQuery({
    queryKey: qk.docTypes(),
    queryFn: api.listDocTypes,
    staleTime: STALE_MS,
  });
  return data ?? NONE;
}

// Derived per fetched list and shared by every caller, so memoised rows get stable values.
const activeLists = new WeakMap<DocTypeInfo[], DocTypeInfo[]>();
const labelMaps = new WeakMap<DocTypeInfo[], ReadonlyMap<string, string>>();

/** Active doc types in admin order, the ones a user may pick. Empty while loading or on failure. */
export function useDocTypes(): DocTypeInfo[] {
  const all = useAllDocTypes();
  let active = activeLists.get(all);
  if (!active) {
    active = all.filter((d) => !d.archived);
    activeLists.set(all, active);
  }
  return active;
}

/** Doc type labels (already in the caller's locale) by key, archived types
 * included. Empty while loading or when the request fails: callers fall back to the key. */
export function useDocTypeLabels(): ReadonlyMap<string, string> {
  const types = useAllDocTypes();
  let labels = labelMaps.get(types);
  if (!labels) {
    labels = new Map(types.map((d) => [d.key, d.label]));
    labelMaps.set(types, labels);
  }
  return labels;
}

/** Label of a doc type in the UI locale; untyped documents get the "no type" label. */
export function useDocTypeLabel(): (docType: string | null) => string {
  const labels = useDocTypeLabels();
  return useCallback(
    (key: string | null) => (key == null || key === "" ? t("assetMetaDialog.noDocType") : (labels.get(key) ?? key)),
    [labels],
  );
}
