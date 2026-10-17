# ADR-0023: Notifications: watches in PostgreSQL, inbox in Redis, four delivery channels

**Status:** Accepted, implemented 2026-09-28.
**Decision owners:** Owner.
**Scope:** `backend/app/services/notifications/` (extended, the binding sync
dispatcher stays), `backend/app/jobs/tasks/notify.py`,
`backend/app/routes/notifications/`, watch endpoints under
`/api/assets/{slug}/watch` and `/api/projects/{slug}/watch`, tables
`watches`, `notification_preferences`, `push_subscriptions` (migration 0043),
`frontend/src/components/Notifications/`, `frontend/src/views/Notifications.tsx`,
`frontend/src/views/AccountNotifications.tsx`, `frontend/src/sw.ts`, the web
app manifest, and the nginx location for the event stream.

## Context

ICS has no way to tell a user that something they care about changed. People
learn about a new version of a spec by accident, and a new document in a
project they follow is invisible until they open the project. The only
outbound message today is the Google Chat card after a GitLab binding sync
(`services/notifications`, one webhook per binding, not per user).

Pieces already in place: Redis (sessions, rate limits, arq, OCR secrets),
the arq worker, the `email_outbox` table with SMTP delivery, the Google Chat
provider with a host-locked URL check, the backend i18n catalogue
(ADR-0011), and FastAPI 0.141 with native Server-Sent Events
(`fastapi.sse.EventSourceResponse`, keepalive comment every 15 s,
`X-Accel-Buffering: no`). Production runs two uvicorn workers behind nginx
with HTTP/2 at the edge; Redis is capped at 256 MB.

## Problem

1. What a user can watch (a single asset, a whole project) and at what grain.
2. Where notifications are kept so the database does not fill with
   short-lived rows, and how the inbox stays bounded.
3. How an event reaches a browser tab within a second, with two API
   processes and many tabs per user, without polling.
4. How the same event reaches the OS (browser push), e-mail and a personal
   Google Chat webhook without spamming during bursts (an agent can write
   twenty versions in a minute).
5. How a notification never reveals an asset the recipient can no longer
   read.
6. Which libraries, given that most of what is needed is already in the stack
   or in the browser.

## Decision

### 1. What lives where

| Data | Store | Why |
|---|---|---|
| Watches (asset, project) | PostgreSQL `watches` | Configuration, must survive a Redis flush, joined with permissions in the fan-out query. |
| Preferences | PostgreSQL `notification_preferences` | Configuration, one row per user. |
| Browser push subscriptions | PostgreSQL `push_subscriptions` | Device registration; losing it silently breaks push until the user re-enables it. |
| Notifications (the inbox) | Redis, per user | Short-lived, capped, high write rate, cleared by the user. This is the part that must not land in Postgres. |
| Live delivery | Redis pub/sub | Fan-out to whichever API process holds the user's stream. |
| Pending e-mail and Chat batches | Redis lists | Buffers of minutes, dropped once sent. |

Losing Redis empties inboxes and pending batches. That is acceptable by
design: e-mail already sent stays sent, watches and preferences are intact,
and new events arrive normally. Redis persistence is still recommended
(section 9).

### 2. Watches

```
watches(
  user_id     FK users   ON DELETE CASCADE,
  asset_id    FK assets  ON DELETE CASCADE NULL,
  project_id  FK projects ON DELETE CASCADE NULL,
  level       text  -- asset: 'watch' | 'mute'; project: 'new' | 'all'
  created_at,
  CHECK (num_nonnulls(asset_id, project_id) = 1)
)
UNIQUE (user_id, asset_id)   WHERE asset_id IS NOT NULL
UNIQUE (user_id, project_id) WHERE project_id IS NOT NULL
INDEX  (asset_id)   WHERE asset_id IS NOT NULL      -- fan-out, FK cascade
INDEX  (project_id) WHERE project_id IS NOT NULL
```

Two nullable foreign keys instead of a polymorphic `target_id`: cascades and
referential integrity come for free, and each fan-out lookup hits a partial
index.

- Project level `new`: new assets in the project (created, moved in, shared
  in through `AssetProjectShare`). Level `all`: that plus every new version
  of any asset in the project.
- Asset level `watch`: new versions and deletion. Level `mute` overrides a
  project watch for one noisy asset.
