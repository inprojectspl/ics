# Realtime channels of micro-applications

Status: accepted

## Context

A micro-application page learns about data only by asking: an open page does
not see a record another person, a handler or a Google Sheets sync changed
until it reloads. Apps used by several people at once (a shared board, a
game, a document edited together) need to hear about changes and to pass
short messages between open pages. App handlers run per request and cannot
hold a connection; the broker already serves every app origin, checks the
app session and reports each app's state to ICS every 10 seconds.

## Problem

Give an open app page a live connection that tells it when a collection it
may read changed and carries the app's own messages between pages, so that
many apps with many open pages cost little, nothing leaks past the app's
rules, and ICS learns how many people are active in each app.

## Decision

### Transport

- One WebSocket per open page at `wss://<app origin>/__ics/realtime`,
  terminated by the broker (library `ws`). It signs in with the app session
  cookie; the `Origin` header must be the app's own origin. ICS authorizes
  the person when the socket opens and again every 60 seconds (each socket
  at its own moment of the minute); losing access closes the socket (code
  4403). A broker shutting down closes its sockets with 1001; pages come
  back after a random 1 to 10 seconds.
- Text frames of JSON. Client: `{t: "sub", ch}`, `{t: "unsub", ch}`,
  `{t: "pub", ch, d}`, `{t: "watch", c}`, `{t: "unwatch", c}`,
  `{t: "ping"}`. Server: `{t: "hello", conn, user: {id, name}, limits}`,
  `{t: "msg", ch, from: {id, name}, d}`, `{t: "presence", ch, members:
  [{id, name, n}]}`, `{t: "changed", c}`, `{t: "error", code, ref?}`,
  `{t: "pong"}`.
- An open socket does not wake the app's runners, and neither does ICS's
  own access to the data (Data tab, MCP, a sheet sync): only a person's
  requests wake the app and keep it awake.

### What travels

- **Collection changes.** Every committed write of a collection (CRUD,
  handlers, a sheet sync) marks it changed. Pages that `watch` it get
  `{t: "changed", c}`, at most once a second per collection; each page waits
  a random moment of up to a second before it fetches. The signal names
  the collection only, never records or values: the page fetches through
  the app API, under its rules, so a row scope (`own`) leaks nothing.
  `watch` needs the collection's `list` permission.
- **App channels.** The manifest declares them:
  `realtime.channels.<name> = {permission, presence?, maxMessageBytes?,
  messagesPerSecond?}`. A page subscribes to `<name>` or to a room
  `<name>/<key>` (`key`: 1 to 64 of `[A-Za-z0-9_-]`) with the channel's
  permission; a message goes to every other subscriber of the same room.
  Nothing is stored. With `presence`, subscribers get the room's members
  (debounced, 500 ms).

### Fan-out

Redis pub/sub between broker processes, one channel per app
(`ics:rt:<asset hex>`): a broker subscribes to an app's channel while it has
sockets of that app and delivers to its own sockets. Presence is kept per
room in Redis with a heartbeat, so it survives several brokers. A broker
alone on an app's channel (a publish reached only itself) stops publishing
and keeps presence in memory until another broker joins the channel. ICS
publishes nothing directly: a sheet sync writes through the broker like any
change; its own writes reach watchers but stay out of the report's changed
collections, so they do not start a sync of the same link again.

### Limits

Platform caps (environment of the broker), an app may ask for less:

| Limit | Default |
|---|---|
| message size | 64 KB per app, cap `ICS_MICROAPPS_RT_MAX_MESSAGE_BYTES` 128 KB |
| messages per socket | 30 a second, burst 60 |
| sockets per app | 2000 |
| sockets per person and app | 20 |
| subscriptions per socket | 50 |
| unsent data per socket | 1 MB, then the socket closes (4008) |

Heartbeat every 30 seconds; a socket silent for 75 seconds is closed.

### Activity

The broker's report adds, per app, `realtime: {sockets, people}` and the
collections changed since the last report. ICS keeps the counts in the app's
stats and shows them as active people. Google Sheets automatic sync
(ADR-0031) uses the report instead of asking the broker per link:

- a linked collection reported changed: recorded on the link, synced at the
  next sweep (every 10 seconds);
- people have the app open: read the sheet every 30 seconds;
- the app is awake without open pages: every `ICS_GOOGLE_SHEETS_POLL_SECONDS`;
- the app sleeps or is suspended: no sync; waking up after a sleep longer
  than the interval syncs at once;
- a read of the app's data through ICS (Data tab, MCP) of a sleeping app
  counts as waking up.

## Consequences

- Open pages see changes within about a second of a commit, a sheet edit
  within about 30 seconds while someone has the app open.
- An idle socket costs a few kilobytes in the broker and nothing elsewhere;
  apps nobody has open cost nothing.
- Messages are best effort: a page that reconnects fetches again instead of
  receiving what it missed.
- Server-side game loops stay out of reach (handlers run per request);
  multiplayer apps validate moves in endpoints or trust the peers.
- Production proxies must pass WebSocket upgrades on app origins.
