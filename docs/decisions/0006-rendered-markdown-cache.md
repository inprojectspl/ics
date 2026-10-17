# ADR-0006: Rendered Markdown cache keyed by asset version

**Status:** Accepted, implemented 2026-09-21.
**Decision owners:** Owner.
**Scope:** `backend/app/render_cache.py` (new), render call sites in
`routes/assets/_helpers.py`, `routes/assets/view.py`, `routes/shares/viewer.py`.

## Context

Rendering Markdown means markdown-it plus bleach sanitization: 30-150 ms of
CPU for a 10-50 KB document. A measurement on a 14 KB document gave 38 ms.

There was no cache of the result. `Asset` holds `outline_json` (built by the
worker) and `search_content`, but not HTML. Every visit rendered the document
from scratch: `/doc`, `/render`, the share view. The same document opened by
ten readers meant ten full renders of the same content.

Rendering was already off the event loop through `asyncio.to_thread`, so it
did not block other requests, but with the GIL it still used the process's
CPU.

## Problem

Repeated, expensive work on data that does not change. The main concern with
caching content is whether a reader can see an outdated version of the
document. The answer depends entirely on how the key is built.

Options considered:

1. **A `rendered_html` column in `AssetVersion`**, filled by the worker, like
   the outline. Durable, survives a Redis restart, but bloats the database
   with content, needs a migration, handling of a "not rendered yet" state and
   a fallback when the worker falls behind. Estimate: ~1 day plus the
   migration.
2. **A Redis cache keyed by content** (a hash of the text). Robust against
   everything, but requires reading the file from storage before checking the
   cache, so it saves only CPU, not I/O.
3. **A Redis cache keyed by asset version.** Skips both the render and the
   storage read. Correctness relies on version content being immutable.
   Estimate: half a day.

## Decision

Option 3. The key is `md:{renderer fingerprint}:{asset id}:v{version}:{path hash}`.

The correctness condition holds and is verified in the code: a version's
bytes never change after they are written. Every content mutation (editing,
adding, moving and deleting a file, restoring a version, a binding sync)
copies the tree to `v{n+1}` and writes there. Storage writes go only to a fresh
version prefix or to `v1` of a newly created asset. It follows that a cache
entry cannot go stale because of a change: a change creates a new key, and the
old one is no longer queried and expires.

The renderer enters the key through `_RENDERER_FINGERPRINT`: a hash of the
source of `app/markdown.py` and `app/markdown_sanitize.py` together with the
versions of the rendering libraries (markdown-it-py, mdit-py-plugins, bleach,
pygments). This covers every reason the HTML may change: sanitizer
allowlists, plugins, the highlighter, callout syntax, and also a dependency
bump that changes the output without touching our code.

The first version relied on a manually bumped schema number here. That was
rejected in review: nothing caught a missed bump, so adding a plugin without
remembering it would serve old HTML for the whole TTL, with no signal at all.
The source hash removes the dependency on human memory. The price is
invalidating the cache after a cosmetic change in the module too, meaning one
extra render per document after a deploy. That is the right direction to err
in.

A separate test makes sure `render_markdown_async` is not called anywhere
outside this module: the cache has to be the only path to rendering, and a
direct call in a handler would silently bypass it.

Tuning: a TTL of seven days and a maximum entry size of 1 MB. Larger pages
are served but not stored, so they do not push out many small documents.

Redis is an optimization here, not a dependency. Every error, including an
unreachable server, degrades to a normal render. A test covers this.

The cache holds the document's public HTML, identical for every reader, so it
contains nothing user- or permission-dependent. Access control happens before
the cache is consulted and is not affected by it.

## Reactivation trigger

Revisit this decision when:

- a write path appears that modifies a file in an existing version without
  bumping the number. The immutability assumption then fails and the key has
  to include a content hash, i.e. option 2;
- rendering starts to depend on something outside the text and the rendering
  module, for example per-user or per-organization settings. That dimension
  has to go into the key, or readers will see each other's variants;
- the deployment stops shipping source files (an image without `.py`). The
  fingerprint then degrades to library versions only, which is coarser, and a
  change in `markdown.py` will no longer invalidate entries;
- losing the cache on a Redis restart becomes noticeable. Then option 1, a
  durable cache in the database.

## Consequences

- Reading a document with a cache hit: 0.25 ms instead of 38 ms on a 14 KB
  document, 154 times faster. A hit also skips the storage read.
- Redis usage grows by the rendered HTML of actively read documents. With a
  seven-day TTL and a 1 MB limit per entry this is bounded and expires by
  itself.
- Restoring a version creates a new version, so the content is rendered again
  even though it is identical to the archived one. A deliberate loss, the
  price of a simple key.
- A file deleted manually from storage no longer yields a 404 while its entry
  is in the cache. That state is inconsistent anyway, and in this case the
  cache is proof that the file existed in that version.

## Addendum: titles of `[[ics:...]]` links

A link to another asset without an alias should show that asset's title, but
the title is neither part of the linking document's version nor the same for
every reader: it changes on a rename without a new version, and a reader who
cannot see the target must not learn it. Putting the title into the rendered
HTML would break both the key (stale titles on a hit) and the "no per-user
input" rule above.

So the renderer emits only the slug, as the link text and as
`data-ics-slug`, and the cached HTML stays viewer-independent. After
hydration the client asks `GET /api/assets/link-titles?slug=...` for the
titles the signed-in viewer may see (the canonical visibility predicate) and
swaps the text. Unknown, hidden and deleted targets are left out of the
answer alike, so the link keeps its slug, which is already in the source; a
share-link visitor without a session keeps the slugs too.
