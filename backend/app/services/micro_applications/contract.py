"""The agent contract: everything needed to build a package without guessing.
Served in sections that share one `contract_hash`, so a client can fetch
pieces under a response size cap and still know they belong together."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.micro_applications import manifest
from app.services.micro_applications.common import canonical_hash

SDK_TYPES = """\
// js-capabilities-v1 SDK available to handlers (handlers/*.mjs, default export).
type Json = null | boolean | number | string | Json[] | { [k: string]: Json };
type CallOptions = { capability: string };
type GetOptions = CallOptions & { forUpdate?: boolean }; // row lock, transaction=required only
type WriteOptions = CallOptions & { ifRevision: number };
type Filter = { field: string; op: "eq" | "in" | "lt" | "lte" | "gt" | "gte"; value: Json };
type Input = { params: Record<string, string>; query: Record<string, Json>; body: Json };
interface Context {
  // The caller's app permissions and roles: leave out what they cannot see
  // (a document view); every data call is checked against them anyway.
  readonly actor: { id: string; permissions: string[]; roles: string[] };
  readonly app: { id: string; environment: string; release: string; dataGeneration: number };
  readonly request: { id: string; deadline: string; preconditions: { revision: number | null } };
  db: {
    get(collection: string, id: string, options: GetOptions): Promise<Record<string, Json> | null>;
    list(collection: string, query: { filters?: Filter[]; limit?: number; cursor?: string; sort?: string },
         options: CallOptions): Promise<{ items: Record<string, Json>[]; nextCursor?: string }>;
    insert(collection: string, data: Record<string, Json>, options: CallOptions): Promise<Record<string, Json>>;
    update(collection: string, id: string, patch: Record<string, Json>, options: WriteOptions): Promise<Record<string, Json>>;
    delete(collection: string, id: string, options: WriteOptions): Promise<void>;
    count(collection: string, filters: Filter[], options: CallOptions): Promise<number>;
    groupCount(collection: string, field: string, filters: Filter[], options: CallOptions):
      Promise<Array<{ value: Json; count: number }>>;
  };
  errors: {
    notFound(): Error;                // 404
    forbidden(code: string): Error;   // 403
    conflict(code: string): Error;    // 409
    invalid(code: string): Error;     // 422
  };
  log(level: "info" | "warn" | "error", message: string, fields?: Record<string, Json>): void;
}
type Handler = (input: Input, ctx: Context) => Promise<{ status: number; body: Json }>;
// Data calls run in the request's one transaction, in call order. Every rule of
// the named capability (permission, rowScope, fields, conditions) is enforced
// by the broker; a write without the right revision fails with 412.
// Not available: process, require, import, fetch, timers, files, sockets, eval.
"""

BROWSER_SDK = """\
// <script src="/__ics/sdk.js"></script> on every app origin provides window.ics:
ics.session()                              -> { user, app: { release, dataGeneration }, permissions, roles, csrfToken }
// roles: the app roles the person holds (from the manifest's "roles"); show
// a reviewer's screens on roles, enforce with permissions (the broker does).
// Hide what the person may not do instead of letting it fail with 403:
//   form.hidden = !s.permissions.includes("requests.create");
// and keep `[hidden] { display: none !important; }` in the CSS, or a
// `display` rule shows the hidden element again.
ics.collection(name).list({ limit, cursor, sort, <field>: value })
ics.collection(name).get(id)
ics.collection(name).create(data)          // adds Idempotency-Key
ics.collection(name).update(id, revision, patch)
ics.collection(name).remove(id, revision)  // adds Idempotency-Key
ics.call(method, "/v1/custom/...", { body, query, ifMatch, idempotencyKey })
// Errors: ics.IcsApiError { status, code, field, body }. 409 release_changed or
// data_generation_changed means: reload the page.
"""

PROCEDURE = [
    "Check that the idea fits before building: ics_help('micro-applications'), section "
    "'What fits and what does not' (no network, e-mail, scheduled jobs, file uploads, "
    "joins or full-text search; own logic in handlers within the limits section).",
    "Read this contract (all sections share contract_hash).",
    "Write microapp.json, public/ (static UI, no inline scripts: CSP script-src 'self') "
    "and handlers/*.mjs only where CRUD is not enough.",
    "Start public/app.css from the template's: it carries the ICS palette (light and dark "
    "follow the system) and the classes for the header, cards, forms, buttons, lists, "
    "badges and empty states, so the app looks like part of ICS.",
    "Keep the app's content in its collections, not in public/ files: data that exists at "
    "the start (e.g. the items of a document turned into an app) goes to "
    "seed/<collection>.json, a JSON array of records (the collection's fields, optionally id "
    "and created_at to keep an imported record's identity and date) inserted once, when a "
    "release creates the collection. Plan the collections up front: rows cannot be seeded "
    "into a collection that already exists.",
    'Always declare a document view ("document": {"endpoint": "<name>"}): a GET, read_only '
    'endpoint without path parameters returning {"markdown": string}. It renders the app\'s '
    "content as people see it, records filled in (each item with its comments, totals, "
    "states). ICS runs it as the reader; ics_asset_read returns it first, so this is how "
    "agents and people read the app. The template has one.",
    "Call ics_microapp_plan with the complete package and a one-sentence change_note; fix "
    "diagnostics by file/pointer/code. Tell the user its app_changes (what the release "
    "changes for the people using the app) before applying.",
    "Call ics_microapp_apply with plan_id, release_digest, expected_generation and a "
    "stable idempotency_key; after a lost response repeat it with the same key.",
    "Poll ics_microapp_status(operation_id) until terminal; then open app_url.",
    'In microapp.json declare every permission with a name people understand ("permissions": '
    '{"requests.approve": {"label": ...}}) and the roles of the kinds of people who use the '
    'app ("roles": {"reviewer": {"label": ..., "permissions": [...]}}); every permission '
    "belongs to at least one role, and access is given by role.",
    "Give people access with ics_microapp_access_set(asset_id, user_email | project_id, "
    "roles=[...]): one call lets the person open the app and sets exactly these roles "
    "(permissions=[...] adds single permissions beside them). ICS roles (viewer, editor, "
    "owner) decide what a person does with the asset, never in the app: none implies app "
    "roles, not even ownership (the owner sets their own). A project's app roles reach "
    "every accepted member alike, whatever their project role; give different roles to "
    "people directly. ics_microapp_access(asset_id) shows the roles and what each "
    "permission unlocks.",
    "For people without an account use ics_share_create_link(app_roles=[...]): "
    "a public link opens the app without sign-in, other modes keep their gate.",
]

ERRORS = {
    "format": "{code, detail, field, request_id, retryable?}; field is a JSON Pointer",
    "management": {
        "manifest_invalid": "422, diagnostics[] with file/pointer/code",
        "destructive_change": "422, v1 accepts additive model changes only",
        "schema_incompatible": "422, compatibility range or transitional release needed",
        "programmatic_auth_required": "403, plan/apply need a bearer token or PAT",
        "publish_permission_required": "403, app.publish needed for apply",
        "digest_mismatch": "409",
        "plan_expired": "409",
        "generation_conflict": "409",
        "idempotency_key_reused": "409, same key with a different request",
        "microapp_requires_agent_api": "409, generic upload/edit routes refuse micro-applications",
    },
    "runtime": {
        "401 app_session_required": "open the app through ICS",
        "403 forbidden / csrf_failed": "missing permission or cross-origin write",
        "404 not_found": "missing or invisible record",
        "409 release_changed / data_generation_changed / invalid_state": "state conflicts",
        "412 revision_mismatch": "If-Match is stale",
        "428 precondition_required": "header missing",
        "422 validation_failed": "field error with JSON Pointer",
        "429 rate_limited": "Retry-After",
        "507 app_data_quota_exceeded": "owner's data limit is full; reads and deletes still work",
        "503 app_suspended / capacity_exhausted": "",
        "504 execution_deadline / commit_unknown": "retry with the same Idempotency-Key",
    },
}

MANAGEMENT_API = {
    "contract": "GET /api/micro-applications/contract?section=",
    "plan": "POST /api/micro-applications/plans {files[{path, content_text|content_base64}], "
    "asset_id?, project_id?, change_note?} -> app_changes, migration, seed_rows",
    "apply": "POST /api/micro-applications/plans/{plan_id}/apply {digest, expected_generation, idempotency_key} -> 202",
    "operation": "GET /api/micro-applications/operations/{operation_id}",
    "list": "GET /api/micro-applications?q=&state=&offset=&limit=",
    "status": "GET /api/micro-applications/{asset_id}",
    "control": "POST /api/micro-applications/{asset_id}/control {action, expected_generation, idempotency_key}",
    "logs": "GET /api/micro-applications/{asset_id}/logs?cursor=&limit=",
    "package": "GET /api/micro-applications/{asset_id}/package?version=&path= (app.publish)",
    "releases": "GET /api/micro-applications/{asset_id}/releases: package versions and their state",
    "compare": "GET /api/assets/{asset_id}/versions/{from}/diff/{to}?path= (app.publish) -> "
    "files[] and app_changes[] (roles, permissions, endpoints, capabilities, collections)",
    "access": "GET /api/micro-applications/{asset_id}/access; PUT the same path "
    "{user_email | project_id, roles[], permissions[], can_open?} sets exactly these "
    "roles and permissions",
    "document": "GET /api/micro-applications/{asset_id}/document?collection=&cursor=&lines= -> "
    "{markdown, html, app_view, collections}: the document view as the reader, then roles, "
    "model and records",
    "app_api": "on the app origin: /api/v1/session, /api/v1/schema, /api/v1/openapi.json, "
    "/api/v1/collections/{name}[/{id}], /api/v1/custom/...",
}

SECTIONS = (
    "manifest_schema",
    "sdk_types",
    "browser_sdk",
    "template",
    "limits",
    "errors",
    "management_api",
    "procedure",
)


@lru_cache
def _template() -> dict[str, str]:
    root = Path(__file__).with_name("template")
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*")) if p.is_file()}


def build(settings: Settings) -> dict[str, Any]:
    sections: dict[str, Any] = {
        "manifest_schema": manifest.manifest_schema(),
        "sdk_types": SDK_TYPES,
        "browser_sdk": BROWSER_SDK,
        "template": {"files": [{"path": k, "content_text": v} for k, v in _template().items()]},
        "limits": manifest.LIMITS,
        "errors": ERRORS,
        "management_api": MANAGEMENT_API,
        "procedure": PROCEDURE,
    }
    return {
        "contract_version": manifest.CONTRACT_VERSION,
        "profile": manifest.PROFILE,
        "sdk_version": manifest.SDK_VERSION,
        "validator_version": manifest.VALIDATOR_VERSION,
        "app_url_pattern": f"{settings.microapps_app_scheme}://a-<asset id hex>-prod."
        f"{settings.microapps_app_host_suffix}/",
        "contract_hash": "sha256:" + canonical_hash(sections),
        "sections": sections,
    }
