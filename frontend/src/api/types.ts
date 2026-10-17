// Shared ICS domain types used by all api/* modules and UI components.
// Whatever the call layer (REST, TanStack Query), this file is the single
// source of truth for the server's JSON shape (metadata types are in `metadataTypes.ts`).

import type { AssetMetadata } from "./metadataTypes";
import type { OcrState } from "./ocrTypes";

export type * from "./metadataTypes";
export type * from "./auditTypes";
export type * from "./ocrTypes";
export type * from "./relationTypes";

/** Account role, mirrors `Role` in backend/app/constants.py. */
export type UserRole = "user" | "external" | "admin";
/** How the account signs in, mirrors `AuthMethod` in backend/app/constants.py. */
// "invite": created by an invitation, no password set yet (becomes "password" after setup).
type AuthMethod = "google_sso" | "password" | "invite";
/** Membership role inside a project. */
export type ProjectRole = "owner" | "editor" | "viewer";

export type Me = {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  dev_stub_sso: boolean;
  locale: "pl" | "en" | null;
};

/** Personal access token as listed; the secret itself is never returned again. */
export type AccessToken = {
  id: string;
  name: string;
  /** First characters after `ics_pat_`, to recognise the token. */
  prefix: string;
  scopes: string[];
  expires_at: string;
  last_used_at: string | null;
  created_at: string | null;
};

/** Response of the create call: the only time `token` is available. */
export type CreatedAccessToken = AccessToken & { token: string };

export type Quota = {
  used_bytes: number;
  quota_bytes: number;
};

export type AuthConfig = {
  google_oidc_enabled: boolean;
  self_register_enabled: boolean;
  dev_stub_sso: boolean;
  sync_image: string;
};

export type UploadShareMode = "org_sso" | "public";

export type AssetKind = "md_single" | "md_collection" | "html_bundle" | "pdf_doc" | "office_doc";

export type SecurityStatus = "clean" | "warn" | "critical";

type SecurityFinding = {
  severity: "info" | "warn" | "critical";
  rule: string;
  file: string;
  line: number | null;
  message: string;
};

export type SecurityReport = {
  status: SecurityStatus;
  findings: SecurityFinding[];
};

/** Sort keys accepted by the asset list endpoints (`?sort=&order=`). */
export type AssetSortKey = "updated" | "created" | "title" | "versions" | "kind";
export type SortOrder = "asc" | "desc";
export type AssetSort = { key: AssetSortKey; order: SortOrder };

export type AssetSummary = Partial<AssetMetadata> & {
  id: string;
  slug: string;
  title: string | null;
  kind: AssetKind;
  size_bytes: number | null;
  version: number;
  security_status: SecurityStatus | null;
  security_bypass?: boolean;
  active_share_modes?: string[];
  has_binding?: boolean;
  pinned_at?: string | null;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  content_updated_by?: string | null;
  /** In a project list: the asset's home is another project (ADR-0017). */
  shared_in?: boolean;
  my_role?: "owner" | "editor" | "viewer";
  access_source?: "owned" | "direct" | "project";
  owner?: { id: string; email: string; display_name: string | null } | null;
};

