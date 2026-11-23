// Micro-application management for the panel: status, control, data,
// access and logs. There is deliberately no create or upload call here:
// packages are planned and applied through ICS-MCP only.
import { postJson, putJson, req } from "./_core";

export type MicroAppAction = "enable" | "suspend" | "sleep" | "restart";
export type RuntimeState = "sleeping" | "ready" | "running" | "draining" | "suspended" | "unknown";

export interface MicroAppRights {
  use: boolean;
  publish: boolean;
  control: boolean;
  manage_access: boolean;
  prepare: boolean;
}

export interface MicroApp {
  asset_id: string;
  slug: string;
  title: string | null;
  description: string | null;
  environment: string;
  app_url: string;
  owner: { id: string; display_name: string } | null;
  project: { id: string; name: string; slug: string } | null;
  desired_state: "enabled" | "suspended";
  generation: number;
  package_version: number;
  active_release: {
    id: string;
    package_version: number;
    digest: string;
    activated_at: string | null;
    schema: [number, number];
  } | null;
  last_publication: {
    operation_id: string;
    status: string;
    step: string;
    error_code: string | null;
    at: string | null;
  } | null;
  runtime: {
    state: RuntimeState;
    sampled_at: string | null;
    fresh: boolean;
    inflight: number;
    queued: number;
    open_connections: number;
    last_used_at: string | null;
    last_error: { code: string; at: string | null } | null;
    breaker_open_until: string | null;
    /** Open live pages (`sockets`) and the distinct people behind them; 0
     * when the runtime sample is stale. */
    realtime: { sockets: number; people: number };
  };
  data: {
    measured: boolean;
    sampled_at: string | null;
    bytes: number | null;
    rows_estimate: number | null;
    tables: number | null;
    schema_version: number;
  };
  rights: MicroAppRights;
  suspended_at: string | null;
}

export interface MicroAppOperation {
  operation_id: string;
  action: string;
  status: "pending" | "running" | "succeeded" | "failed";
  terminal: boolean;
  step: string;
  error: { code: string; detail: string | null } | null;
}

export interface MicroAppLogLine {
  id: number;
  ts: string | null;
  level: string;
  source: string;
  message: string;
  request_id: string | null;
  release_id: string | null;
}

/** `GET /{id}/document`: the app's data as one Markdown document. With
 * `collection` set, only that collection's rows after `cursor`. */
export interface MicroAppDocument {
  asset_id: string;
  title: string | null;
  markdown: string;
  /** `markdown` rendered and sanitized by ICS, like an md asset's body. */
  html?: string;
  collections: { name: string; readable: boolean; next_cursor: string | null }[];
  /** Why the data is not available now (`app_suspended`, ...), else `null`. */
  error?: string | null;
}

export interface MicroAppPerson {
  email: string;
  display_name: string;
  can_open: boolean;
  /** Owner, a share role, or `null` when the person cannot open the asset. */
  access: string | null;
  /** Roles granted directly. */
  roles: string[];
  /** Single permissions granted directly, beside the roles. */
  permissions: string[];
  /** What the person may do now: roles expanded, plus project grants. */
  effective_permissions: string[];
}

export interface MicroAppProjectAccess {
  project_id: string;
  name: string;
  roles: string[];
  permissions: string[];
  members_can_open: boolean;
}

/** A named set of the app's permissions, declared in its manifest. */
export interface MicroAppRole {
  role: string;
  label: string;
  description: string | null;
  permissions: string[];
}

export interface MicroAppPermissionInfo {
  permission: string;
  /** The manifest's name for it; null for the platform permissions. */
  label: string | null;
  description: string | null;
  /** `app.publish` / `app.control`: co-authors and operators, not app users. */
  platform: boolean;
  allows: string[];
}

/** Direct grants of one person, project or link. */
export interface MicroAppGrantSet {
  roles: string[];
  permissions: string[];
}

export interface MicroAppAccess {
  asset_id: string;
  title: string | null;
  app_url: string;
  roles: MicroAppRole[];
  permissions: MicroAppPermissionInfo[];
  people: MicroAppPerson[];
  projects: MicroAppProjectAccess[];
}

export type MicroAppAccessChange = MicroAppGrantSet & { can_open?: boolean } & (
  | { user_email: string }
  | { project_id: string }
);

export interface MicroAppAccessResult {
  added: string[];
  removed: string[];
  roles_added: string[];
  roles_removed: string[];
  open_change: string | null;
  person?: MicroAppPerson;
  project?: Omit<MicroAppProjectAccess, "name">;
  /** The person still opens the app this way (owner, editor, project). */
  still_opens_via?: string | null;
}

const BASE = "/api/micro-applications";

export function getMicroApp(assetId: string): Promise<MicroApp> {
  return req<MicroApp>(`${BASE}/${assetId}`);
}

function newKey(): string {
  return `panel-${crypto.randomUUID()}`;
}

/** One control action; the idempotency key travels as a header and in the
 * body, so a retried click of the same request cannot act twice. */
export function controlMicroApp(
  assetId: string,
  action: MicroAppAction,
  expectedGeneration: number,
  idempotencyKey: string = newKey(),
): Promise<MicroAppOperation> {
  return postJson<MicroAppOperation>(
    `${BASE}/${assetId}/control`,
    { action, expected_generation: expectedGeneration, idempotency_key: idempotencyKey },
    { headers: { "Idempotency-Key": idempotencyKey } },
  );
}

export function listLogs(assetId: string): Promise<{ items: MicroAppLogLine[] }> {
  return req(`${BASE}/${assetId}/logs?limit=30`);
}

export function getMicroAppDocument(
  assetId: string,
  params: { collection?: string; cursor?: string; limit?: number; overview?: boolean } = {},
): Promise<MicroAppDocument> {
  const search = new URLSearchParams();
  if (params.collection) search.set("collection", params.collection);
  if (params.cursor) search.set("cursor", params.cursor);
  if (params.limit) search.set("limit", String(params.limit));
  if (params.overview === false) search.set("overview", "false");
  const qs = search.toString();
  return req(`${BASE}/${assetId}/document${qs ? `?${qs}` : ""}`);
}

export function getMicroAppAccess(assetId: string): Promise<MicroAppAccess> {
  return req(`${BASE}/${assetId}/access`);
}

/** Sets one person's or project's direct grants to exactly these roles and permissions. */
export function setMicroAppAccess(assetId: string, change: MicroAppAccessChange): Promise<MicroAppAccessResult> {
  return putJson(`${BASE}/${assetId}/access`, change);
}