- Own assets: owners and maintainers get notified about others' changes
  without a row, through the preference `watch_own_assets` (default on).
  One less row per asset, and it follows ownership changes automatically.
- Watching needs read access at the moment of subscribing; the fan-out checks
  it again for every event (section 4).

### 3. Event types

Stable codes, stored in the inbox as `code` plus params, never as text
(same pattern as scanner findings, ADR-0011):

| Code | Recipients | Link |
|---|---|---|
| `asset.created` | project watchers (`new`, `all`) | `/v/{slug}` |
| `asset.added` | project watchers of the target project (move, project share) | `/v/{slug}` |
| `asset.updated` | asset watchers, project watchers (`all`), owner and maintainer | `/v/{slug}` for one version, `/v/{slug}/diff?from=..&to=..` for a range |
| `asset.deleted` | asset watchers, owner | the project page |

Always excluded: the actor (also when an agent acts for the user through
MCP), users with the master switch off, and muted assets. A CI binding sync
has no user actor and shows as "GitLab sync".

Out of the first version, each with a code reserved: review due
(`review_due_at`, ADR-0015), a new relation to a watched asset (ADR-0016),
OCR finished (ADR-0021), comments (ADR-0001).

### 4. Pipeline

```
route / service ──commit──> emit()  ──arq──>  notify_asset_event (worker)
                                                 │ 1 SQL: recipients + prefs + read access
                                                 │ 1 Redis pipeline: inbox Lua per recipient
                                                 │                  + PUBLISH ntf:live:{uid}
                                                 ├─> email batch   (list + deferred job)
                                                 ├─> chat batch    (list + deferred job)
                                                 └─> web push      (per device, immediate)
```

**Emit.** Producers call `notifications.emit(...)` after `session.commit()`,
the same way `commit_new_version` already calls `ocr.enqueue`. Hook points:
`commit_new_version` (every version, including CI sync and MCP writes), the
three create paths (`routes/assets/crud.py`, `routes/assets/documents.py`,
`routes/mcp_assets/upload.py`) through one helper, moving an asset into a
project, adding an `AssetProjectShare`, and soft delete. A test asserts that
every `Asset(` construction site calls the helper, so a fourth create path
cannot skip it.

The enqueue after commit is not transactional; a crash between the two loses
one event. An outbox table was rejected: it is exactly the Postgres clutter
this design avoids, and a lost notification is not a lost document.

**Debounce at the source.** `asset.updated` does not enqueue a job. The
producer records the first unreported version and the writers of the burst
(`ntf:asset:{asset_id}:from`, `:actors`, `:last`) and adds the asset to the
due queue `ntf:due:upd` with `ZADD NX` (due in 20 s). A sweeper in the main
worker (every 5 s) claims due members atomically and fans out once per burst,
reporting the range: "v5 to v14, 10 versions". An arq `_job_id` dedupe was
rejected: an event arriving while the job runs is dropped by arq, and the
marker it leaves waits for the next write. With the due queue a write after
the claim simply starts the next burst. The same queue pattern schedules the
e-mail and Chat batches (`ntf:due:mail`, `ntf:due:chat`).

**Recipients.** One query: asset watchers, project watchers of
`asset.project_id` and of its `AssetProjectShare` projects at the right
level, owner and maintainer when their preference allows, minus mutes, minus
the actor, joined with `notification_preferences` (missing row means
defaults). Read access is checked in the same query by a new set-based
predicate `permissions.readers_filter(asset)`, the user-side mirror of
`visible_assets_filter`. A parity test compares it with `effective_role` on
generated fixtures, so the two cannot drift.

**Inbox write.** One Lua script per recipient (`redis.register_script`,
EVALSHA with automatic reload), all recipients in one pipeline round trip.
100 recipients cost one SQL query and one Redis round trip.

### 5. Redis inbox layout

Keys use a hash tag, so every key of one user maps to one slot and the Lua
script stays valid on Redis Cluster:

| Key | Type | Content |
|---|---|---|
| `ntf:{uid}:log` | STREAM | entries, field `p` = compact JSON (orjson) |
| `ntf:{uid}:unread` | ZSET | member = stream id, score = its ms timestamp |
| `ntf:{uid}:ck:{collapse_key}` | STRING, TTL 15 min | stream id of the last entry for that key |
| `ntf:{uid}:mail`, `ntf:{uid}:chat` | LIST | stream ids waiting for a batch |
| `ntf:asset:{asset_id}:from`, `:actors`, `:last` | STRING, SET | the burst of versions not reported yet |
| `ntf:due:upd`, `ntf:due:mail`, `ntf:due:chat` | ZSET | members due at the score (unix time) |
| `ntf:live:{uid}` | pub/sub channel | live events |

