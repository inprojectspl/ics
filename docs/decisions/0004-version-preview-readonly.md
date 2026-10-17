# ADR-0004: Archived version preview is read-only and separate from restore

**Status:** Accepted, implemented 2026-08-05.
**Decision owners:** Owner / Product.
**Scope:** `app/services/versions.py`, `app/services/version_banner.py`,
`app/routes/assets/{view,versions,_helpers}.py`, `app/routes/shares/viewer.py`,
`app/routes/html_viewer.py`, frontend: `views/{Viewer,ShareView}.tsx`,
`components/{StaleVersionNotice,VersionHistoryList,VersionHistorySection}.tsx`.

## Context

A feature request asked for the shared link page to show the number of file
versions and the update history (who, when). That raised a question: since
storage keeps every version in its own tree (`{prefix}/v{N}/...`), can an old
version be **opened in the browser without making it current**?

Until then the only way to reach archived content was `POST
/api/assets/{id}/versions/{n}/restore`, which copies the `vN` tree to `vN+1`:
it bumps `asset.version`, adds an `AssetVersion` row, reruns the security
scan, refreshes the full-text index and writes `asset_rolled_back` to the
audit log. "I just want to see what was there" therefore cost a permanent
mutation of the document, and broke every working share link (the visitor
suddenly sees different content).

## Problem

Three decisions needed settling.

### 1. Preview as a read mode vs yet another restore

- **A. Read-only `?version=N` on the read endpoints.** The document payload,
  the collection file and the HTML grant accept a version number; the asset
  row is not touched. Chosen.
- **B. "Restore into a sandbox"**: copy the version into a temporary asset.
  Rejected: multiplies assets, eats quota, needs GC, and still does not show
  the history in the context of the original.
- **C. Diff only (the existing `/diff`).** Rejected: a diff answers "what
  changed", not "what it looked like"; useless for a vault or an HTML bundle
  (for `html_bundle` diff was outright forbidden).

Consequence of choosing A: **editing is disabled in preview mode**. Saving
from the editor writes to the current version, so "edit v1" would silently
overwrite v5. Promoting old content stays with an explicit "Restore".

### 2. The version goes in the iso-viewer path, not in the query

An HTML bundle renders on a separate subdomain (`html.ics.localhost`), where
relative URLs (`css/app.css`, subpages) resolve against the path. If the
version were passed as `?version=1`, the first `<link href="css/app.css">`
would drop the parameter and fetch the file from the current version, and the
page would look like a v1 + v5 hybrid. That is why the archive is served under
the `/-v{N}/{slug}/{path}` prefix, and the browser carries it to all
dependencies by itself.

Entry keys in the `ics_html_access` cookie are distinct: `"{uuid}"` for the
current version, `"{uuid}:{N}"` for an archive. An old grant therefore does
not open the history (and vice versa): fail-closed. The visitor gate for
`critical` without a bypass is evaluated from the **asset** status, not the
version: the scan concerns the document, so a blocked bundle is blocked in the
history as well.

### 3. Shape of the "outdated version" bar in the HTML preview

Markdown gets a React warning (`StaleVersionNotice`). A bundle has no ICS
chrome, so the bar has to be injected into the served document. Considered:

- **`position: fixed` at the top**: moves nothing, but permanently covers the
  top ~30 px of the page's own sticky navbar. Rejected by the owner.
- **A pill in the corner**: no collisions, but not visible enough.
- **A static block in the normal flow** (chosen): inserted right after
  `<body>`, pushes the content down, so it covers nothing and does not float
  while scrolling. It has `position: relative` + `z-index: 2147483647`:
  `relative` without offsets does not take it out of the flow, but makes
  `z-index` apply at all, so no `z-index` on the page can cover the warning.
  Critical properties are `!important`, because the bundle's stylesheet may
  contain `div { display: none }`. The close button removes the node,
  restoring the layout bit for bit.

The snippet is **ASCII-only** (non-ASCII characters as numeric entities),
because a bundle may declare a charset other than UTF-8; injection works on
bytes, so pages in iso-8859-2 pass through untouched.

