import { encodePath, postJson, putJson, req, withVersion } from "./_core";
import type {
  AssetDoc,
  AssetShareRow,
  CollectionFile,
  GraphResponse,
  ProjectShareRole,
  ProjectShareRow,
  ShareInfo,
  ShareLink,
  ShareMode,
  VersionRow,
} from "./types";

// ---------- Project shares: the asset assigned to more projects ----------

export const listProjectShares = (assetId: string) =>
  req<ProjectShareRow[]>(`/api/assets/${assetId}/project-shares`);

/** Adds the project or changes its role; returns the updated list. */
export const putProjectShare = (assetId: string, projectId: string, role: ProjectShareRole) =>
  putJson<ProjectShareRow[]>(`/api/assets/${assetId}/project-shares`, { project_id: projectId, role });

export const deleteProjectShare = (assetId: string, projectId: string) =>
  req<ProjectShareRow[]>(`/api/assets/${assetId}/project-shares/${projectId}`, {
    method: "DELETE",
  });

// ---------- Public ShareLink (per-asset, owner-side) ----------

export const listShares = (assetId: string) =>
  req<ShareLink[]>(`/api/assets/${assetId}/shares`);

export const createShare = (
  assetId: string,
  body: {
    mode: ShareMode;
    password?: string;
    allowed_emails?: string[];
    expires_at?: string | null;
    max_views?: number | null;
  },
) => postJson<ShareLink>(`/api/assets/${assetId}/shares`, body);

export const revokeShare = (shareId: string) =>
  req<void>(`/api/shares/${shareId}`, { method: "DELETE" });

// ---------- Visitor-side: token-scoped read endpoints ----------

export const getShareInfo = (token: string) => req<ShareInfo>(`/api/share/${token}/info`);

export const shareAuth = (token: string, password: string) =>
  postJson<{ ok: boolean }>(`/api/share/${token}/auth`, { password });

export const shareMagicClaim = (token: string, m: string) =>
  postJson<{ ok: boolean; email: string }>(`/api/share/${token}/magic-claim`, { m });

// `version` gives a read-only preview of an archived version. Only reading
// the current version counts against the link's `max_views`, see `share_doc`
// in the backend.
export const getShareDoc = (token: string, version?: number) =>
  req<AssetDoc>(withVersion(`/api/share/${token}/doc`, version));

export const getShareGraph = (token: string) =>
  req<GraphResponse>(`/api/share/${token}/graph`);

export const getShareVersions = (token: string) =>
  req<VersionRow[]>(`/api/share/${token}/versions`);

export const getShareCollectionFile = (token: string, path: string, version?: number) =>
  req<CollectionFile>(
    withVersion(`/api/share/${token}/file?path=${encodeURIComponent(path)}`, version),
  );

export const shareStaticUrl = (token: string, path: string) =>
  `/api/share/${token}/static/${encodePath(path)}`;

export const sharePdfUrl = (token: string, version?: number) =>
  withVersion(`/api/share/${token}/pdf`, version);

export const getShareHtmlGrant = (token: string, version?: number) =>
  req<{ url: string }>(withVersion(`/api/share/${token}/html-grant`, version));

// ---------- Per-user asset shares (granted_to specific email) ----------

export const listAssetShares = (slug: string) =>
  req<AssetShareRow[]>(`/api/assets/by-slug/${slug}/shares`);

export const createAssetShare = (slug: string, email: string, role: "editor" | "viewer") =>
  postJson<AssetShareRow & { new_account: boolean }>(
    `/api/assets/by-slug/${slug}/shares`,
    { email, role },
  );

export const deleteAssetShare = (slug: string, userId: string) =>
  req<void>(`/api/assets/by-slug/${slug}/shares/${userId}`, { method: "DELETE" });

export const patchAssetProject = (slug: string, projectId: string | null) =>
  req<{ project_id: string | null }>(`/api/assets/by-slug/${slug}/project`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId }),
  });