A stream fits the inbox well: ids are time-ordered and unique, so they serve
as the cursor for pagination (`XREVRANGE log (id - COUNT n`) and as the SSE
`Last-Event-ID` for resuming after a reconnect (`XRANGE log (id +`). Stream
entries are listpack-encoded and cheaper per entry than a hash plus a sorted
set of ids.

Payload of one entry, about 300 bytes:

```json
{"c":"asset.updated","a":{"id":"…","n":"Alice Smith"},
 "s":{"slug":"k3x9…","t":"API spec","k":"markdown"},
 "p":{"slug":"crm","n":"CRM"},"v":14,"fv":5,"n":10}
```

The title is a snapshot of the moment, like an e-mail subject.

**The script** (`inbox_push.lua`), atomic per user:
1. Collapse: if `ck:{key}` points to an entry that is still unread, read it,
   merge (`n` summed, `fv` kept, the rest replaced), `XDEL` and `ZREM` it.
   The collapse key is `{code}:{asset_id}`. A read entry is never merged, so
   the user does not see an old item change under their eyes.
2. `XADD`, `ZADD` into unread, `SET ck:{key} EX 900`.
3. Trim: `XTRIM MAXLEN cap` (exact; the cap is small) and `MINID` for the
   retention window, then remove from `unread` every id older than the oldest
   remaining entry. The unread count is always `ZCARD`, never a separate
   counter that could drift.
4. `EXPIRE` all keys of the user to the retention window, so inactive users
   leave nothing behind.
5. Return the new id and the unread count.

Defaults: `ICS_NOTIFICATIONS_INBOX_MAX=150`, `ICS_NOTIFICATIONS_RETENTION_DAYS=30`.
Worst case per user: 150 x 300 B, about 45 KB plus overhead.

**Reads.**
- Badge: `ZCARD`, O(1).
- List page: `XREVRANGE` plus `ZMSCORE` for read flags in one pipeline, then
  one SQL query with `visible_assets_filter` over the page's slugs. Entries
  for assets the user can no longer read are returned as `unavailable`
  without title or project. Access is therefore checked at write time and at
  read time.
- Mark read: `ZREM ids`; mark all read: `DEL unread`; delete: `XDEL` plus
  `ZREM`; clear: `DEL log unread`. Every mutation publishes a `sync` event
  with the new unread count, so other tabs and devices update the badge.

### 6. Live delivery: SSE

`GET /api/notifications/stream`, `response_class=EventSourceResponse`
(FastAPI native, no `sse-starlette`).

- Events: `notification` (entry plus unread count), `sync` (unread count
  after a change elsewhere), `reset` (the resume id was trimmed away: the
  client refetches). Each event id is the stream id; on reconnect the browser
  sends `Last-Event-ID` and the server replays the gap from the stream before
  going live, so nothing is lost across a network blip.
- One pub/sub connection per API process (`notifications/live.py`), started
  in the lifespan. It subscribes to `ntf:live:{uid}` when the first stream of
  that user opens in that process and unsubscribes when the last one closes,
  then routes messages to per-connection `asyncio.Queue`s (bounded; a slow
  client that fills its queue gets `reset` and is closed). A process
  receives only events of users connected to it.
- The endpoint authenticates with a short-lived DB session that is closed
  before streaming starts. Holding the request session for the life of the
  stream would drain the pool with a few hundred open tabs.
- Every 60 s the stream checks the session revocation store (one `GET`);
  after logout or lockout it closes.
- Cookie auth only. PAT and OAuth bearer tokens get `403`; agents do not need
  a live stream.

**Browser side.** Native `EventSource`: reconnect and `Last-Event-ID` are
built in, and a same-origin stream sends the session cookie. One stream per
browser, not per tab: tabs elect a leader with the Web Locks API
(`navigator.locks.request("ics-notifications", …)`); the leader holds the
`EventSource` and relays events over `BroadcastChannel`. When the leader tab
closes, the lock passes to another tab. Incoming events update the TanStack
Query cache with `setQueryData`; there is no refetch and no polling.