## Decision

1. `?version=N` on `GET /doc`, `/file`, `/html-grant` (owner path and share
   link path): read-only, validated by a single `resolve_preview_version`.
   The service raises a domain `VersionNotFound` (services know nothing about
   HTTP); the mapping to 404 is done by a
   single wrapper, `routes._version_param.resolve_version_or_404`, also called
   by `diff_versions` and the iso-viewer grant, so that "one validation point"
   is more than a statement. Non-HTTP surfaces (MCP, jobs) call the service
   directly.
2. The entry and the file tree are computed from **that version's tree**
   (`derive_entry_path` on `list_version_files`), not from `asset.entry_path`.
3. Version history at the `viewer` threshold (`GET /api/assets/{id}/versions`,
   `GET /api/share/{token}/versions`: the same response shape, a flat list).
   `storage_prefix` and the author's full email only for editor+ (a single
   `privileged` flag, fail-closed); the link shows the author without the
   domain (`display_name` → local part of the email), because `public` mode
   reaches the internet.
4. Viewing history **does not consume `max_views`**: only reading the current
   content counts as a view. Otherwise a "single-open link" would die on the
   first click on an archived version.
5. The bundle archive is served under `/-v{N}/{slug}/{path}`, with the bar
   injected into `.html` / `.htm` files.

## Version comparison (extension, 2026-08-06)

Version preview exposed gaps in the existing comparison: added files were
only names (you could not see what was in them), you could not tell who made
which version, HTML bundles had no diff at all, and the whole thing lived in a
~800 px modal.

6. **One response shape for all three kinds.** `files[]`
   (`path`, `change`, `binary`, `added_lines` / `removed_lines`,
   `size_from` / `size_to`) instead of three separate protocols (md_single:
   a string; md_collection: three lists of names; html_bundle: 400). The logic
   moved to `app/services/version_diff.py`, because `routes/assets/versions.py`
   was approaching the 400 LOC threshold (ADR-0002). The old `diff` field
   for md_single **is gone** (breaking for clients older than this change): it
   cost a second full read of the same bytes just to build a string that
   `?path=` produces anyway, and it brought a per-kind branch back into the
   route, which is exactly what this point removes. `ics_asset_diff` passes the
   JSON through without a model, so updating the tool description to
   `files[]` + `?path=` was enough.
7. **One-sided files have content.** `?path=` for a file that exists in only
   one of the versions returns an "all added" / "all removed" diff (previously
   404). This was the main gap: you could not look into a file that had just
   been added to the vault.
8. **HTML bundles compare like everything else.** Files that decode as UTF-8
   get a full unified diff; binary ones (images, fonts, video) are listed as an
   entry with a size and a `binary` flag, with no content (a line diff of bytes
   says nothing) and no counters. Whether a file is text is decided by a decode
   attempt, not by the extension (the same rule as in `file-mcp`).
9. **`+N/-M` counters with a byte threshold** (`DIFF_COUNT_MAX_BYTES`,
   512 kB): above it we return `null` and the UI shows "~" with a tooltip.
   Without this, a minified single-line `bundle.js` would run Myers over a
   megabyte just to print "+1 -1".
10. **Diff at the `viewer` threshold** (previously editor+), with an entry
    point from the asset list for anyone with access, consistent with history
    and preview. "Restore" stays at editor+, so a read-only collaborator does
    not see a trap button.
11. **A `/v/<slug>/diff?from=&to=` screen** next to the modal: the modal is a
    shortcut (list of changes), the screen has room to expand content. File
    content loads only on click, so a 50-file collection does not load 50
    diffs up front.
