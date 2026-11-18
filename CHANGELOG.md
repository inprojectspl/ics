# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- First public release.
- Archive and trash of documents ([ADR-0029](docs/decisions/0029-asset-archive-and-trash.md)).
  An archived document leaves lists, search and project upkeep but still opens by link, share and
  slug: **Move to archive** in the `…` menu, **Archive** in the sidebar and in **Filters**, a
  banner in the reader, `POST`/`DELETE /api/assets/{id}/archive`, `archive=` on `/api/assets/index`,
  `/api/assets/search-mcp` and `/api/projects/{slug}`. A deleted document goes to the trash for
  `ICS_TRASH_RETENTION_DAYS` (30): **Trash** in the sidebar and the project's `…` menu, **Restore**,
  **Delete forever** and **Empty trash**, undo from the toast; `GET /api/assets/trash`,
  `POST /api/assets/{id}/purge`, `POST /api/assets/trash/purge`. The hourly `purge_trash` job then
  deletes the document with its files. Migration `0052` adds `archived_at`, `archived_by`,
  `deleted_by` and `purge_at`; documents already deleted get the full period from the upgrade.
  The project owner may now restore a project document from the trash, and a restore needs room in
  the owner's quota.
- Documentation site at <https://inprojectspl.github.io/ics/>, built with MkDocs from `docs/`.
- `GET /api/assets/by-id/{id}/meta`: the asset meta by id for any viewer, as
  `/by-slug/{slug}/meta` (`/api/assets/{id}` answers editors only).
- `format=markdown` on an agent read of a Markdown file (`file-mcp`, `agent-view`, share
  `resolve`) drops its HTML comments, so machine markers such as transcript timestamps do not
  cost tokens; comments in code stay and every line keeps its number.
- HTML JSON publications accept a scoped idempotency key and keep a durable receipt (`GET
  /api/assets/publications/{id}`), so a retry after a lost response returns the original result
  instead of a second document (migration 0046, docs/publication-receipts-api.md).
- Version writes can reject stale edits. Asset write endpoints accept an optional
  `expected_version`; a mismatch returns `409 version_conflict` before any file is staged, and calls
  without it behave as before (docs/expected-version-api.md).
- A version replacement accepts the same publication identity: its receipt is saved with the version
  and a retry after a lost acknowledgement returns the original result. A keyed replacement requires
  `expected_version`; a different payload under the same key is refused.
- GitLab bindings accept a signed `release_id` with `release_generation`. The result, the version
  and the generation commit together, so retrying the same signed release after a lost response
  returns the original result; an older generation under a new ID is refused with
  `release_generation_conflict`, and once a binding has a release a manifest without one gets
  `release_required` (migration 0047). `ics-sync` does not send these fields yet.
- Micro-applications (PoC, `ICS_MICROAPPS_ENABLED`): the `micro_application` asset kind, a
  validated `ics.microapp/v1alpha1` manifest, plan/apply with durable, idempotent publication
  operations, a schema and runtime role per app in a separate `ics_apps` database, generic CRUD
  and JavaScript handlers run by a shared Node.js broker with two QuickJS/WASM runners
  (`microapp-runtime/`), and a per-app origin and session. Apps are ordinary assets in the
  panel (status, control, data, access and logs on the asset page; no upload). An app
  declares a document view (a read-only endpoint that renders its content with the records
  as Markdown, run as the reader) and seed rows for the collections a release creates; the
  agent read of an app starts with that view. Publishers compare package versions like any
  asset's (Versions in the menu, `/v/<slug>/diff`), with each version's release state and
  `app_changes` saying what changed for the people using the app; plans show the same against
  the running release, count against the storage quota and take a `change_note`. The broker
  checks seed rows and the values a manifest states for fields with the rules of the app's
  own API. Watchers hear of an app once its first release runs; one whose first publication
  fails goes to the trash. Deleting an app removes the roles people hold in it. A rename or a
  hand-written summary survives later releases. Generic content, version, restore, sync,
  download and read paths refuse the kind; relations point at an app as a whole. Local
  profile: `scripts/microapps-local.sh` and `docs/development/microapps-local.md`.
- `seed-user` CLI command for local profiles.
- The user guide covers micro-applications (opening and running an app, its data, roles, sharing,
  versions and data limit, with screenshots) and safe retries for agents; `docs/microapps-api.md`
  describes the management and app APIs and ADR-0027 the design.
- Race Track, a third example micro-application: a 3D race built with Three.js, with results checked
  by a handler, a board of the fastest drivers, a judge role and a document view of the board.

### Changed

- A micro-application handler gets 1000 ms of JavaScript CPU instead of 250 ms, and a spent budget
  answers `504 cpu_budget` instead of `504 execution_deadline`, so the panel shows which limit
  stopped the handler.
- An administrator's **Trash** shows their own and their projects' documents, like everyone's; the
  **Whole organisation** switch (`scope=admin:trash`) shows every user's, and **Empty trash** there
  (`everyone: true`) is the only way to purge other people's documents in bulk.
- An older version of a document is an "earlier version" in the web app ("archived" now means the
  archive of documents), and **Delete** in the `…` menu reads **Move to trash**.
- `format=markdown` on a file that is neither HTML nor Markdown answers `format_unsupported`
  instead of `html_only`.
- The example micro-applications (`examples/microapps`) and the template agents start from are in
  English and use the ICS palette: a header, cards, status badges, empty states and light and dark
  themes that follow the system setting.
