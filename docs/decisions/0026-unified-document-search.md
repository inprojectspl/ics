# Unified document search

Status: accepted

## Context and problem

The browser first filtered a loaded list locally, then replaced it with an
owner-only substring search. Shared documents disappeared, metadata was lost,
errors became empty results, and only 50 hits could be reached. MCP used a
different OR/prefix query, ignored terms after the eighth, and capped offsets
at 500. Its response-size guard could discard every hit in a large response.

## Decision

Use PostgreSQL's existing stored, GIN-indexed document vector and a single
visibility predicate and query implementation across discovery endpoints.
Normalize accents with an explicit `ics_search` text search configuration.
Default to all query words, support quoted phrases and prefix matching, and
expose broader matching only through `match=any`. Rank exact titles first,
then title matches and weighted metadata/content, with deterministic ties.
The existing ranking penalty for a visible successor still applies.

Use the GIN vector to select candidate documents. Verify quoted phrases in
the full text of each field separately: stored tsvectors cap positions at
16,383 and record at most 256 occurrences of a lexeme. Positional matching
alone loses phrases late in long documents and can join metadata boundaries.
Phrase verification also respects complete identifiers such as `v1.3`.
PostgreSQL also inserts positional operators when parsing hyphenated words,
dates and URLs. Candidate queries remove that adjacency and verify the
original identifier in a single field, preserving its prefix semantics.

The browser sends search, scope and filters to the server before pagination.
Query keys include every input; consume AbortSignal and never display a result
for a previous query as the current answer. Loading, empty results and errors
are separate states. MCP trims pages by complete hits and exposes continuation.
Successful document, sharing, project and relation writes invalidate cached
discovery results. Facet aggregates share one materialized set of eligible
document metadata, avoiding repeated authorization and full-text scans.

No external search cluster or vector database: the current corpus and access
model fit PostgreSQL, and synchronous generated vectors avoid eventual-index
consistency. A dedicated search service is justified only by measured scale or
requirements such as multilingual morphology, semantic retrieval or typos.

## Contract

- `GET /api/assets`: optional `q` (max 200 characters), `match=all|any`,
  `scope`, repeated `f=kind:value`, `facets`; ordinary `page`/`page_size`.
  With `q`, default order is relevance; an explicit `sort` overrides it.
  Filters apply before counting and pagination. `facets=true` adds
  `scope_counts` and `filter_counts` over the matching corpus, not the page.
- `GET /api/assets/search`: same matching, visibility, ranking and complete
  row metadata; bounded array for pickers. The document page uses the paged API.
- `GET /api/assets/search-mcp`: same matching and relevance, page-local
  snippets, exact `total`, `offset`, `limit`, `has_more`; no artificial last page.
- `GET /api/assets/index?q=...`: same matching, existing cursor order and shape.
- Quotes mean exact token adjacency; punctuation is not SQL or tsquery syntax.
  Bare single letters and punctuation-only input match nothing; digits are
  exact terms. All accepted words are used. Search includes title, slug,
  summary, tags and the current extracted content. HTML bundles have metadata
  only; scanned PDFs gain content when OCR completes. Prefixes are not a
  Polish stemmer and arbitrary spelling errors are not silently corrected.

## Consequences and rollout

Apply migration 0044 before deploying the application. It rewrites existing
vectors and rebuilds the existing GIN index under a table lock; schedule the
migration for the corpus size. Existing document text needs no new extraction.
Deploy the corresponding MCP descriptions and query option. Multiword default
matching intentionally becomes narrower; `match=any` preserves broad discovery.
Pagination is deterministic for a fixed corpus; concurrent edits can reorder
ranked offset pages. Test against real PostgreSQL, including migration upgrade
and downgrade, access parity, metadata changes, ranking and continuation.

## Validation

Regression tests use real PostgreSQL for all four discovery endpoints,
including shared/project/admin visibility, accents, quoted phrases across
field boundaries, text beyond the tsvector position limits, compound
identifiers, changes in the same commit, filter combinations and results
beyond the old 50/200/500 cutoffs. The migration is tested on pre-existing
rows, both forward and backward. The index test checks the query plan.

Frontend tests delay and reorder responses, verify cancellation and clearing,
distinguish server errors from no results, refresh searches after mutations
and recover a page after its last item disappears. MCP tests follow every
continuation through response-size truncation in compact and full mode.

A local diagnostic on 2026-10-15 used an isolated PostgreSQL database with
10,000 synthetic documents, one owner and about 2.4 KB of repeated content
per document. Requests included 25 results, full metadata and facet counts.
Median times after the first request (three samples, during the test run):

| Query | Matching documents | Median |
| --- | ---: | ---: |
| Browse | 10,000 | 137 ms |
| `gesla`, matching accented titles | 100 | 83 ms |
| `architecture` | 10,000 | 440 ms |
| `"architecture decision"` | 10,000 | 1,964 ms |

These are diagnostic measurements, not a production latency guarantee.
Broad exact phrases still verify full candidate text and cost more; measure
with the deployment's corpus and concurrency before setting a latency SLO.

## References

- [PostgreSQL text search and ranking](https://www.postgresql.org/docs/current/textsearch-controls.html)
- [PostgreSQL unaccent dictionary](https://www.postgresql.org/docs/current/unaccent.html)
- [GIN indexes for text search](https://www.postgresql.org/docs/current/textsearch-indexes.html)
- [PostgreSQL text search limits](https://www.postgresql.org/docs/current/textsearch-limitations.html)
- [TanStack query cancellation](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation)
