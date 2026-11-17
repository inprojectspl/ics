# Micro-applications API

A micro-application has two APIs. The **management API** on the ICS host builds, publishes, runs and hands out apps; agents call it through [ics-mcp](https://github.com/inprojectspl/ics-mcp). The **app API** on the app's own origin is what the app's page calls for its data. Both exist only when micro-applications are enabled (`microapps_disabled` otherwise, see [Deploying ICS](DEPLOY.md#micro-applications-optional)).

The authoritative description of the package format is the contract that ICS serves, `GET /api/micro-applications/contract`: the manifest JSON Schema (`ics.microapp/v1alpha1`), the handler SDK types, the browser SDK, a working template, the limits, the errors and this API, in sections under one `contract_hash`. This page is the overview; the user side is in the [user guide](guide/micro-applications.md) and the reasons behind the design in [ADR-0027](decisions/0027-micro-applications.md).

## Who may do what

| Right | Who has it |
|---|---|
| use the app (`app.use`) | an active internal account that can currently see the asset, or a visitor of a share link that names app roles |
| publish (`app.publish`) | the owner of the asset or of its home project, or an explicit grant; an editor may plan but not apply |
| run (`app.control`) | the same as publish, or an explicit `app.control` grant |
| manage access (`app.access.manage`) | the owner of the asset or of its home project |

What a person may do inside the app comes only from the app's own permissions, given one by one or through the app's roles (`role:<name>`). No ICS role implies them, not even ownership. A role means what the active release defines, so a release that changes a role changes what its holders may do.

Plan and apply need programmatic authentication: an OAuth bearer token (ics-mcp). Personal access tokens are read-only and are refused with `insufficient_scope`.

## Management API

Paths are relative to the ICS host. Errors have the usual shape `{detail, code, field?}`; package problems also carry `file`, `pointer` (a JSON Pointer into `microapp.json`) and `diagnostics[]`. The codes are in [API errors](api-errors.md).

| Purpose | Request |
|---|---|
| Contract | `GET /api/micro-applications/contract?section=&part=` |
| Plan | `POST /api/micro-applications/plans` |
| Apply | `POST /api/micro-applications/plans/{plan_id}/apply` |
| Operation | `GET /api/micro-applications/operations/{operation_id}` |
| List apps | `GET /api/micro-applications?q=&state=&offset=&limit=` |
| App status | `GET /api/micro-applications/{asset_id}` |
| Control | `POST /api/micro-applications/{asset_id}/control` |
| Logs | `GET /api/micro-applications/{asset_id}/logs?cursor=&limit=` |
| Package files | `GET /api/micro-applications/{asset_id}/package?version=&path=` (publishers) |
| Releases | `GET /api/micro-applications/{asset_id}/releases` |
| Access | `GET` and `PUT /api/micro-applications/{asset_id}/access` |
| Document view | `GET /api/micro-applications/{asset_id}/document?collection=&cursor=&lines=` |
| Versions and compare | `GET /api/assets/{asset_id}/versions`, `GET /api/assets/{asset_id}/versions/{from}/diff/{to}?path=` (publishers) |

### Plan

```http
POST /api/micro-applications/plans
{"files": [{"path": "microapp.json", "content_text": "..."}, {"path": "public/logo.png", "content_base64": "..."}],
 "asset_id": null, "project_id": "<uuid or null>", "change_note": "First release"}
```

A plan checks a complete package against the contract without touching the running app and binds it to a digest. `asset_id` updates an existing app; without it the plan creates one, in `project_id` when given. `change_note` (up to 500 characters) becomes the note of the package version.

The answer either lists `problems` (each with `file`, `pointer` and `code`) or describes the release:

- `plan_id`, `release_digest`, `expected_generation`: what apply needs; a plan expires after an hour;
- `app_changes`: what changes for the people using the app (roles, permissions, endpoints, capabilities, collections), against the running release or, for a new app, everything it brings;
- `database`: the schema versions and the migration; v1 accepts additive changes only (`destructive_change` otherwise);
- `seed_rows`: how many starting records each new collection gets;
- `permissions_required`: what the caller needs to apply.

Plans count against the caller's storage quota and are limited to 60 per 10 minutes per person.

### Apply and operations

```http
POST /api/micro-applications/plans/{plan_id}/apply
{"digest": "<release_digest>", "expected_generation": 3, "idempotency_key": "release-2026-11-16-a"}
```

Apply answers `202` with an `operation_id` and publishes exactly the planned package: a new package version, the database migration and seed rows in the app's schema, then the release becomes active. The same `idempotency_key` returns the same operation; a different request under it is `idempotency_key_reused`. A stale `expected_generation` is `generation_conflict`, a changed package `digest_mismatch`, an old plan `plan_expired`.

`GET .../operations/{operation_id}` reports `pending`, `running`, `succeeded` or `failed`, with the step it reached. A failed publication never leaves a half-applied release; a new app whose first publication fails is moved to the trash.

### Control

```http
POST /api/micro-applications/{asset_id}/control
{"action": "suspend", "expected_generation": 4, "idempotency_key": "ops-suspend-01"}
```

| Action | Effect |
|---|---|
| `enable` | the app accepts requests again; it stays asleep until a real request |
| `suspend` | new requests get `503 app_suspended` at once, running ones are finished; the operation ends after a confirmed drain |
| `sleep` | frees pools, caches and runner leases now; no state change |
| `restart` | drains and recycles the runner processes; never lifts a suspension |

No action deletes data. Every action is audited and appears in the app's logs.

### Access

`GET .../access` lists the app's roles with their permissions and what each permission unlocks, and who holds which roles, people and projects. `PUT` sets exactly the given roles and single permissions for one person or project:

```http
PUT /api/micro-applications/{asset_id}/access
{"user_email": "priya.shah@example.com", "roles": ["employee"], "permissions": [], "can_open": true}
```

`can_open: true` also shares the asset with the person as a viewer, so they can open the app; `can_open: false` removes that viewer share. Empty `roles` and `permissions` take away all of the person's permissions in the app. A project's roles reach every accepted member alike. Share links name app roles or permissions in `app_roles` and `app_permissions` (`POST /api/assets/{id}/shares`); a public link opens the app without sign-in.

### Document view

`GET .../document` runs the app's declared document endpoint as the caller and returns `{markdown, html, app_view, collections}`: the app's own rendering of its content with the caller's records, then the roles, the data model and the records of each collection the caller may read, paged with `collection` and `cursor`. It is the same content the Data tab shows and `ics_asset_read` returns.

## App API

Every app runs on its own origin, `https://<name>.<ICS_MICROAPPS_APP_HOST_SUFFIX>/`, served by the shared broker. `name` is 8 random characters (`a-z` without `i`, `l`, `o`, digits `2-9`) drawn when the app is created and never changed or given to another app; `app_url` in the API answers carries it. The long `https://a-<asset id hex>-prod.<suffix>/` of earlier releases still serves the same app, with a session of its own ([ADR-0028](decisions/0028-short-micro-application-hosts.md)). The app's page loads the browser SDK from `/__ics/sdk.js`, which handles the sign-in through ICS (a one-time code exchanged for a host-bound app session) and adds the headers below. Apps should use the SDK; the raw HTTP API is listed for completeness.

| Request | Purpose |
|---|---|
| `GET /api/v1/session` | the person, the app and its release, the person's permissions and roles, the CSRF token |
| `GET /api/v1/schema` | the collections and fields the person may use |
| `GET /api/v1/openapi.json` | an OpenAPI description of the app's API for this person |
| `GET /api/v1/collections/{name}?limit=&cursor=&sort=&filters=` | list records the person may read |
| `GET /api/v1/collections/{name}/{id}` | one record, with an `ETag` of its revision |
| `POST /api/v1/collections/{name}` | create a record |
| `PATCH /api/v1/collections/{name}/{id}` | change a record |
| `DELETE /api/v1/collections/{name}/{id}` | delete a record |
| `/api/v1/custom/...` | the app's own endpoints, run as JavaScript handlers |

Every generic operation is allowed only by the permission the manifest names for it, and a row scope (`own` or `all`) limits which records it reaches. Writes require:

| Header | When |
|---|---|
| `Origin` equal to the app's origin and `X-ICS-CSRF` | every write |
| `X-ICS-Data-Generation` | every write; a mismatch after a data restore is `409 data_generation_changed` |
| `X-ICS-Release` | writes; a newer active release is `409 release_changed`, reload the page |
| `Idempotency-Key` | `POST` and `DELETE`, and custom endpoints that declare it; a repeated key replays the first answer |
| `If-Match` | `PATCH` and `DELETE`, and custom endpoints that declare it; a stale revision is `412 revision_mismatch` |

Notable answers: `401 app_session_required` (open the app through ICS), `403 forbidden` or `csrf_failed`, `422 validation_failed` with a JSON Pointer, `429 rate_limited` with `Retry-After`, `507 app_data_quota_exceeded` (the owner's data limit is full; reads and deletes still work), `503 app_suspended`, `504 execution_deadline` or `commit_unknown` (retry with the same `Idempotency-Key`).

## Limits

| Limit | Value |
|---|---|
| Files in a package | 50 |
| Package size | 5 MiB |
| One handler | 256 KiB |
| Collections | 20, with up to 40 fields and 8 indexes each |
| Custom endpoints | 30 |
| JSON field | 64 KiB |
| String field | 100,000 characters |
| Handler run | 5 s wall time, 250 ms of JavaScript CPU, 32 MiB heap, 20 database calls, 256 KiB response |
| Idle time before sleep | 60 to 3600 s, set by the app |
| Data of all apps of one owner | 100 MB by default, set per user by an administrator |
| Requests | 20 per second per person and app, 100 per second per share link, by default |

The values for a server are in the `limits` section of the contract.
