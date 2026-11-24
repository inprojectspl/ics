# Google Sheets links per spreadsheet file, with several tabs

Status: accepted

Amends [ADR-0031](0031-google-sheets-links.md): its Scope (one collection on
one tab) is replaced below. The three-way comparison, row matching, values,
accounts, rights and the apply procedure stay in force, now run per mapping
inside one operation for the whole file. Automatic sync
([ADR-0032](0032-micro-application-realtime.md)) runs per file.

Scope: `backend/app/models/sheets.py`, `backend/app/services/sheets/*`,
`backend/app/routes/sheets.py`, migration `0056`,
`microapp-runtime/src/broker/sheets.js`,
`frontend/src/components/microapps/{MicroAppSheets,SheetSync}.tsx`,
`frontend/src/api/sheets.ts`, the `ics_sheets_*` tools of ICS-MCP.

## Context

People call a Google spreadsheet "a sheet" and mean the file, and teams use
its tabs in three ways: one tab of records; several tabs with the same
columns holding one kind of record split by month, state or team; tabs of
different things used together (orders and the customers they refer to,
with a price list next to them and a summary tab on top). ADR-0031 linked
one collection to one tab, an app had one link and a spreadsheet one link
in the whole ICS. An app over such a file could use one tab only.

ADR-0031 also had a gap between two syncs of the same link: a sync marks
its operation `applied` and only then writes the sheet, while the guard
against a second sync looked for `applying` operations only. A second
preview made in that window (or after a crash before the write, or while
a write was `uncertain`) planned the same appends again and could write a
record into the sheet twice.

## Decision

### The file is the unit

`sheet_links` stays one row per app and per spreadsheet (both unique), with
the account mode, revision, pause and the automatic sync state. What is
linked moves to `sheet_mappings`, one per collection (unique per link):

- `tabs`: one tab, or several tabs whose rows are one kind of record, as
  `[{sheet_id, title, append?}]`. A tab is identified by Google's
  `sheet_id`, so a renamed tab stays linked; a tab given by name is pinned
  to its id by the first read. A tab belongs to one mapping. Tabs no
  mapping names are never read.
- `columns`, `key_field` as in ADR-0031. With several tabs `key_field` is
  required and must be unique across them; rows are matched by key across
  all the mapping's tabs, so a row someone moved between tabs is the same
  record.
- `append_to` (stored as `append` on one tab): where records created in
  the app go when there are several tabs. ICS never guesses the tab.
- `tab_field`: an optional string field of the collection that takes the
  name of the tab a record's row is in. It compares like a column the
  sheet owns, so it follows a moved row and a renamed tab; it is never
  written to the sheet.

`sheet_base` is keyed by `(mapping_id, record_id)` and keeps the tab and row
a record was last seen in.

Rejected: several independent links per app, one per tab (two writers of
one file again, and an app transaction over two collections would reach
the sheet in two writes); a mapping per tab with records merged in the app
(the app would see one kind of record as several collections).

### Reading and comparing

One read of the file per sync step: one metadata call (tab ids, names,
grid sizes), one `values.batchGet` for the header rows of every linked tab
and one for the linked columns. The tabs of a mapping are joined into one
list of rows, each holding the linked columns in the mapping's order, so
`compare` of ADR-0031 runs unchanged on a group of tabs; row numbers count
across the tabs and the preview translates them back to a tab and its own
row. Each tab may hold the linked headers in any order, with any other
columns. A missing tab, a missing or doubled linked header stops the sync
of the whole file and names the tab. The row limit counts the rows of all
linked tabs together.

### Lists the app only reads

A mapping whose columns are all owned by `sheet` is a list the app only
reads (customers, prices, categories): its sync imports and creates records
and never writes to its tabs, not even rows for records created in the
app. No separate import mode is needed: the owners already say it.

### New rows

A record the sheet lacks is appended to the mapping's append tab with the
columns the app owns or shares. A column the sheet owns gets a value only
when the app has one: an empty cell would overwrite a formula or a default
the sheet keeps there. A record of a keyed mapping without a key value is
reported (`key_missing`), not appended, since its row could never be told
from a new one.

### One operation for the whole file

