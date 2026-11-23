// Google Sheets links of micro-applications (ADR-0031): the person's Google
// connection, the link of one collection to one sheet tab (set up by an AI
// agent through ics-mcp, read-only here), and the sync (preview, apply with
// decisions, check an uncertain write). A sync runs on a person's click or,
// with `auto_sync`, by itself as the app owner.
import { postJson, req, withParams } from "./_core";

export type SheetColumnOwner = "sheet" | "app" | "both";
export type SheetAccountMode = "owner_account" | "per_user";

export interface SheetColumn {
  field: string;
  header: string;
  owner: SheetColumnOwner;
}

export interface SheetLink {
  collection: string;
  spreadsheet_id: string;
  spreadsheet_url: string;
  sheet_title: string;
  /** A linked field whose values are unique in the sheet; without one, rows
   * are matched to records by content. */
  key_field: string | null;
  columns: SheetColumn[];
  account_mode: SheetAccountMode;
  revision: number;
  paused: boolean;
  /** Syncs by itself as the app owner while the app is in use: app changes at
   * once, the sheet every `auto_active_interval_seconds` while people have the
   * app open and every `auto_interval_seconds` while it is only awake. */
  auto_sync: boolean;
  /** Last automatic look at the sheet. */
  auto_checked_at: string | null;
  /** Why automatic syncing stopped until a person acts: `"conflicts"` (a
   * preview waits for decisions) or an API error code. */
  auto_error: string | null;
}

export type SheetOperationState = "previewed" | "applying" | "applied" | "stale" | "superseded" | "failed";
export type SheetGoogleStatus = "none" | "pending" | "confirmed" | "uncertain" | "failed";

export interface SheetConflict {
  field: string;
  base: unknown;
  app: unknown;
  sheet: unknown;
}

export interface SheetUpdate {
  record_id: string;
  row: number;
  import: Record<string, unknown>;
  export: Record<string, unknown>;
  conflicts: SheetConflict[];
}

export type SheetIssueKind =
  | "invalid_value"
  | "duplicate_key"
  | "record_not_in_app"
  | "unmatched_row"
  | "missing_required"
  | "removed_from_sheet"
  | "not_editable";

export interface SheetIssue {
  kind: SheetIssueKind;
  row?: number;
  record_id?: string;
  field?: string;
  detail?: string;
  fields?: string[];
  first_row?: number;
}

export interface SheetOperation {
  id: string;
  state: SheetOperationState;
  google_status: SheetGoogleStatus;
  error: string | null;
  /** Started by me: only then are the details below included. */
  mine: boolean;
  /** Made by the automatic sync, not a person. */
  auto: boolean;
  created_at: string | null;
  summary: { imports?: number; exports?: number; conflicts?: number; creates?: number; appends?: number; issues?: number; agreed?: number };
  result: { app_changes?: number; replayed?: boolean } | null;
  headers?: Record<string, string>;
  updates?: SheetUpdate[];
  creates?: { row: number; data: Record<string, unknown> }[];
  appends?: { record_id: string; values: Record<string, unknown> }[];
  issues?: SheetIssue[];
  decisions?: Record<string, "app" | "sheet">;
}

export interface SheetStatus {
  enabled: boolean;
  /** Rows a sync may handle, from the app owner's profile. */
  row_limit: number;
  /** How often the automatic sync reads the sheet while the app is awake
   * without open pages. */
  auto_interval_seconds: number;
  /** How often it reads the sheet while people have the app open; 30 s when
   * the server does not say. */
  auto_active_interval_seconds?: number;
  rights: { configure: boolean; run: boolean; owner: boolean };
  my_google: { email: string } | null;
  link: SheetLink | null;
  /** Only with `owner_account`: whether the owner's account is still connected. */
  owner_google_connected?: boolean;
  operations: SheetOperation[];
}

const BASE = "/api/micro-applications";

/** Starts the Google consent; a page navigation, not a fetch. `next` is the
 * app-relative path the browser returns to with `?google=<outcome>`. */
export const googleConnectUrl = (next: string) => withParams("/api/integrations/google/connect", { next });

export function disconnectGoogle(): Promise<{ disconnected: boolean }> {
  return req("/api/integrations/google", { method: "DELETE" });
}

export function getSheetStatus(assetId: string): Promise<SheetStatus> {
  return req(`${BASE}/${assetId}/sheets`);
}

export function removeSheetLink(assetId: string): Promise<void> {
  return req(`${BASE}/${assetId}/sheets`, { method: "DELETE" });
}

export function previewSheetSync(assetId: string): Promise<SheetOperation> {
  return postJson(`${BASE}/${assetId}/sheets/preview`, {});
}

/** `decisions` maps `"<record_id>:<field>"` of every conflict to the side kept. */
export function applySheetSync(
  assetId: string,
  opId: string,
  decisions: Record<string, "app" | "sheet">,
): Promise<SheetOperation> {
  return postJson(`${BASE}/${assetId}/sheets/operations/${opId}/apply`, { decisions });
}

export function checkSheetSync(assetId: string, opId: string): Promise<SheetOperation> {
  return postJson(`${BASE}/${assetId}/sheets/operations/${opId}/check`, {});
}

export function requestSheetAccess(assetId: string): Promise<{ sent: boolean; reason?: string }> {
  return postJson(`${BASE}/${assetId}/sheets/request-access`, {});
}