export type ReviewItem = {
  id: string;
  slug: string;
  title: string | null;
  kind: AssetKind;
  owner_id: string;
  /** Null when the owner row is gone. */
  owner_email: string | null;
  version: number;
  size_bytes: number | null;
  security_status: SecurityStatus;
  security_report: SecurityReport | null;
  security_bypass: boolean;
  security_bypass_at: string | null;
  security_bypass_by: string | null;
  security_bypass_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type UploadResponse = {
  id: string;
  slug: string;
  title: string | null;
  share_url: string;
};

export type PdfUploadResponse = UploadResponse & {
  page_count: number;
  security_status: SecurityStatus | null;
};

/** Page statistics of a pdf_doc. `text_page_count` is 0 for a scanned PDF
 * (no text layer, so search finds nothing in it). */
export type PdfInfo = {
  page_count: number;
  /** Pages with a text layer; OCR text is counted in `ocr_page_count`. */
  text_page_count: number;
  ocr_page_count?: number;
};

/** Format of the original file behind an office_doc (detected from content). */
type OfficeSourceFormat = "docx" | "odt" | "doc";

/** An office_doc as converted by the backend. `images` counts the pictures
 * the conversion dropped (they appear as an `[image]` marker in the text). */
export type OfficeDocumentInfo = {
  source_format: OfficeSourceFormat;
  images: number;
};

/** `share_url` is null while a critical document is held for review. */
export type DocumentUploadResponse = Omit<UploadResponse, "share_url"> &
  OfficeDocumentInfo & {
    kind: "office_doc";
    share_url: string | null;
    security_status: SecurityStatus | null;
  };

export type ShareMode = "org_sso" | "password" | "public" | "magic_email";

export type ShareLink = {
  id: string;
  token: string;
  mode: ShareMode;
  url: string;
  expires_at: string | null;
  max_views: number | null;
  view_count: number;
  revoked_at: string | null;
  created_at: string;
  allowed_emails: string[] | null;
  requires_password: boolean;
};

export type ShareInfo = {
  mode: ShareMode;
  requires_password: boolean;
  requires_login: boolean;
  requires_magic_link: boolean;
  has_access: boolean;
  title: string | null;
  expires_at: string | null;
  /** The role the visitor has on the asset regardless of the link. When set,
   * no mode challenge applies and the visitor gets the full view. */
  my_role?: EffectiveRole | null;
  /** Asset slug; the backend reveals it only to a role holder. */
  slug?: string | null;
};

/** Response of the `/v/<slug>` resolver. A union rather than one `url` field
 * with three meanings: the backend returns data (slug, token) and the SPA
 * router, which owns the routes, builds the addresses. No way in is a 404,
 * not a response variant. */
export type EntryResolution =
  | { action: "view"; slug: string }
  | { action: "login"; slug: string }
  | { action: "redirect"; url: string };

/**
 * Effective role on an asset (lattice from backend permissions.py).
 * Note: this is the full lattice (from `/doc`); listings
 * (`AssetSummary.my_role`) use the simplified "owner" | "editor" | "viewer"
 * roles. Do not mix them.
 */
export type EffectiveRole = "owner_file" | "project_owner" | "editor" | "viewer";

export type AssetDoc = Partial<AssetMetadata> & {
  id: string;
  slug: string;
  title: string | null;
  kind: AssetKind;
  version: number;
  size_bytes: number | null;
  entry_path?: string | null;
  /** Rendered Markdown; pdf_doc has none and gets null from the backend. */
  html: string;
  tree?: string[] | null;
  files?: string[] | null;
  security_status?: SecurityStatus | null;
  security_report?: SecurityReport | null;
  security_bypass?: boolean;
  /** Set for pdf_doc only. */
  pdf?: PdfInfo | null;
  /** pdf_doc only: OCR of the version shown. */
  ocr?: OcrState | null;
  /** Set for office_doc only; its `html` is the converted document. */
  document?: OfficeDocumentInfo | null;
  /** Caller's role; a viewer gets a read-only UI. */
  my_role?: EffectiveRole;
  created_at: string;
  updated_at: string;
  /** Set only when reading an archived version (read-only preview); for the
   * current version the backend returns null so the UI does not draw an
   * "outdated" warning above current content. */
  preview_version?: number | null;
  current_version?: number;
  /** Creation date of the version being read. */
  version_created_at?: string | null;
  /** The newer document that replaces this one. The backend sends it only
   * when this reader can open the successor, so the banner never points at
   * a document they have no way into. */
  superseded_by?: SupersededBy | null;
  /** The address this document should be shared under. The viewer rewrites
   * the address bar to it, because people copy the URL from the browser. */
  canonical_url?: string;
};

export type SupersededBy = {
  id: string;
  slug: string;
  title: string | null;
  /** When the `supersedes` relation was made. */
  since: string | null;
  /** Where this reader opens it: `/v/<slug>` or `/s/<token>`. */
  href: string;
};

export type CollectionFile = {
  slug: string;
  path: string;
  html: string;
  /** Version the content comes from (an archived preview returns it explicitly). */
  version?: number;
};

/** One version history entry. `author` has no e-mail domain (the backend
 * masks it for links); `author_email` is sent only to editor+. */
export type VersionRow = {
  version: number;
  size_bytes: number | null;
  created_at: string;
  created_by: string | null;
  author: string | null;
  author_email: string | null;
  is_current: boolean;
  /** Editor+ only; a read-only collaborator gets null. */
  storage_prefix?: string | null;
  /** What changed in this version, like a commit message; absent on older versions. */
  change_note?: string | null;
};

export type CollectionUploadResponse = {
  id: string;
  slug: string;
  title: string | null;
  kind: AssetKind;
  entry_path: string | null;
  file_count: number;
};

// Notification provider for a bound sync. The backend exposes a stable ID
// per provider; the frontend does not know its semantics and uses it only
// as a tag for the (provider, webhook_url) pair. The dropdown is fed from
// `/api/bindings/providers`.
export type NotificationProviderId = "google_chat";

export type NotificationProviderInfo = {
  id: NotificationProviderId;
  display_name: string;
  url_hint: string;
};

export type Binding = {
  id: string;
  asset_id: string;
  gitlab_project_url: string | null;
  webhook_url: string | null;
  provider: NotificationProviderId | null;
  public_key: string;
  last_sync_at: string | null;
  last_sync_commit_sha: string | null;
  created_at: string;
};

export type BindingWithSecret = Binding & {
  private_key: string;
};

/** One entry of a version comparison, the same shape for md_single,
 * md_collection and html_bundle. `added_lines`/`removed_lines` are `null` for
 * binary files and for files above the byte threshold (the backend does not
 * diff a minified one-liner). */
export type DiffFileChange = {
  path: string;
  change: "added" | "removed" | "modified";
  binary: boolean;
  added_lines: number | null;
  removed_lines: number | null;
  size_from: number | null;
  size_to: number | null;
};

/** Comparison summary (without `?path=`): one shape for all kinds. A single
 * file's content is fetched separately via `?path=`. */
export type DiffSummary = {
  kind: AssetKind;
  from_version: number;
  to_version: number;
  from_meta: VersionRow | null;
  to_meta: VersionRow | null;
  files: DiffFileChange[];
};

/** Response for `?path=`: unified diff of one file. */
export type DiffFile = {
  path: string;
  change: "added" | "removed" | "modified";
  diff: string;
};

export type AdminUser = {
  id: string;
  email: string;
  display_name: string | null;
  role: UserRole;
  auth_method: AuthMethod;
  email_verified: boolean;
  email_verified_at: string | null;
  locked_until: string | null;
  locked: boolean;
  storage_quota_bytes: number;
  bundle_max_bytes: number;
  html_autobypass: boolean;
  asset_count: number;
  asset_bytes: number;
  created_at: string;
  last_login_at: string | null;
};

/** Role an asset has in a project it is assigned to besides its home. */
export type ProjectShareRole = "viewer" | "editor";

/** `GET /api/assets/{id}/project-shares` row. */
export type ProjectShareRow = {
  project_id: string;
  project_slug: string;
  project_name: string;
  role: ProjectShareRole;
  created_at: string | null;
};

export type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  created_by: string | null;
  created_at: string;
  my_role: "owner" | "editor" | "viewer" | null;
  member_count: number;
  asset_count: number;
};