12. **The main panel is a STACK of diffs, not a second file list.** The first
    version of the screen had a tree on the left and a change summary on the
    right, which is the same list twice, with file content only after a click.
    Now it works like GitLab: all files one below another, and the tree only
    scrolls to a block (`scrollIntoView` on an anchor). Each block's content
    loads when it approaches the viewport (`lib/lazyObserve.observeOnce`, the
    same gate as heavy Markdown widgets), so opening the screen costs as many
    requests as are visible, not as many as there are files. The version
    picker bar goes into the `banner` slot of `CollectionLayout` (full width
    above the sidebar and the diff), because the layout is pinned to the
    viewport height. Choosing the same version on both sides is blocked with
    `<option disabled>`: the only path to the "versions must differ" error
    went through the UI.
13. **The screen uses the same skeleton as the vault reader**
    (`CollectionLayout` + `FileTree` + `SegmentedToggle`): a tree of changed
    files on the left and the mode switch in the `modeToggle` slot, where the
    vault has "Text / Graph". `FileTree` got two optional props
    (`stripExtension`, `badgeFor`), because the diff shows full names
    (`index.html` vs `app.css`) and a change marker; the vault keeps its
    behavior through the defaults. The alternative, a separate tree for the
    diff, would have been a second implementation of the same navigation.
14. **Intra-line highlighting** (`lib/intralineDiff.ts`): for paired lines we
    compute an LCS on tokens and paint a stronger background only on what
    actually differs. Word granularity, not character granularity: `134` →
    `141` marks whole numbers instead of making confetti out of single digits.
    Three safeguards: a 300-token limit (a minified line does not enter an
    O(n·m) LCS), a 25% similarity threshold computed **without whitespace**
    (spaces always match, so two completely different lines came out as "half
    shared"), and trimming whitespace from the highlight edges. The same
    function feeds both modes.
15. **Side-by-side mode computed on the client.** The backend returns one
    format (unified); `lib/parseUnifiedDiff.ts` (a pure function) builds
    two-column rows from it, so switching modes costs no request. Pairing: a
    contiguous `-` block followed by a `+` block, with the surplus getting an
    empty cell; without this, replacing one line would spread over two rows.
    The mode choice is kept in `localStorage`. `UnifiedDiff` renders from the
    same parser (flattening the rows back to "all `-`, then `+`" order), so
    both modes share one pairing and one highlighting instead of two
    implementations.

## Consequences

- A read-only collaborator (project viewer, viewer share) gained access to the
  version history. This widens metadata visibility, deliberately: they already
  saw the file and its content; now they also see who changed it and when.
- Serving an HTML file with the bar requires buffering it in memory (so we
  know the `Content-Length`). This applies only to HTML documents; media, JS
  and CSS are streamed as before.
- `MAX_GRANTED_PER_COOKIE` (32) now also covers archive entries: heavy history
  browsing across many bundles pushes out the oldest grants. The consequence
  is having to click "Open" again; no data is lost.
- The MCP surface got the same parameter (`file-mcp`, `files-mcp`, `source`),
  so an agent reads an archived version with the same tools as the current one
  (`ics_asset_read(version=)`, `ics_asset_list_files(version=)`). Extending
  `ics-mcp` also required relaxing `VersionInfo`: `storage_prefix` is now
  optional, because ICS returns `null` for a read-only collaborator.
- The `?version=` contract (parameter declaration, 404 mapping, the
  `version` / `current_version` echo) is defined in the neutral
  `app/routes/_version_param.py`, so no route package has to import another:
  `mcp_assets` does not depend on `routes.assets`, and `html_viewer` / `shares`
  need no lazy imports for this symbol.
- **`outline` deliberately has NO `?version=`**, and this is an inconsistency
  visible to clients, not just a missing feature: the outline is cached per
  current `asset.version` (in ICS) and per slug (in the MCP client), so
  versioning it would require changing the key in both. Until then,
  `read` / `list_files` know about versions and `outline` does not, which is
  why both tool descriptions and the `ics-mcp` `tool-selection.md` state
  explicitly that `lines=` ranges from the outline do not apply to `version=`,
  and that the structure of an archive comes from `list_files(version=)`.
- Out of scope (to decide when the need arises): downloading a ZIP of an
  archived version (`/download?version=`), a versioned `outline`, and
  `version` in `POST /api/share/{token}/resolve` for agents that read links.
