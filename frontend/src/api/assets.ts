import { encodePath, patchJson, postJson, putJson, req, sortQuery, withVersion } from "./_core";
import type {
  AgentFiles,
  AgentReadOpts,
  AgentView,
  AssetDoc,
  AssetMetaDetail,
  AssetMetaPatch,
  AssetMetaView,
  AssetSort,
  AssetSummary,
  CollectionFile,
  CollectionUploadResponse,
  DiffFile,
  DiffSummary,
  DocTypeInfo,
  DocumentUploadResponse,
  EntryResolution,
  GraphResponse,
  OcrRequest,
  OcrResponse,
  PdfUploadResponse,
  UploadResponse,
  UploadShareMode,
  VersionRow,
} from "./types";

import type { AssetFilter, AssetScope } from "../lib/useAssetFilter";

// ---------- Listing + read ----------

export type AssetPage = {
  items: AssetSummary[];
  total: number;
  page: number;
  page_size: number;
  scope_counts?: Partial<Record<AssetScope, number>>;
  filter_counts?: Partial<Record<AssetFilter, number>>;
};

export type AssetListOptions = {
  q?: string;
  scope?: AssetScope;
  filters?: readonly AssetFilter[];
  facets?: boolean;
  signal?: AbortSignal;
};

// The server caps page_size at 200; every filter applies before paging.
export const listAssets = (page = 1, pageSize = 200, sort?: AssetSort, opts: AssetListOptions = {}) => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (opts.q !== undefined) params.set("q", opts.q);
  if (opts.scope) params.set("scope", opts.scope);
  if (opts.facets) params.set("facets", "true");
  for (const filter of opts.filters ?? []) params.append("f", filter);
  return req<AssetPage>(`/api/assets?${params}${sortQuery(sort, "&")}`, { signal: opts.signal });
};

export const searchAssets = (q: string, limit: number = 50, sort?: AssetSort, signal?: AbortSignal) =>
  req<AssetSummary[]>(
    `/api/assets/search?q=${encodeURIComponent(q)}&limit=${limit}${sortQuery(sort, "&")}`,
    { signal },
  );

export const getDoc = (slug: string, version?: number) =>
  req<AssetDoc>(withVersion(`/api/assets/by-slug/${slug}/doc`, version));

/** Resolves how this slug opens for this visitor.
 * The only asset endpoint that answers anonymous callers: 404 means "no
 * way in" and is indistinguishable from a nonexistent slug. */
export const getEntry = (slug: string) =>
  req<EntryResolution>(`/api/assets/by-slug/${slug}/entry`);

/** AssetSummary row for a single asset: feeds the reader's management
 * panel with the same data as the row on the list. The endpoint is
 * editor+, so a reader gets 404; call it only when `doc.my_role` allows. */
export const getAssetSummary = (slug: string) =>
  req<AssetSummary>(`/api/assets/by-slug/${slug}/summary`);

export const getSource = (slug: string, path?: string) =>
  req<{ path: string; content: string }>(
    `/api/assets/by-slug/${slug}/source${path ? `?path=${encodeURIComponent(path)}` : ""}`,
  );

/** What an MCP agent reads from one file (`ics_asset_read`), editor+. */
export const getAgentView = (slug: string, opts: AgentReadOpts = {}) => {
  const q = new URLSearchParams();
  if (opts.path) q.set("path", opts.path);
  if (opts.format) q.set("format", opts.format);
  if (opts.version) q.set("version", String(opts.version));
  const qs = q.toString();
  return req<AgentView>(`/api/assets/by-slug/${slug}/agent-view${qs ? `?${qs}` : ""}`);
};

export const listAgentFiles = (slug: string, version?: number) =>
  req<AgentFiles>(withVersion(`/api/assets/by-slug/${slug}/files-mcp`, version));

export const getGraph = (slug: string) =>
  req<GraphResponse>(`/api/assets/by-slug/${slug}/graph`);

export const getCollectionFile = (slug: string, path: string, version?: number) =>
  req<CollectionFile>(
    withVersion(`/api/assets/by-slug/${slug}/file?path=${encodeURIComponent(path)}`, version),
  );

