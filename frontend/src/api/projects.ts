import { postJson, putJson, req, sortQuery } from "./_core";
import type {
  AssetSort,
  HygieneList,
  KeyDocument,
  KeyDocumentIn,
  ProjectDetail,
  ProjectExternalRef,
  ProjectGraph,
  ProjectHygiene,
  ProjectMemberRow,
  ProjectRole,
  ProjectSummary,
} from "./types";

export const listProjects = (params: { page?: number; page_size?: number } = {}) => {
  const qs = new URLSearchParams();
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  return req<{
    items: ProjectSummary[];
    total: number;
    page: number;
    page_size: number;
  }>(`/api/projects${qs.toString() ? "?" + qs.toString() : ""}`);
};

export const createProject = (name: string, description?: string) =>
  postJson<ProjectSummary>("/api/projects", { name, description: description ?? null });

export const getProject = (slug: string, sort?: AssetSort) =>
  req<ProjectDetail>(`/api/projects/${slug}${sortQuery(sort, "?")}`);

export const patchProject = (
  slug: string,
  body: { name?: string; description?: string | null },
) =>
  req<ProjectSummary>(`/api/projects/${slug}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const deleteProject = (slug: string) =>
  req<{ deleted: boolean }>(`/api/projects/${slug}`, { method: "DELETE" });

export const inviteProjectMember = (
  slug: string,
  email: string,
  role: "editor" | "viewer",
) => postJson<ProjectMemberRow>(`/api/projects/${slug}/members`, { email, role });

export const patchProjectMember = (
  slug: string,
  userId: string,
  role: "editor" | "viewer",
) =>
  req<ProjectMemberRow>(`/api/projects/${slug}/members/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });

export const kickProjectMember = (slug: string, userId: string) =>
  req<{ kicked: boolean }>(`/api/projects/${slug}/members/${userId}`, {
    method: "DELETE",
  });

export const leaveProject = (slug: string) =>
  postJson<{ left: boolean }>(`/api/projects/${slug}/leave`, {});

export const transferProjectOwner = (slug: string, userId: string) =>
  postJson<{ transferred: boolean }>(`/api/projects/${slug}/transfer-owner`, {
    user_id: userId,
  });

export const acceptProjectInvite = (token: string) =>
  postJson<{
    accepted: boolean;
    project_slug: string | null;
    project_name: string | null;
    role: ProjectRole;
  }>("/api/projects/accept-invite", { token });

export const getProjectGraph = (slug: string, opts: { tasks?: boolean } = {}) =>
  req<ProjectGraph>(`/api/projects/${slug}/graph${opts.tasks ? "?include=tasks" : ""}`);

export const getProjectHygiene = (slug: string, list: HygieneList, page = 1) =>
  req<ProjectHygiene>(`/api/projects/${slug}/hygiene?list=${list}&page=${page}`);

// ---------- Project links (ADR-0018) ----------

export const getProjectExternalRefs = (slug: string) =>
  req<ProjectExternalRef[]>(`/api/projects/${slug}/external-refs`);

/** Replaces every mapping of the project; returns the saved list. */
export const putProjectExternalRefs = (slug: string, refs: ProjectExternalRef[]) =>
  putJson<ProjectExternalRef[]>(`/api/projects/${slug}/external-refs`, { refs });

export const getKeyDocuments = (slug: string) =>
  req<KeyDocument[]>(`/api/projects/${slug}/key-documents`);

/** Replaces the ordered list; the array order is the new order. */
export const putKeyDocuments = (slug: string, documents: KeyDocumentIn[]) =>
  putJson<KeyDocument[]>(`/api/projects/${slug}/key-documents`, { documents });

/** Accepts a duplicate suggestion: `source duplicates target`. */
export const markDuplicate = (slug: string, sourceId: string, targetId: string) =>
  postJson<{ relation_id: string }>(`/api/projects/${slug}/hygiene/duplicates/mark`, {
    source_id: sourceId,
    target_id: targetId,
  });

/** "Not a duplicate": the pair is not suggested again. */
export const dismissDuplicate = (slug: string, sourceId: string, targetId: string) =>
  postJson<void>(`/api/projects/${slug}/hygiene/duplicates/dismiss`, {
    source_id: sourceId,
    target_id: targetId,
  });