- Micro-applications run on short addresses, `https://<name>.<ICS_MICROAPPS_APP_HOST_SUFFIX>/`
  with an 8-character random name drawn once per app and never given to another app, even after
  the app is purged (migration 0051, ADR-0028). The API, the panel and share links use it; the
  long `a-<asset id hex>-prod` host and configured aliases keep serving the same app. The browser
  treats the short host as a new site: people sign in to the app again, and a share-link guest
  gets a new anonymous identity there (the old host keeps the old one).

### Security

- The session cookie is `__Host-ics-session` (plain-HTTP debug setups: `ics-session`). The
  prefix stops a sibling subdomain, such as an HTML bundle on the viewer host, from setting a
  session of its own for ICS (cookie tossing) and signing the visitor into another account.
  Everyone signs in again once after the upgrade.
- KaTeX 0.18.11 and mermaid 12.2.0 replace versions with a published advisory (prototype pollution
  bypassing KaTeX trust restrictions); both share one copy of KaTeX.
- Locking an account and an admin's **Revoke all tokens** also sign out the person's AI assistants
  connected through ics-mcp: their OAuth tokens are revoked, so they no longer work again once a
  lock ends.
- Access to an HTML bundle in the isolated viewer ends with what granted it: every page re-checks
  the share link (revoked or expired) or the reader's role and account, so an earlier cookie no
  longer opens the bundle, nor a version published after the link was revoked. The files a page
  loads trust that check for 10 seconds. Each document keeps its own one-hour expiry; opening
  another one does not extend it.
- `POST /api/assets/{id}/undelete` on a document that is not deleted answers `404` to anyone
  but its owner, instead of returning its slug.
- An HTML bundle created through `POST /api/assets/html-json`, as MCP does, counts against the
  owner's total storage quota like every other upload.
- An OAuth token, as used by MCP clients, never carries administrator rights, like a personal
  access token: an admin's agent sees what an ordinary user would and `/api/admin/*` refuses it.
  Administration stays in the browser.
- A refresh token or authorization code used by two requests at once is consumed once: the
  second request waits for the first and is refused, so one refresh no longer yields two live
  successors.
- Revoking a refresh token works without `token_type_hint` or with a wrong one, and ends the
  grant: the token's rotation family and the access tokens issued with it stop working at once.
  Reuse of a rotated refresh token cuts the access tokens of its family too.
- The loopback redirect of the built-in stdio client is checked as a parsed URL, so only the
  port may vary: `http://127.0.0.1:1@other.host/callback` no longer sends the authorization code
  to another host. Dynamic clients register only HTTPS, loopback HTTP or app-scheme callbacks, and the
  consent page shows where the browser goes after consent.
- A single Markdown upload or a new version of one stores the file under its base name, so a
  name with directory segments cannot write into another document.
- Bundle files served on the app origin (the legacy `/static/` links of documents and shares)
  are sandboxed and cannot call the API with the visitor's session.
- joserfc 1.7.6 replaces 1.7.5 (CVE-2026-119284); only the lockfile changes, authentication code is
  untouched.
- dnspython 2.9.2 (CVE-2026-128089) and soupsieve 4.1.1 (CVE-2026-126190 to CVE-2026-126193) replace
  versions with a published advisory.

### Fixed

- A micro-application request stopped by its deadline counted twice towards the circuit breaker,
  so two failed requests already blocked the app for 30 seconds. A restart, enable or policy change
  from ICS now also closes the breaker.
- Signing in from a link to a page that needs an account (a project, the graph, notifications)
  returns to that page, also with Google; a document link keeps its file and version.
- OAuth clients can discover the authorization server at the issuer's root; the existing
  discovery URLs under `/api/auth/oauth/` remain supported. Deployments must also forward the
  root discovery paths through their reverse proxy.
- Connecting an MCP client from a signed-out browser resumes the original consent request
  after Google or password sign-in. Google return paths are validated and bound to a single
  OIDC transaction.
- OAuth consent responses preserve the exact client `state`, including reserved characters,
  after either allowing or denying access.
- The agent context pack no longer fails with a server error on a `supersedes` chain of three
  or more documents; the whole chain collapses into its newest visible document.
- Restoring version 1 on S3 or R2 storage no longer copies the files of versions 10 to 19.
- The collection reader shows the last file clicked even when answers arrive out of order, and
  back/forward show the file the address names.
- A new version of a bundle or a collection keeps the `entry_path` the caller names; it was
  ignored and ICS picked `index.html` or `README.md` instead.
- An older GitLab sync that was still uploading when a newer one landed no longer publishes
  over it: the order check is repeated under a lock on the binding.
- The sign-in page retries loading its configuration, so Google sign-in no longer disappears
  until a reload when the page opened while the server was restarting.
- PS node references include the project. The same document can link to the same local node ID in
  two PS projects; context packs and rekey stay scoped to the selected project. Repeating a link
  within one project still returns `409 external_ref_exists`, also with changed required or
  pinned-version parameters, and two racing retries get that conflict instead of a server error.
  Migration 0045 keeps existing links, turns empty scopes into null and leaves unknown legacy scopes
  unresolved; its downgrade refuses cross-project collisions instead of dropping links. OpenProject
  work packages keep their single-instance identity.
- Concurrent Markdown edits use the locked version. Edit, add, delete and move recheck the files
  under the version lock, and sizes and quota growth use the tree actually staged. A failed write
  leaves the current version and its history intact.
- The backend test runner waits for PostgreSQL over TCP, so the temporary Unix-socket-only server of
  the image initialization no longer starts tests before the final database is ready.
- An app's data summary says "1 table" and "1 row" instead of "1 tables", in English and Polish.