export type ProjectMemberRow = {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  role: "owner" | "editor" | "viewer";
  invited_at: string;
  accepted_at: string | null;
  invited_by: string | null;
};

export type ProjectDetail = ProjectSummary & {
  members: ProjectMemberRow[];
  // Full AssetSummary rows (backend uses the shared serializer) so the
  // project file list renders with the same <AssetRow> as the home view.
  assets: AssetSummary[];
  // True when the project has more files than the response cap (200).
  assets_truncated?: boolean;
};

export type AssetShareRow = {
  id: string;
  user_id: string;
  email: string;
  display_name: string | null;
  role: "editor" | "viewer";
  granted_at: string;
  granted_by: string | null;
};

export type GraphResponse = {
  nodes: Array<{
    path: string;
    title: string;
    in_degree: number;
    out_degree: number;
  }>;
  edges: Array<{ from: string; to: string }>;
};

/** How an agent reads an HTML file through `file-mcp`. */
export type AgentFormat = "markdown" | "raw";

/** One agent read: the file (`null`/absent for the entry), its format and version. */
export type AgentReadOpts = { path?: string | null; format?: AgentFormat; version?: number };

/** `GET /by-slug/{slug}/agent-view`: the text an MCP agent reads through
 * `file-mcp` for one file, whole, with its Markdown rendered by ICS. */
export type AgentView = {
  slug: string;
  kind: AssetKind;
  path: string;
  content: string;
  /** The content rendered by ICS; `null` when it is not Markdown (raw HTML, CSS, JS). */
  html: string | null;
  total_lines: number;
  /** Lines in `content`, fewer than `total_lines` when `truncated`. */
  shown_lines: number;
  size_bytes: number;
  /** About four characters per token, over the whole text. */
  estimated_tokens: number;
  /** Default `ics_asset_read` calls needed to read the whole file. */
  agent_reads: number;
  lines_per_read: number;
  /** `content` was cut to the preview size cap; the totals still describe the whole text. */
  truncated: boolean;
  version: number;
  current_version: number;
  /** Set when the file was converted (HTML with `format=markdown`, documents). */
  format?: "markdown";
  page_count?: number;
  /** pdf_doc only: OCR of the version read. */
  ocr?: OcrState | null;
};

/** `GET /by-slug/{slug}/files-mcp`: the file inventory an agent sees. */
export type AgentFiles = {
  slug: string;
  kind: AssetKind;
  version: number;
  current_version: number;
  entry_path: string | null;
  files: { path: string; size_bytes: number }[];
};
