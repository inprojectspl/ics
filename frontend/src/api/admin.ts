import { patchJson, postJson, req } from "./_core";
import type {
  AdminDocType,
  AdminUser,
  AuditPage,
  DocType,
  DocTypeCreate,
  DocTypeUpdate,
  ReviewItem,
  UserRole,
} from "./types";

// ---------- Users ----------

export const adminUsersList = (params: {
  q?: string;
  role?: UserRole;
  status?: string;
  page?: number;
  page_size?: number;
} = {}) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  return req<{
    summary: {
      total: number;
      active_30d: number;
      locked: number;
      unverified: number;
      admins: number;
    };
    users: AdminUser[];
    total: number;
    page: number;
    page_size: number;
  }>(`/api/admin/users${qs.toString() ? "?" + qs.toString() : ""}`);
};

export const adminUserGet = (id: string) => req<AdminUser>(`/api/admin/users/${id}`);

export const adminUserInvite = (body: {
  email: string;
  display_name?: string | null;
  role?: "user" | "external" | "admin";
}) => postJson<AdminUser>("/api/admin/users", body);

export const adminUserPatch = (
  id: string,
  body: {
    display_name?: string | null;
    role?: "user" | "external" | "admin";
    storage_quota_bytes?: number;
    bundle_max_bytes?: number;
    html_autobypass?: boolean;
  },
) =>
  req<AdminUser>(`/api/admin/users/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const adminUserLock = (id: string, minutes: number, reason?: string) =>
  postJson<{ locked_until: string }>(`/api/admin/users/${id}/lock`, {
    minutes,
    reason: reason || null,
  });

export const adminUserUnlock = (id: string) =>
  req<{ locked_until: null }>(`/api/admin/users/${id}/lock`, { method: "DELETE" });

export const adminUserPasswordReset = (id: string) =>
  postJson<{ sent_to: string }>(`/api/admin/users/${id}/password-reset`, {});

export const adminUserReinvite = (id: string) =>
  postJson<{ sent_to: string }>(`/api/admin/users/${id}/reinvite`, {});

export const adminRevokeUserTokens = (id: string) =>
  postJson<{ revoked: number }>(`/api/admin/users/${id}/tokens/revoke`, {});

export const adminUserDelete = (id: string) =>
  req<{ deleted: true; cascade_assets: number }>(`/api/admin/users/${id}`, { method: "DELETE" });

// ---------- CDN allowlist ----------

export const adminCdnList = () =>
  req<{
    builtin: string[];
    runtime: Array<{
      id: string;
      host: string;
      note: string | null;
      added_by: string | null;
      created_at: string;
    }>;
  }>("/api/admin/cdn-allowlist");

export const adminCdnAdd = (host: string, note?: string) =>
  postJson<{ id: string; host: string }>("/api/admin/cdn-allowlist", {
    host,
    note: note || null,
  });

export const adminCdnRemove = (id: string) =>
  req<void>(`/api/admin/cdn-allowlist/${id}`, { method: "DELETE" });

// ---------- Security review ----------

export const adminReviewQueue = () => req<ReviewItem[]>("/api/admin/review");

export const adminReviewDetail = (assetId: string) =>
  req<ReviewItem>(`/api/admin/assets/${assetId}/review`);

export const adminGrantBypass = (assetId: string, reason: string) =>
  postJson<ReviewItem>(`/api/admin/assets/${assetId}/security-bypass`, { reason });

export const adminRevokeBypass = (assetId: string) =>
  req<ReviewItem>(`/api/admin/assets/${assetId}/security-bypass`, { method: "DELETE" });

// ---------- Doc types ----------

/** Every doc type, archived ones included; rows carry both stored labels. */
export const adminListDocTypes = () =>
  req<AdminDocType[]>("/api/admin/doc-types");

export const adminCreateDocType = (body: DocTypeCreate) =>
  postJson<AdminDocType>("/api/admin/doc-types", body);

export const adminUpdateDocType = (key: DocType, body: DocTypeUpdate) =>
  patchJson<AdminDocType>(`/api/admin/doc-types/${encodeURIComponent(key)}`, body);

// ---------- Audit log ----------

export const listAuditActions = () => req<string[]>("/api/admin/audit/actions");

export const listAudit = (
  params: {
    action?: string;
    actor?: string;
    target?: string;
    limit?: number;
    before_id?: number;
  } = {},
  signal?: AbortSignal,
) => {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
  }
  return req<AuditPage>(`/api/admin/audit${qs.toString() ? "?" + qs.toString() : ""}`, { signal });
};