### 7. Delivery channels

Each channel is a module with the same shape (`enabled_for(prefs)`,
`deliver(user, entries)`), next to the existing Google Chat provider.

**In-app.** Always on while the master switch is on. The badge and the
screen are described in section 8.

**Browser (Web Push).** Notifications appear in the OS even with ICS closed.
- VAPID (RFC 8292) with `ICS_VAPID_PRIVATE_KEY` and `ICS_VAPID_SUBJECT`
  (`mailto:`); `python -m app.cli vapid-keygen` prints a pair. Without the key
  the channel is off and the UI hides it.
- Encryption `aes128gcm` (RFC 8291) with **`http-ece`** (Mozilla's reference
  implementation, small, one dependency: `cryptography`, already in the
  stack). The VAPID JWT is signed with `joserfc` (already in the stack);
  delivery goes through `httpx` (already in the stack). `pywebpush` was
  rejected: it is synchronous (`requests`) and would need a thread per send.
- The push endpoint comes from the browser, so it is untrusted input: the
  host must match an allowlist of push services (`fcm.googleapis.com`,
  `updates.push.services.mozilla.com`, `web.push.apple.com`,
  `*.notify.windows.com`), otherwise the worker could be used for SSRF.
- `404`/`410` from the push service deletes the subscription; other errors go
  to arq retries. Headers `TTL: 86400`, `Urgency: normal`, `Topic` = collapse
  key, so the push service itself replaces a pending message for the same
  asset.
- Payload (under 4 KB) is rendered in the recipient's locale by the backend:
  `{title, body, url, tag}`. `tag` equals the collapse key, so the OS
  replaces "3 new versions" with "4 new versions" instead of stacking them.
- Service worker `frontend/src/sw.ts`, built as a separate entry to `/sw.js`
  (not hashed, `Cache-Control: no-cache`). It handles `push` and
  `notificationclick` (focus an open ICS tab and navigate it, or open a new
  one). When an ICS window is focused, it posts the event to that window
  instead of showing an OS notification; the in-app toast is enough there,
  and Chrome allows skipping the OS notification when a client is focused.
  No offline caching: `vite-plugin-pwa`/Workbox were rejected because a
  precached app shell brings stale-version problems ICS does not need.
- A minimal `manifest.webmanifest` with icons: required for push on iOS
  (Safari 16.4+, only after "Add to Home Screen") and for installing on
  Android. The UI explains the iOS condition and the Brave setting "Use
  Google services for push messaging", which is off by default and blocks
  push there.
- Permission is requested only after a click on "Enable on this device";
  browsers penalise unprompted requests. Each device is a row with a label
  from the user agent, visible and removable in the settings.

**E-mail.** Modes: `off` (default), `batched`, `daily`.
- `batched`: the first event puts its id on `ntf:{uid}:mail` and adds the
  user to `ntf:due:mail`, due in 10 minutes. Events in the window join the
  list; the sweeper sends one e-mail.
- `daily`: the same list, the job deferred to the next
  `ICS_NOTIFICATIONS_DIGEST_HOUR` (default 8) in
  `ICS_NOTIFICATIONS_TIMEZONE` (default `Europe/Warsaw`).
- Before sending, the job drops entries the user already read or deleted in
  the app: no e-mail about what they have seen.
- Delivery through the existing `queue_email` (`purpose="notification"`,
  already in `EmailPurpose`), so the outbox, retention and SMTP settings are
  reused. Templates in a new module (`email_templates.py` is at 421 LOC),
  text and HTML, mobile-first single column, one row per asset with a
  button-sized link.
