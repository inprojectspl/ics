# Google Sheets links of micro-applications

Status: accepted; Scope amended by [ADR-0033](0033-google-sheets-file-links.md)

## Context

Teams keep operational data in Google Sheets and want to move it into a
micro-application without giving up the sheet: people keep typing in the
sheet, the app keeps its rules, roles and revisions. A sheet and a database
cannot share a transaction: a write to Sheets is not conditional on a cell's
previous value, a read and a later write leave a window in which someone may
type, and an HTTP answer from Google can be lost after Google applied the
write. App handlers have no network access, and Google does not tell anyone
about an edit without extra Drive access and a public callback.

## Problem

Link one app collection to one sheet tab so that data flows both ways, on
request or on its own, without silently losing an edit on either side,
without a new service, and with honest guarantees. The sheet stays as people
keep it: ICS has to understand it, not ask anyone to restructure it, and
an app around an existing sheet is built by an agent, not by filling in
forms.

## Decision

### Scope

- A link is optional and outside the app: the manifest and handlers never
  mention a sheet, and linking needs no new release.
- One link per app (one collection, one tab), one link per spreadsheet:
  ICS is never one of several bridges writing the same file.
- A sync is a **preview**, conflicts decided by a person, then **apply**.
  Someone runs it, or ICS does on its own when the link has `auto_sync`
  (see Automatic sync).
- An agent sets the link up through ICS-MCP: it reads the spreadsheet
  (`POST /api/integrations/google/inspect`: headers, a proposed field name
  and type per column from the first 200 rows, fill rate, uniqueness,
  samples), designs the app on it and links the collection to the tab. The
  panel only connects Google accounts and runs syncs; the only browser step
  is Google's consent.
- The link maps fields to header names in the sheet's first row. Headers
  are found by name, so columns may move; a missing header stops the sync.
  ICS never adds or renames columns and writes no ids into the sheet.
- Every column has an owner: `sheet` (flows into the app only), `app` (flows
  into the sheet only) or `both`. Owning a field by one side is the
  recommended setup; `both` accepts that two people may edit the same value.

### Three-way comparison

For every record and column ICS compares the app's value, the sheet's value
and the **base**, the value both sides agreed on at the last sync
(`sheet_base`, platform database). For `both`: equal values need nothing;
when only one side moved away from the base, that side wins; when both
moved, or there is no base yet, it is a conflict a person decides (keep the
app's value or take the sheet's). No timestamps decide anything.

### Which row is which record

The sheet carries no ids; the platform database keeps, per record, the
values last agreed and the row it was last seen in, and every sync works
the matching out again from the sheet as it is:

- With a `key_field` (a linked field whose values are unique in the sheet,
  e.g. a request number or e-mail), a row is the record with that value;
  repeated values are reported.
- Otherwise a row equal to a record's agreed values (or, for a record never
  synced, its app values) is that record, wherever it moved; then a row in
  the record's last row with a value still equal, or the most similar row
  with at least half its values equal, closest to the last row first.
  Sorting the sheet or inserting rows changes nothing. A row both moved and
  heavily edited between syncs comes out as a removed record and a new row;
  the preview shows it before anything changes. Above 250 000 unmatched
  row/record pairs only exact and same-row matches are tried.
- A row matching an agreed record the person cannot see (deleted in the app
  or hidden by the list rule) is reported, never created again.