// Same-origin URL for owner-preview of html_bundle. Path-style (not query)
// so relative URLs inside the served HTML resolve to sibling files under
// the same /static/ base.
export const staticUrl = (slug: string, path: string) =>
  `/api/assets/by-slug/${slug}/static/${encodePath(path)}`;

/** Raw PDF bytes of a pdf_doc, read by the in-page PDF viewer. */
export const pdfUrl = (slug: string, version?: number) =>
  withVersion(`/api/assets/by-slug/${slug}/pdf`, version);

/** OCR state of a pdf_doc version (ADR-0021). */
export const getOcr = (slug: string, version?: number) =>
  req<OcrResponse>(withVersion(`/api/assets/by-slug/${slug}/ocr`, version));

/** Queue OCR of the current version: the first run or a retry. */
export const requestOcr = (assetId: string, body: OcrRequest = {}) =>
  postJson<OcrResponse>(`/api/assets/${assetId}/ocr`, body);

export const getAssetHtmlGrant = (slug: string, version?: number) =>
  req<{ url: string }>(withVersion(`/api/assets/by-slug/${slug}/html-grant`, version));

// ---------- Asset metadata mutations ----------

export const pinAsset = (assetId: string) =>
  req<{ id: string; pinned_at: string | null }>(`/api/assets/${assetId}/pin`, {
    method: "POST",
  });

export const unpinAsset = (assetId: string) =>
  req<{ id: string; pinned_at: string | null }>(`/api/assets/${assetId}/pin`, {
    method: "DELETE",
  });

export const renameAsset = (assetId: string, title: string) =>
  req<{ id: string; title: string }>(`/api/assets/${assetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });

export const deleteAsset = (assetId: string) =>
  req<void>(`/api/assets/${assetId}`, { method: "DELETE" });

// ---------- Document metadata (ADR-0015) ----------

export const getAssetMeta = (slug: string) =>
  req<AssetMetaView>(`/api/assets/by-slug/${slug}/meta`);

export const patchMeta = (assetId: string, patch: AssetMetaPatch) =>
  patchJson<AssetMetaDetail>(`/api/assets/${assetId}/meta`, patch);

/** "Still current": records a review without a content change. */
export const markReviewed = (assetId: string) =>
  postJson<AssetMetaDetail>(`/api/assets/${assetId}/reviewed`, {});

/** Replaces the whole tag list; the server normalises it (lowercase, deduplicated). */
export const setTags = (assetId: string, tags: string[]) =>
  putJson<{ id: string; tags: string[] }>(`/api/assets/${assetId}/tags`, { tags });

/** Archived types come too: documents keep them, so their badges still need a label. */
export const listDocTypes = () => req<DocTypeInfo[]>("/api/doc-types?include_archived=true");

/** `{slug: title}` for the `[[ics:...]]` link targets the caller may see (ADR-0006 addendum). */
export const linkTitles = (slugs: string[]) =>
  req<Record<string, string>>(
    `/api/assets/link-titles?${slugs.map((s) => `slug=${encodeURIComponent(s)}`).join("&")}`,
  );

// ---------- Inline editing + per-file CRUD ----------

export const editContent = (
  assetId: string,
  content: string,
  path?: string,
  changeNote?: string,
) =>
  putJson<{ id: string; version: number; path: string; size_bytes: number }>(
    `/api/assets/${assetId}/content`,
    { content, path: path ?? null, change_note: changeNote },
  );

export const addVaultFile = async (assetId: string, file: File, path?: string) => {
  const form = new FormData();
  form.append("file", file);
  if (path) form.append("path", path);
  return req<{ id: string; version: number; added_path: string; size_bytes: number }>(
    `/api/assets/${assetId}/files`,
    { method: "POST", body: form },
  );
};

export const deleteVaultFile = (assetId: string, path: string) =>
  req<{
    id: string;
    version: number;
    deleted_path: string;
    entry_path: string;
    size_bytes: number;
  }>(`/api/assets/${assetId}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" });

export const createEmptyVaultFile = (assetId: string, path: string) =>
  req<{ id: string; version: number; added_path: string; size_bytes: number }>(
    `/api/assets/${assetId}/files/empty`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    },
  );

export const moveVaultFile = (assetId: string, fromPath: string, toPath: string) =>
  req<{
    id: string;
    version: number;
    from_path: string;
    to_path: string;
    entry_path: string;
  }>(`/api/assets/${assetId}/files/move`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_path: fromPath, to_path: toPath }),
  });