- `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
  (RFC 8058) with a signed, purpose-scoped token; `POST
  /api/notifications/unsubscribe` sets the e-mail mode to `off`. Gmail and
  Yahoo require this for bulk senders, and it lets people leave without
  logging in. `_build_message` gains an `extra_headers` argument.

**Google Chat.** A personal incoming webhook in the settings.
- The URL is validated with the existing `GoogleChatProvider.accepts_url`
  (host `chat.googleapis.com`, `https`, port 443, no userinfo). It is a
  bearer secret (anyone with it can post to the space), so it is stored
  encrypted with Fernet under a key derived from the app secret; the
  derivation in `services/ocr/secrets.py` moves to a shared `app/secret_box.py`.
  The UI shows only the space id; the URL is never logged or returned.
- Batching as for e-mail with a 60 s window (`ntf:due:chat`): Google Chat
  limits a webhook to about one message per second, and one card with five
  rows reads better than five cards.
- Card (Cards v2): header "ICS", subtitle with the count, one
  `decoratedText` per entry (icon by event, title, project, actor, version)
  with an "Open" button to `/v/{slug}` or the diff. The link requires login,
  so the space sees titles but not content.
- `400`/`403`/`404` from Google (webhook deleted, space gone) disables the
  channel, stores `chat_error_code` and puts a `channel.chat_disabled` entry
  in the in-app inbox. `429` and `5xx` go to arq retries.
- "Send test" button (rate-limited) sends a sample card.
- The settings say plainly that everyone in that space will see document
  titles.

### 8. User interface

**The bell.** The unread count is a badge on the bell in the top bar
(`NotificationsButton`): number up to 99, then `99+`, `aria-label` with the
count, a short bump on a new event (off under `prefers-reduced-motion`). The
bell opens a popover with the 5 newest entries, "Mark all as read", "See all"
(`/notifications`) and a link to the settings. Amended with the app shell
(ADR-0024), which moved the count from the avatar menu to the bell. The count
also goes to the tab title (`(3) ICS`) and to `navigator.setAppBadge` in an
installed app.

**`/notifications` screen** (lazy route, `PageHeader`): filter All / Unread,
groups by day (`formatDay`), infinite list over the cursor (server pages of
30, no virtualization needed below the 150 cap). A row, `memo()`-ised:
event icon, one line of text ("Alice Smith added **API spec** to CRM",
"**API spec**: 10 new versions"), project chip, relative time (new
`formatRelative` in `lib/format.ts` on `Intl.RelativeTimeFormat`), unread
dot, trailing menu (mark read/unread, delete). The whole row is the link, at
least 48 px high. Header actions: mark all read, clear (with `ConfirmDialog`).
Unavailable entries render dimmed without a link. Empty state with a pointer
to the watch buttons.

**Watch control: one toggle.** An eye icon button in the top bar with
`aria-pressed` and a tooltip, no menu. On a document page it means "I get
notifications about this document": on when the user watches it, or gets it
through a watched project or ownership without muting it. A click turns it
off (drops the own watch, or mutes the document when it comes through the
project or ownership) or back on. On a project page the same button watches
the whole project (`all`) or stops. The `new` level and explicit mutes stay
in the API and show in the watched list of the settings. Optimistic, with
rollback on error.

**`/account/notifications`** (new account section with tabs, next to the
existing `/account/tokens`; `UserMenu` gets "Settings"):
1. Master switch. Off stops all channels and keeps watches.
2. Channels: in-app (on), browser (per device: enable button, device list),
   e-mail (off / batched / daily), Google Chat (URL, status, test).
3. What to notify about: a matrix of event types by channel. On a phone it
   becomes one card per event with channel chips.
4. "Notify me about changes to my own documents".
5. Watched items: projects with level, assets, unwatch; paginated.

All text through the i18n catalogues (`notifications.*`, `accountNotifications.*`,
with `tn` for counts), both locales.

### 9. Operations

- nginx: a dedicated `location = /api/notifications/stream` with
  `proxy_buffering off` and `proxy_read_timeout 1h` (the general `/api/` has
  60 s; the 15 s keepalive would survive it, but a dedicated block states the
  intent). `/sw.js` and the manifest from the static root with `no-cache`.
  HTTP/2 at the edge already removes the six-connections-per-host limit of
  HTTP/1.1; the tab leader election removes it for HTTP/1.1 clients too.
- Redis: the production limit goes from 256 MB to 512 MB (`compose.prod.yaml`)
  and the eviction policy stays `noeviction` (sessions and arq must not be
  evicted). AOF (`appendonly yes`, `appendfsync everysec`) is recommended but
  left to the operator: switched on only in the command line of an instance
  that has an RDB snapshot and no AOF, Redis starts empty, so it is turned on
  at run time first (`docs/DEPLOY.md`, step 7). Worst case for 1000 active
  users: about 50 MB of inboxes.
- Logs (no metrics endpoint): `notify.fanout` with recipient count and
  duration, `notify.channel.failed` with channel and code.

### 10. API

| Method and path | Purpose |
|---|---|
| `GET /api/notifications?before=&limit=&unread=` | page of entries, cursor = stream id |
| `GET /api/notifications/summary` | `{unread}` |
| `GET /api/notifications/stream` | SSE |
| `POST /api/notifications/read` | `{ids}` or `{all: true}` |
| `POST /api/notifications/unread` | `{ids}` |
| `DELETE /api/notifications/{id}`, `DELETE /api/notifications` | delete one, clear |
| `GET/PUT /api/notifications/preferences` | preferences |
| `POST /api/notifications/chat/test` | test card |
| `GET /api/notifications/push/key` | VAPID public key |
| `PUT/DELETE /api/notifications/push/subscriptions` | register or remove a device |
| `POST /api/notifications/unsubscribe` | one-click e-mail opt-out (token) |
| `PUT/DELETE /api/assets/{slug}/watch`, `PUT/DELETE /api/projects/{slug}/watch` | watch |
| `GET /api/watches` | watched items |

Errors through `ApiError` with codes (`watch_forbidden`,
`notification_not_found`, `invalid_webhook_url`, `push_endpoint_not_allowed`,
`push_not_configured`, `invalid_unsubscribe_token`), added to
`docs/api-errors.md` and `errorMessages.ts`.

### 11. Libraries

| Need | Choice | Rejected |
|---|---|---|
| Live stream | FastAPI `EventSourceResponse` + native `EventSource` | WebSocket (two-way not needed, own reconnect and resume), long polling, `sse-starlette` (now built in), `@microsoft/fetch-event-source` (only needed for custom headers; cookies suffice) |
| Tab coordination | Web Locks + `BroadcastChannel` | `SharedWorker` (no Safari on iOS before 16, harder to debug) |
| Background jobs | arq (existing) | Redis Streams consumer groups as a second bus |
| Web Push | `http-ece` + `joserfc` + `httpx` | `pywebpush` (sync), FCM SDK / OneSignal (third party sees document titles) |
| Service worker | hand-written TS entry | `vite-plugin-pwa`/Workbox (offline caching not wanted) |
| Notification platforms | none | Novu (self-hosted needs MongoDB and several services), Knock (SaaS, titles leave the company) |
| Client state | TanStack Query (existing) | a separate store |

New dependencies: `http-ece` in the backend. None in the frontend.

## Reactivation trigger

- More event types (review due, relations, OCR, comments): add a code, a
  producer hook and catalogue keys; the pipeline does not change.
- Users ask for quiet hours or a per-project e-mail mode: extend the
  preferences JSON.
- Slack or Teams webhooks: a new provider in the existing registry.
- Agents need to watch (`ics_asset_watch` in `ics-mcp`): the endpoints are
  there.
- More than about 2000 concurrent streams per process, or more than two API
  processes: move the stream to a dedicated service; the Redis contract stays.
- Redis memory for inboxes above 25% of its limit: lower the cap or the
  retention.

## Consequences

- Postgres gets three small configuration tables; notifications themselves
  never touch it (except e-mails, which already go through `email_outbox`
  with its retention).
- Two places check read access (fan-out and list), guarded by a parity test.
- Every asset write path must call `emit`; a test enforces it for create
  paths, and `commit_new_version` covers all versions in one place.
- Each API process keeps one extra Redis connection for pub/sub.
- Production needs VAPID keys, the nginx stream location and the Redis limit
  change; the sysadmin guide gets a section.
- Web push on iOS works only for users who add ICS to the home screen.
- The bundle budget in `frontend/scripts/check-bundle.mjs` goes from 170 to
  175 JS files. The notification and account screens share one lazy chunk
  (`views/accountScreens.ts`); the rest is rolldown regrouping small shared
  chunks once the badge and its menu section sit in the always-loaded top bar. Total size is
  unchanged in practice (9.4 MiB of 10).

## Delivery plan

1. Backend core: migration 0043, watches, inbox (Lua), `emit` hooks, fan-out
   job, list/read/delete/summary/stream endpoints, `readers_filter` with the
   parity test.
2. Frontend in-app: avatar badge and menu section, `/notifications`, watch toggle, stream
   hook with tab leader election.
3. Settings screen, e-mail channel with batching and one-click unsubscribe,
   Google Chat channel.
4. Web Push: VAPID, service worker, manifest, device list, nginx.
5. Documentation: sysadmin guide, `api-errors.md`, CHANGELOG, user guide.