Values are compared in one canonical form: the sheet is read with
`UNFORMATTED_VALUE` and dates as serial numbers, so the locale and
formatting of the sheet do not matter; numbers, decimals, dates, timestamps
(in the spreadsheet's time zone, also typed as text without a zone), yes/no and enums are parsed by the field
type, and a cell the field cannot take is reported, not imported.

- A row matching no record creates one (from its `sheet`/`both` columns);
  the app's own columns go back to that row.
- A record without a row is appended to the sheet; a record whose row was
  removed after a sync is reported, never deleted in the app nor re-added.
- A record the app's update rule conditions lock (e.g. `status: submitted`)
  does not take sheet values; the preview says so.

### Apply

No database transaction or row lock is held across a call to Google or the
broker; every state change is conditional on the state it leaves, so two
requests resuming the same operation cannot both finish it.

1. The decisions are checked and the sheet read again: if a touched row
   changed (moving is fine), a header moved since the preview, or the link
   changed, the operation is `stale` and nothing is written. Otherwise it becomes
   `applying` (only if no other sync of the link is applying).
2. The broker applies every app change in one transaction, as the person,
   under the collection's rules, row scopes, field lists and revisions, with
   the operation id reserved in the app's idempotency table and the release
   of the preview checked. A retry after a lost answer or an unknown commit
   (`commit_unknown`) replays the stored result. Any other broker answer
   comes after a rollback: the operation is `stale` (a changed record or
   release) or `failed`, and nothing was applied.
3. The base takes the values the app now holds; the operation is `applied`.
4. The sheet is read again and the cells are placed on it as it is now:
   a touched row that only moved (rows inserted or sorted above) is
   followed by its content, appended rows go after its current last row,
   and a touched row that changed or cannot be told apart stops the write
   (`failed`). The cells go in one `spreadsheets.batchUpdate`, one
   `updateCells` per run of adjacent cells (Google applies all of it or none).
   A definite rejection is `failed`; a timeout or a 5xx after sending is
   `uncertain` and is never resent. **Check** reads the cells back: all
   written means `confirmed`, otherwise `failed`; a `pending` write a crash
   left behind is checked the same way after 90 seconds. Exported values
   join the base only when confirmed, so a failed or unconfirmed write is
   offered again by the next preview, which reads the real sheet.

A new row's record gets its id in the preview and its agreed values when
the app commits, so a failed or lost sheet write cannot make a second
record: the next sync recognises the row by its content. An appended record
is agreed as unconfirmed until its write is confirmed; without a row it is
appended again rather than reported as removed.

Changing the link waits for an applying sync. Another sheet, tab or
collection forgets every agreed value; another header or owner of a column
forgets that column's.

Text is always written as a string value, so a value starting with `=` never
becomes a formula; dates are written as dates.

### Automatic sync

A link with `auto_sync` (set by the agent, `owner_account` only) is synced
by ICS as the asset owner, on the owner's Google account, with the same
preview and apply. When it runs follows the app's activity, as the broker
reports it every 10 seconds ([ADR-0032](0032-micro-application-realtime.md));
ICS asks the broker nothing per link:

- A write to the linked collection (by people or handlers) is in the next
  report, which records it on the link (`app_changed_at`); the next sweep
  runs the sync, so an edit in the app reaches the sheet within seconds.
- The sheet is read on an interval only while the app is in use: every
  `ICS_GOOGLE_SHEETS_ACTIVE_POLL_SECONDS` (30) while people have it open
  (realtime sockets), every `ICS_GOOGLE_SHEETS_POLL_SECONDS` (120) while it
  is awake without open pages, never while it sleeps or is suspended. A link
  is due when its last look is older than that interval, so waking up after
  a sleep longer than the interval syncs at once, and so does a read of the
  app's data through ICS (Data tab, MCP) when the link was not looked at
  within `ICS_GOOGLE_SHEETS_POLL_SECONDS`.
- A sweeper every 10 seconds decides this from the platform database alone
  (the app's last report as the panel shows it, the link's last look and the
  last reported app change) in one read-only query. No link runs more often
  than every 10 seconds.
- A run keeps a hash of the linked columns as it last found them with
  nothing to do; while the sheet hashes the same and the app reported no
  change since, the run reads only Google, neither the app nor the base.
- A run computes the preview in memory and stores it only when there is
  something to apply or a conflict: a preview with nothing to do, or only
  something to report, leaves no operation. One with conflicts stays
  for a person, and so does an error a retry would not fix (no access, a
  missing header, no role in the app); automatic syncing of the link waits
  until a later look goes through (at most every
  `ICS_GOOGLE_SHEETS_POLL_SECONDS`), and the owner gets one notification
  (`sheets.auto_sync_stopped`) per stop. Passing errors (Google or the
  broker unavailable, a side that moved during the apply) are retried
  without a word, after 10 seconds, then twice the previous delay up to
  `ICS_GOOGLE_SHEETS_POLL_SECONDS`. A link whose preview waits for a person
  is looked at again after `ICS_GOOGLE_SHEETS_POLL_SECONDS`.
- A preview a person made in the last 10 minutes is not superseded.
- One run per link at a time (the job id); runs of different links are
  independent. They run on their own Arq queue and worker
  (`arq app.jobs.sheets_worker.WorkerSettings`, `ICS_GOOGLE_SHEETS_MAX_JOBS`
  at once), so syncs never delay publications or notifications.

### Accounts

- Connecting Google is its own OAuth flow (scope `spreadsheets`, PKCE,
  offline access), bound to the ICS session that started it: the callback
  must come back to the same ICS user. The grant stores the verified `sub`;
  signing in with Google grants nothing here and nothing is matched by
  e-mail. The refresh token is encrypted with `secret_box`; access tokens
  are cached in Redis, encrypted, until shortly before they expire.
- `owner_account`: the asset owner's account reads and writes for everyone
  allowed to run the sync; only the owner can choose it.
- `per_user`: each person's own account, never the owner's as a fallback;
  only the person who ran a sync checks its write, with their account.
  Without access to the file the person can ask the owner through a normal
  ICS notification (`sheets.access_requested`, one an hour); the owner
  shares the file in Google, nothing in ICS grants access.
- Changing the link or the owner's Google account bumps the link's
  revision: a preview made before cannot be applied.

### Rights

Configuring needs an owner-like role on the asset; running a sync needs
`app.control` (owner, publisher or the grant). The app's own permissions
still decide every record change, and the preview shows only fields the
person's list rule lets them read.

### Limits

A sync handles at most the app owner's `users.sheet_max_rows` rows (5000 by
default, set per user by an administrator like the storage limit), capped
for everyone by `ICS_GOOGLE_SHEETS_MAX_ROWS` (50 000), since a preview is
stored in one row and the runtime holds the records in memory; 30 sync calls
a minute per person. One apply takes every change of a sync, the first one's
record per row included, in one transaction whose deadline grows with them. Only the header row and the linked columns of the sheet
are read.
A linked header that appears twice in the first row stops the sync. Numbers
with a decimal comma that may be a thousands separator (`1,000`) and dates
with slashes (day or month first?) are reported, not guessed.

## Consequences

- No new process: the backend, the worker, the broker and Redis that ICS
  already has. An automatic link costs one count in the app's database every
  10 seconds and one read of the sheet per interval or app change.
- An edit typed into the sheet between the re-read and the write can still be
  overwritten in a `both` column; owning columns by one side avoids it.
- Without `auto_sync` the sheet is only as fresh as the last sync. With it,
  sheet edits wait up to the interval, and a conflict stops the link until
  someone decides it.
- Deployments set `ICS_GOOGLE_SHEETS_CLIENT_ID` and
  `ICS_GOOGLE_SHEETS_CLIENT_SECRET` (an OAuth client of its own, Sheets API
  enabled); without them the feature is off.
