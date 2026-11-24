# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- First public release.
- Google Sheets links per spreadsheet file ([ADR-0033](docs/decisions/0033-google-sheets-file-links.md)).
  A micro-application links one spreadsheet file with a mapping per collection: one tab, several
  tabs of one kind of record (a tab per month, state or team, matched by a `key_field` unique across
  them, new records going to the `append_to` tab, an optional `tab_field` keeping the row's tab name
  on the record) or a list the app only reads (every column owned by the sheet: nothing is written
  to its tabs). Tabs are tracked by Google's tab id, so renaming one keeps the link; a row moved by
  hand between tabs of a group stays the same record. One sync covers the whole file: one read of
  the linked tabs, one broker transaction for every collection (read in one snapshot), one atomic
  `batchUpdate` for every tab. New rows leave the sheet's own columns empty when the app has no
  value, so formulas there stay. Inspect lists every tab with its id and headers, suggests groups of
  tabs with the same headers and marks formula columns. The panel shows each collection with its
  tabs and names the collection, tab and row of every change. Migration `0056` turns each link into
  one single-tab mapping and keeps what was agreed.
- Live updates and channels of micro-applications ([ADR-0032](docs/decisions/0032-micro-application-realtime.md)).
  An open app page keeps one WebSocket to the broker (`/__ics/realtime`): `ics.collection(name).watch(cb)`
  hears when a collection it may list changed (any committed write, a Google Sheets sync included),
  and `ics.realtime.channel("<name>/<room>")` carries the app's own messages and presence between
  pages, declared in the manifest under `realtime.channels` with a permission. Redis pub/sub fans
  out between brokers; limits on message size (64 KB by default, at most 128 KB), rate, sockets and
  subscriptions. The broker reports open pages and changed collections; the App tab shows how many
  people have the app open, and Google Sheets automatic sync follows that activity on its own
  worker (`sheets-worker`): a sleeping app does not sync. Example `examples/microapps/stars`.
- Google Sheets links of micro-applications ([ADR-0031](docs/decisions/0031-google-sheets-links.md),
  docs/guide/micro-applications.md). An agent builds an app around an existing spreadsheet
  through ICS-MCP: `POST /api/integrations/google/inspect` reads its headers and proposes field
  names and types, and the agent links the collection to the tab; nobody fills in a form or
  changes the sheet. The sheet carries no ids: rows match records by an optional unique
  `key_field` or by content and the row last seen, so sorting and inserting rows is fine.
  One collection of an app syncs with one tab of a spreadsheet
  on request: **Preview** compares the app, the sheet and the values agreed at the last sync,
  conflicts are decided by a person, **Apply** changes the app's records in one broker transaction
  (once per operation, whatever the retries) and writes the sheet in one atomic `batchUpdate`; a
  lost Google answer stays `uncertain` until **Check result** reads the cells back. Columns are
  owned by the sheet, the app or both; rows matching no record become records, records without a
  row are appended, deletions are never inferred. A sync handles up to the app owner's
  `sheet_max_rows` (5000 by default, set per user by an administrator, capped by
  `ICS_GOOGLE_SHEETS_MAX_ROWS`). Each person connects their own Google account
  (`/api/integrations/google`, encrypted refresh token, bound to the ICS session); a link writes
  with the owner's account or each person's own, and a person without access to the file can ask
  the owner through a `sheets.access_requested` notification. With `auto_sync` (the agent's
  default) ICS syncs on its own as the owner: app changes reach the sheet within seconds, sheet
  edits come in every `ICS_GOOGLE_SHEETS_POLL_SECONDS` (120); conflicts and errors wait for a
  person and notify the owner (`sheets.auto_sync_stopped`). API under
  `/api/micro-applications/{id}/sheets`, broker `sheets/read` and `sheets/apply`, migration `0055`,
  `ICS_GOOGLE_SHEETS_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` / `_MAX_ROWS`.
- Copyable addresses of HTML bundles and micro-applications opened through a share link
  ([ADR-0030](docs/decisions/0030-copyable-share-addresses.md), docs/copyable-addresses.md). The
  page address keeps the link as `ics_share=<token>` across pages, `history.pushState`, GET forms
  and anchors; a recipient of the copied address passes that link's gate and lands on the same
  page, query and fragment. ICS and the broker inject `share_context.js` into served pages (no
  UI, no requests), serve an entry page instead of a page without a session, and carry the page
  through `html-grant` (`share`, `to`), `/api/share/{token}/launch` (`to`) and the `/s/{token}?to=`
  share page. `ICS_SHARE_CONTEXT_ENABLED=false` stops the injection only.
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
- Project invitations reach the app, not only the e-mail: the invitee gets a `project.invited`
  notification that opens the invitation screen of the e-mail link, now usable without its token,
  with **Accept invitation** and **Decline**. `GET`/`POST`/`DELETE /api/projects/{slug}/invitation`
  read, accept or decline the caller's own invitation (audit `project_invite_declined`).
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

- A Google Sheets record is no longer appended twice: a second sync could plan the same new rows
  while the sheet write of an earlier one was not yet done or confirmed. A sync whose sheet write is
  pending or uncertain now blocks the next one (`sheet_sync_unsettled`) until it is checked; the
  automatic sync settles its own first.
- A micro-application's list rule no longer leaks fields its `readFields` hide: `sort` and
  `filters` of `GET /api/v1/collections/{name}` (and `data.list` in handlers) accept only readable
  fields, so neither the order nor the cursor, which carries the last sort value, reveals a hidden
  one. Without `sort` the list keeps the newest first, or uses the id order when `created_at` is
  hidden.
- Purging the trash no longer deletes the files of a document restored at the same moment: the
  purge locks and checks its rows again, deletes them in one commit with their storage prefixes
  queued in `storage_cleanup` (migration `0053`), and removes the files after it; the
  `sweep_storage_cleanup` job retries what a crash or a storage error left. Deleting an account now
  deletes the files of its documents and app plans, which used to stay on disk with nothing
  pointing at them.
- A database error while writing a version no longer deletes the version files: the transaction may
  already be rolled back, its lock released and the same version written by someone else. The next
  writer clears what an unfinished attempt left. A micro-application version commits outside that
  cleanup as well.
- Two concurrent writes of one owner can no longer both pass the storage quota: a last check right
  before the commit locks the owner's row, so the lock lasts only for the commit.
- Two `part_of` or `supersedes` relations added at the same time can no longer close a cycle.
- A Markdown or document text whose search vector would pass PostgreSQL's 1 MiB tsvector limit no
  longer fails the upload: the longest prefix that fits is indexed and the text is kept whole
  (migration `0054`).
- The relation graph of a document with tens of thousands of backlinks no longer fails on the
  driver's 32,767 parameter limit.
- The project map keeps Project Standard tasks with the same node id in different projects apart.
- Rate limits and the audit log saw the reverse proxy's address for every client, so all users
  shared one bucket (password reset, OAuth registration and tokens). The backend now trusts
  `X-Forwarded-For` from private networks (`ICS_FORWARDED_ALLOW_IPS`).
- The rendered Markdown cache has a Redis of its own (`redis-cache`, `ICS_RENDER_CACHE_REDIS_URL`)
  with a memory cap and LRU eviction, so it cannot use up the memory of sessions and queues.
- The S3 storage keeps one client and its connection pool per process instead of opening a new
  one for every operation.
- A micro-application warming up a runner no longer takes both runner slots, and connections
  still handshaking count against the broker's PostgreSQL budget.

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

