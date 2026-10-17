# Notifications API contract

Design: `docs/decisions/0023-notifications.md`. All endpoints need a signed-in
user (session cookie); errors are `{detail, code}` (`docs/api-errors.md`).

## Types

```ts
type NotificationCode =
  | "asset.created"   // new asset in a watched project
  | "asset.added"     // existing asset moved or shared into a watched project
  | "asset.updated"   // new version(s)
  | "asset.deleted"
  | "channel.chat_disabled"; // the Google Chat webhook stopped working

type EventKind = "asset.created" | "asset.added" | "asset.updated" | "asset.deleted";
type ChannelId = "app" | "push" | "email" | "chat";
type OptionalChannel = "push" | "email" | "chat"; // in-app is always on
type EmailMode = "off" | "batched" | "daily";

interface NotificationItem {
  id: string;                 // opaque cursor, e.g. "1727520000000-0"
  code: NotificationCode;
  at: string;                 // ISO 8601
  read: boolean;
  unavailable: boolean;       // recipient lost access: asset/project are null, link is null
  actor: { id: string; name: string } | null; // null = system (CI sync)
  asset: { id: string; slug: string; title: string; kind: AssetKind } | null;
  project: { slug: string; name: string } | null;
  version: number | null;     // newest version (asset.updated)
  from_version: number | null;// first new version when count > 1
  count: number;              // collapsed events, >= 1
  link: string | null;        // app-relative URL to open, e.g. "/v/abc" or "/v/abc/diff?from=4&to=9"
  params: Record<string, string | number>; // extra, e.g. {error_code} for channel.chat_disabled
}
```

## Inbox

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/notifications?before=<id>&limit=30&unread=true` | | `{items: NotificationItem[], next: string \| null}` (the count comes from `/summary` and the stream) |
| GET | `/api/notifications/summary` | | `{unread: number}` |
| POST | `/api/notifications/read` | `{ids?: string[], all?: boolean}` | `{unread}` |
| POST | `/api/notifications/unread` | `{ids: string[]}` | `{unread}` |
| DELETE | `/api/notifications/{id}` | | `{unread}` |
| DELETE | `/api/notifications` | | `{unread: 0}` |

`limit` 1..50, default 30. Newest first. `next` is the `before` for the next page.

## Live stream (SSE)

`GET /api/notifications/stream`, `text/event-stream`, cookie auth only. Event `id`
is the notification id; the browser resends it as `Last-Event-ID` and the
server replays what was missed.

| event | data |
|---|---|
| `notification` | `{item: NotificationItem, unread: number}` |
| `sync` | `{unread: number, read?: string[], unread_ids?: string[], deleted?: string[], all_read?: boolean, cleared?: boolean}` |
| `reset` | `{}`: the client refetches the list and the summary |

## Preferences

```ts
interface NotificationPreferences {
  enabled: boolean;                 // master switch
  watch_own_assets: boolean;        // others' changes to my assets
  email_mode: EmailMode;
  events: Record<EventKind, OptionalChannel[]>; // in-app is not listed: always on
  chat: { configured: boolean; space: string | null; enabled: boolean; error_code: string | null };
  push: { available: boolean; public_key: string | null }; // VAPID key, base64url
  email_available: boolean;         // SMTP configured on the server
}
```

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/notifications/preferences` | | `NotificationPreferences` |
| PUT | `/api/notifications/preferences` | partial: `{enabled?, watch_own_assets?, email_mode?, events?, chat_webhook_url?: string \| null, chat_enabled?}` (`chat_webhook_url: null` removes it) | `NotificationPreferences` |
| POST | `/api/notifications/chat/test` | | `204` |

## Browser push devices

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/notifications/push/subscriptions` | | `{items: [{id, label, created_at, last_success_at}]}` |
| PUT | `/api/notifications/push/subscriptions` | `{endpoint, keys: {p256dh, auth}, label?}` | `{id}` |
| POST | `/api/notifications/push/unsubscribe` | `{endpoint}` | `204` |
| DELETE | `/api/notifications/push/subscriptions/{id}` | | `204` |

Push payload the service worker receives: `{title, body, url, tag}` (already
localised).

## E-mail opt-out (no login)

`POST /api/notifications/unsubscribe` with `{token}` sets the e-mail mode to
`off`. The e-mail footer links to `/notifications/unsubscribe?token=...`.

## Watches

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/assets/{asset_id}/watch` | | `AssetWatch` |
| PUT | `/api/assets/{asset_id}/watch` | `{level: "watch" \| "mute"}` | `AssetWatch` |
| DELETE | `/api/assets/{asset_id}/watch` | | `AssetWatch` |
| GET | `/api/projects/{slug}/watch` | | `{level: "new" \| "all" \| null}` |
| PUT | `/api/projects/{slug}/watch` | `{level: "new" \| "all"}` | same |
| DELETE | `/api/projects/{slug}/watch` | | same |
| GET | `/api/watches?page=1&page_size=25` | | `{items: WatchItem[], total: number}` (`page` 1-based, `page_size` default 25, max 100) |

```ts
interface AssetWatch {
  level: "watch" | "mute" | null;
  via_project: "new" | "all" | null; // the asset's project is watched at this level
  own: boolean;                        // owner/maintainer and watch_own_assets is on
}
type WatchItem =
  | { type: "asset"; level: "watch" | "mute"; created_at: string;
      asset: { id: string; slug: string; title: string; kind: AssetKind } }
  | { type: "project"; level: "new" | "all"; created_at: string;
      project: { slug: string; name: string } };
```

## Error codes

`invalid_cursor`, `notification_not_found`, `stream_browser_only`,
`invalid_webhook_url`, `chat_not_configured`, `chat_delivery_failed` (502 from
the Chat test), `push_not_configured`, `push_endpoint_not_allowed`,
`push_subscription_not_found`, `invalid_unsubscribe_token`.
