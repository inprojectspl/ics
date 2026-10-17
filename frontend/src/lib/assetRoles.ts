import type { AssetSummary } from "../api";

// A row without `my_role` counts as owned: payloads that omit the field list
// only the caller's own assets.
export function canManage(a: AssetSummary): boolean {
  return !a.my_role || a.my_role === "owner";
}

export function canEdit(a: AssetSummary): boolean {
  return !a.my_role || a.my_role === "owner" || a.my_role === "editor";
}
