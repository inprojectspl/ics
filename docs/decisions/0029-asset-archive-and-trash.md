# Asset archive and trash

Status: accepted

## Context

Deleting an asset only set `deleted_at`: the row, its versions and its files
stayed for good, the web app had no way back, and nothing told a user how
long a deleted document would last. Teams also had no way to keep a document
they were done with without it cluttering every list and search result:
the only choice was keeping it in view or deleting it.

## Problem

Give documents two states besides live, each with one clear meaning, in the
web app, the API and ICS-MCP:

- **archive**: done with, kept, out of the way;
- **trash**: deleted, recoverable for a while, then gone with its files.

Both have to scope like documents do (a project, or the owner's own space),
and leave room for asset packages, which do not exist yet.

## Decision

### What each state means

| | Archived | In the trash |
|---|---|---|
| Lists, search, palette, sidebar counts, MCP `ics_assets_list` / `_search` | left out unless a filter asks (`archive:archived`, `archive=`) | never |
| Opens by link, slug, share, from the graph or a relation | yes, with a banner | no (404, a link answers 410) |
| Share links and per-person shares | kept | revoked and removed, not restored on the way back |
| Project upkeep (hygiene, duplicates), project counts | left out | left out |
| Storage quota | counts | does not count; restoring needs room again |
| Ends | when someone takes it out | at `purge_at`, when the purge job deletes the row and every file |

The archive is about finding, not access: an archived document still works
everywhere it is linked from. The trash is about access: a deleted document
is unreachable at once, and comes back only through its managers.

### Who

Archiving, deleting, restoring and purging are structural changes, like
moving and sharing: the document's owner, the owner of its project, and
administrators (`permissions.can_manage`). Editors work on content. Anyone
who can see a document can browse the archive it is in. The trash lists
what the caller manages: their own documents and those of projects they own.
An administrator's trash is the same by default; the whole organisation's
trash is a view they switch to explicitly (`admin:trash`, `everyone` when
emptying), so emptying their own trash never removes other people's
documents.

### Where

Archive and trash are not separate objects. An asset's container decides
which archive or trash it is in: its home project, or none (the owner's
global archive and trash). A project's archive is its document list filtered
to `archive:archived`; its trash is the trash filtered to the project. When
packages come, an asset in a package is in that package's archive and trash
the same way, so they need no new tables: `archived_at`, `deleted_at` and
`purge_at` already say everything about the state.

### Retention

`ICS_TRASH_RETENTION_DAYS` (30). `purge_at` is fixed when the asset enters
the trash, so a later change of the setting never shortens what the trash
already promised, and the date the web app shows is exact. The migration
gives assets deleted before this change the full period from the day it
ships. The worker runs `purge_trash` every hour: files go first, then the
row, whose cascade removes versions, relations, pins, and an app's
environments (the micro-application sweeper then drops its schema and roles).
A purge that stops halfway leaves the row in the trash for the next run.

### Names

The word *archive* now means the archive of documents only. Older versions
of a document were called "archived versions" in the web app and ICS-MCP;
they are now *earlier versions* (the version history). API names:
`archived_at`, `archived_by`, `deleted_by`, `purge_at`; `POST/DELETE
/api/assets/{id}/archive`, `POST /api/assets/{id}/undelete`, `POST
/api/assets/{id}/purge`, `POST /api/assets/trash/purge`, `GET
/api/assets/trash` (MCP) and the `state:trash` and `admin:trash` scopes of
`GET /api/assets`.
ICS-MCP: `ics_asset_archive`, `ics_trash_list`, `ics_asset_purge`, and
`archive` on `ics_assets_list` and `ics_assets_search`.

### In the web app

No new screens: the sidebar's document group gains **Archive** (the list
filtered to `archive:archived`) and **Trash** (the `state:trash` scope); the
filter menu gains an **Archive** group; the `…` menu of a document gains
**Move to archive** / **Restore from archive**, and **Delete** becomes **Move
to trash**; a trash row offers **Restore** and **Delete forever**; the reader
shows a banner above an archived document; a project's `…` menu links to
its archive and trash. Archiving and deleting can be undone from the toast.

## Consequences

- A deleted document is gone for good after 30 days; nothing keeps it longer.
  Backups are the only way back after that.
- Restoring from the trash does not bring links and shares back, as before.
- Archived documents still count against the quota.
- An administrator deleting a user still removes that user's assets at once,
  outside the trash, and leaves their files in storage (unchanged).

## Reactivation trigger

Revisit when packages are built, if a team needs an archive that also limits
access, or if 30 days proves too short or too long.

## References

- `backend/app/services/asset_lifecycle.py`, `backend/app/routes/mcp_assets/lifecycle.py`,
  migration `0052_asset_archive_trash.py`, `backend/app/jobs/tasks/cleanup.py` (`purge_trash`).
- Frontend: `lib/useAssetFilter.ts`, `lib/useAssetActions.tsx`, `components/ArchivedBanner.tsx`.
- ICS-MCP `ics_mcp/tools/lifecycle.py`.