One preview holds one part per mapping. Apply sends the changes of every
collection to the broker in **one transaction** (`changes[].collection`,
one idempotency key), then writes the cells of every tab in **one
`batchUpdate`**, which Google applies in full or not at all. The broker
reads the linked collections in one `REPEATABLE READ` snapshot, so records
of different collections agree with each other. Conflict keys stay
`<record_id>:<field>`: record ids are unique across collections.

### No second plan while a write is unsettled

An operation `applying`, or `applied` with its sheet write `pending` or
`uncertain`, blocks the next preview, apply and link change of the file
(`sheet_sync_unsettled` names the operation). It is settled by `check`,
which reads the cells back and never writes; a check finding the cells not
written marks the write `failed`, and only then may the next sync plan the
rows again. The automatic sync settles its own operations first: it
resumes the owner's `applying` operation with its key and checks a pending
or uncertain write, and otherwise retries later.

### Saving a link

`PUT /api/micro-applications/{id}/sheets` takes the whole link:
`spreadsheet`, `account_mode`, `auto_sync`, `paused`, `expected_revision`
and `mappings: [{collection, tabs, append_to?, columns, key_field?,
tab_field?}]`. The mappings given are the mappings linked, matched to the
stored ones by collection: a kept mapping keeps its agreed values (only
fields whose header or owner changed are forgotten), a mapping left out is
removed with its base, the app's records stay. Another spreadsheet forgets
everything. A tab leaving a mapping keeps the base of its records, so they
are reported (`removed_from_sheet`) and never appended to another tab as
new. Everything is checked before anything changes. The body of ADR-0031
(`collection`, `sheet_title`, `columns`, `key_field`) is still accepted as
one single-tab mapping.

Rejected: a patch-style PUT where a left-out mapping is kept. The panel and
the agent both show and send the whole link, `expected_revision` refuses a
stale one, and removing a mapping deletes no records.

### Out of scope

Deleting sheet rows and moving rows between tabs by the app (a status
change moving an order from "open" to "done") stay out. Both remove whole
rows, unlinked cells and formulas included, and need their own rules for
hidden versus deleted records and for people editing the sheet meanwhile.
Tabs joining a mapping by a name pattern stay out too: a new tab is linked
explicitly.

### Migration

`0056` turns every link into one single-tab mapping and moves its base. The
tab's id comes from the latest operation made under the link's current
revision when its tab name matches; otherwise the first sync pins it by
name. Unapplied previews are superseded. An operation still `applying` or
with an unsettled write is rewritten to the new shape, so it resumes or is
checked as before; settled operations keep their counts only.

## Reactivation trigger

- Rows of records deleted in the app, or rows moved between tabs by a field
  the app changes, should follow in the sheet.
- New tabs of a growing group (a tab per month) should join without an
  agent.
- One app over several files, or one file shared by several apps.
- A tab outgrows the per-sync row limit while the others stay small.

## Consequences

- An app over a spreadsheet file can use any of its tabs: single tabs,
  groups of tabs of one kind of record, and lists it only reads, in one
  sync that reaches both sides in one transaction and one write.
- A row moved by hand between tabs of a group stays the same record, and a
  renamed tab stays linked.
- One bad tab (a missing header, a vanished tab) stops the sync of the
  whole file until fixed; the error names the tab.
- The row limit covers every linked tab together.
- A sheet write that is not confirmed blocks the next sync of the file
  until checked; the automatic sync checks its own.
- Breaking change of the link API's answer (`link.mappings`) and of
  `ics_sheets_link` (`mappings`), acceptable while micro-applications are
  `v1alpha1`; the old request body still links one tab.

## References

- ADR-0031 (links, comparison, accounts), ADR-0032 (automatic sync,
  broker reports), ADR-0027 (micro-applications).
- `backend/app/services/sheets/book.py` (reading the file),
  `compare.py`, `sync.py`, `write.py`, `links.py`, `mapping_rules.py`;
  `microapp-runtime/src/broker/sheets.js` (`readRows`, `applyChanges`).
- Google Sheets API: `spreadsheets.values.batchGet`,
  `spreadsheets.batchUpdate` (`appendDimension`, `updateCells`).