// ---------- Versioning ----------

export const listVersions = (assetId: string) =>
  req<VersionRow[]>(`/api/assets/${assetId}/versions`);

export const uploadVersion = async (
  assetId: string,
  files: { file: File; path: string }[],
  changeNote?: string,
): Promise<{
  id: string;
  version: number;
  entry_path: string;
  file_count: number;
  size_bytes: number;
}> => {
  const fd = new FormData();
  for (const { file, path } of files) {
    fd.append("files", file);
    fd.append("paths", path);
  }
  if (changeNote) fd.append("change_note", changeNote);
  return req(`/api/assets/${assetId}/versions`, { method: "POST", body: fd });
};

export const restoreVersion = (assetId: string, n: number) =>
  req<{
    id: string;
    version: number;
    entry_path: string;
    restored_from: number;
    size_bytes: number;
  }>(`/api/assets/${assetId}/versions/${n}/restore`, { method: "POST" });

export const diffVersions = (assetId: string, fromV: number, toV: number) =>
  req<DiffSummary>(`/api/assets/${assetId}/versions/${fromV}/diff/${toV}`);

/** Unified diff of one file, including one that exists in only one of the
 * versions (added/removed). A binary file returns 415, so callers skip those
 * entries (`DiffFileChange.binary`). */
export const diffVersionFile = (
  assetId: string,
  fromV: number,
  toV: number,
  path: string,
) =>
  req<DiffFile>(
    `/api/assets/${assetId}/versions/${fromV}/diff/${toV}?path=${encodeURIComponent(path)}`,
  );

// ---------- Uploads ----------

// Optional `projectId` assigns the new asset to a project on creation -
// used when uploading from the project page (the backend validates that
// the caller is an owner/editor of that project).
const uploadQuery = (shareMode: UploadShareMode, projectId?: string) =>
  `?share_mode=${shareMode}${projectId ? `&project_id=${encodeURIComponent(projectId)}` : ""}`;

export const uploadMarkdown = async (
  file: File,
  shareMode: UploadShareMode = "org_sso",
  projectId?: string,
): Promise<UploadResponse> => {
  const fd = new FormData();
  fd.append("file", file);
  return req<UploadResponse>(`/api/assets${uploadQuery(shareMode, projectId)}`, {
    method: "POST",
    body: fd,
  });
};

export const uploadPdf = async (
  file: File,
  shareMode: UploadShareMode = "org_sso",
  projectId?: string,
): Promise<PdfUploadResponse> => {
  const fd = new FormData();
  fd.append("file", file);
  return req<PdfUploadResponse>(`/api/assets/pdf${uploadQuery(shareMode, projectId)}`, {
    method: "POST",
    body: fd,
  });
};

/** A Word/ODF text document (.docx, .odt, .doc), converted server-side. */
export const uploadDocument = async (
  file: File,
  shareMode: UploadShareMode = "org_sso",
  projectId?: string,
): Promise<DocumentUploadResponse> => {
  const fd = new FormData();
  fd.append("file", file);
  return req<DocumentUploadResponse>(`/api/assets/document${uploadQuery(shareMode, projectId)}`, {
    method: "POST",
    body: fd,
  });
};

export const uploadCollection = async (
  files: { file: File; path: string }[],
  shareMode: UploadShareMode = "org_sso",
  projectId?: string,
): Promise<CollectionUploadResponse> => {
  const fd = new FormData();
  for (const { file, path } of files) {
    fd.append("files", file);
    fd.append("paths", path);
  }
  return req<CollectionUploadResponse>(
    `/api/assets/collection${uploadQuery(shareMode, projectId)}`,
    { method: "POST", body: fd },
  );
};

export const uploadHtmlBundle = async (
  files: { file: File; path: string }[],
  shareMode: UploadShareMode = "org_sso",
  projectId?: string,
): Promise<CollectionUploadResponse> => {
  const fd = new FormData();
  for (const { file, path } of files) {
    fd.append("files", file);
    fd.append("paths", path);
  }
  return req<CollectionUploadResponse>(
    `/api/assets/html${uploadQuery(shareMode, projectId)}`,
    { method: "POST", body: fd },
  );
};
