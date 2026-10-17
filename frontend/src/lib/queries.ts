// All query keys in one place, so invalidation in mutations references the
// same literals as useQuery. `qk.assets()` is `["assets"]` and
// `qk.asset(slug)` is `["asset", slug]`, so invalidating `qk.assets()` does not
// touch a specific asset doc (and vice versa).

import { queryOptions } from "@tanstack/react-query";
import { api, type AgentReadOpts } from "../api";
import type { NotificationFilter } from "../api/notificationTypes";

export const qk = {
  me: () => ["me"] as const,
  quota: () => ["quota"] as const,
  authConfig: () => ["authConfig"] as const,

  assets: () => ["assets"] as const,
  assetSearch: (q: string, limit: number) => ["assets", "search", q, limit] as const,
  asset: (slug: string) => ["asset", slug] as const,
  assetDoc: (slug: string) => ["asset", slug, "doc"] as const,
  assetSummary: (slug: string) => ["asset", slug, "summary"] as const,
  assetMeta: (slug: string) => ["asset", slug, "meta"] as const,
  relations: (slug: string) => ["asset", slug, "relations"] as const,
  externalRefs: (assetId: string) => ["asset", assetId, "external-refs"] as const,
  outline: (slug: string) => ["asset", slug, "outline"] as const,
  ocr: (slug: string, version?: number) => ["asset", slug, "ocr", version ?? null] as const,
  neighbourhood: (slug: string, depth?: number) =>
    depth ? (["asset", slug, "neighbourhood", depth] as const) : (["asset", slug, "neighbourhood"] as const),
  assetSource: (slug: string, path?: string) =>
    path ? (["asset", slug, "source", path] as const) : (["asset", slug, "source"] as const),
  assetGraph: (slug: string) => ["asset", slug, "graph"] as const,
  agentViews: (slug: string) => ["asset", slug, "agent-view"] as const,
  agentView: (slug: string, opts: AgentReadOpts) => ["asset", slug, "agent-view", opts] as const,
  agentFiles: (slug: string, version?: number) =>
    ["asset", slug, "agent-files", version ?? null] as const,
  assetVersions: (assetId: string) => ["asset", assetId, "versions"] as const,
  assetShares: (slug: string) => ["asset", slug, "shares"] as const,

  shares: (assetId: string) => ["asset", assetId, "share-links"] as const,
  projectShares: (assetId: string) => ["asset", assetId, "project-shares"] as const,
  shareInfo: (token: string) => ["share", token, "info"] as const,
  shareDoc: (token: string) => ["share", token, "doc"] as const,

  projects: () => ["projects"] as const,
  project: (slug: string) => ["project", slug] as const,
  projectGraph: (slug: string) => ["project", slug, "graph"] as const,
  projectHygiene: (slug: string, list?: string, page?: number) =>
    list ? (["project", slug, "hygiene", list, page ?? 1] as const) : (["project", slug, "hygiene"] as const),
  keyDocuments: (slug: string) => ["project", slug, "key-documents"] as const,
  projectExternalRefs: (slug: string) => ["project", slug, "external-refs"] as const,

  accessTokens: () => ["access-tokens"] as const,

  bindings: (assetId: string) => ["asset", assetId, "bindings"] as const,
  notificationProviders: () => ["notification-providers"] as const,

  adminUsers: (params?: Record<string, unknown>) =>
    params ? (["admin", "users", params] as const) : (["admin", "users"] as const),
  adminCdn: () => ["admin", "cdn"] as const,
  adminReview: () => ["admin", "review"] as const,
  adminAudit: (params?: Record<string, unknown>) =>
    params ? (["admin", "audit", params] as const) : (["admin", "audit"] as const),

  sharedWithMe: () => ["shared-with-me"] as const,

  // Every inbox key starts with "notifications", so a stream `reset`
  // invalidates the summary and all list filters at once.
  notifications: () => ["notifications"] as const,
  notificationSummary: () => ["notifications", "summary"] as const,
  notificationList: (filter: NotificationFilter) => ["notifications", "list", filter] as const,
  notificationPreferences: () => ["notification-preferences"] as const,
  pushDevices: () => ["notification-preferences", "push-devices"] as const,
  pushHere: () => ["notification-preferences", "push-devices", "here"] as const,
  assetWatch: (assetId: string) => ["asset", assetId, "watch"] as const,
  projectWatch: (slug: string) => ["project", slug, "watch"] as const,
  watches: (page: number) => ["watches", page] as const,
  allWatches: () => ["watches"] as const,

  docTypes: () => ["doc-types"] as const,
  adminDocTypes: () => ["admin", "doc-types"] as const,
};

/**
 * The caller's projects (first 200), shared by the sidebar, palette, lists
 * and pickers: one definition, so every consumer reads the same cache entry.
 */
export const projectListQuery = queryOptions({
  queryKey: qk.projects(),
  queryFn: () => api.listProjects({ page_size: 200 }),
  select: (page) => page.items,
});
