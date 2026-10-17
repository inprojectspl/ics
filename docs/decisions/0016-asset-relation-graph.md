# ADR-0016: Asset relation graph in PostgreSQL

**Status:** Accepted, 2026-09-26. Implemented (phase 2 of the document graph work).
**Decision owners:** Owner.
**Scope:** new table `asset_relations`, `backend/app/services/relations.py`,
`backend/app/relation_extract.py`, the package `backend/app/routes/relations/`,
`backend/app/permissions.py` (graph access predicate), `backend/app/markdown.py`
(`[[ics:...]]` wikilinks), `commit_new_version` and every v1 creation path, and the
`ics-mcp` tools `ics_asset_relations`, `ics_relation_add`, `ics_relation_update`,
`ics_relation_remove`, `ics_graph_neighbourhood`.

## Context

Documents in ICS depend on each other: a design is derived from business goals, a
specification from the design, an annex depends on a contract, version 3 of a
specification replaces version 2. Today none of this is recorded. A link inside a Markdown
body is invisible to the system, and PDFs, Office documents and HTML bundles cannot carry
such links at all. An agent that finds a specification cannot tell what it was based on,
whether that basis changed, or whether a newer document replaces it.

ADR-0015 defines per document metadata, including the computed `freshness` that depends on
`supersedes` relations. This ADR defines the relations themselves and who may see them.

## Problem

1. Where edges are stored and how they are traversed with permissions checked.
2. Which relation types exist, in which direction they are stored, and how inverses are
   shown.
3. Where edges come from (people, agents, document content, integrations) and whether some
   need confirmation.
4. Who can see and change the graph, so that it never becomes a side channel that reveals
   documents a user cannot open.
5. Limits that keep traversal and responses bounded.

## Decision

### 1. Storage: one edge table in PostgreSQL

```sql
CREATE TABLE asset_relations (
  id               uuid PRIMARY KEY,
  source_asset_id  uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  target_asset_id  uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  relation_type    varchar(32) NOT NULL,   -- CHECK against the vocabulary below
  source_path      text,                   -- file inside a source collection
  target_path      text,                   -- file inside a target collection
  target_anchor    text,                   -- heading slug from the outline
  target_version   integer,                -- target version when the edge was made
  note             text,                   -- why, max 500
  origin           varchar(16) NOT NULL,   -- manual | agent | extracted | integration
  created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (source_asset_id <> target_asset_id)
);
CREATE UNIQUE INDEX uq_asset_relation ON asset_relations
  (source_asset_id, target_asset_id, relation_type,
   coalesce(source_path, ''), coalesce(target_path, ''), coalesce(target_anchor, ''));
CREATE INDEX ix_asset_relations_target ON asset_relations (target_asset_id, relation_type);
```

Both foreign keys are indexed (the unique index leads with the source), as the
`0017_perf_indexes.py` rule requires for cascading FKs. A collection stays one node; an
edge can point into it through `target_path` and `target_anchor`. Both must exist in the
target's current version when the edge is added (`relation_target_path_not_found`,
`relation_target_anchor_not_found`); the anchor is stored as the heading anchor it matched.

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. PostgreSQL edge table** | transactional with versions and ACL; FKs and cascades; no new infrastructure; backed up with the rest | traversal is application code (BFS), not one query | **chosen**, ample headroom at the expected scale |
| B. Apache AGE (Cypher inside PostgreSQL) | Cypher, same database | an extension outside the standard PostgreSQL image, weak SQLAlchemy support, ACL still in SQL | rejected for now |
| C. Neo4j or Memgraph next to PostgreSQL | strong graph queries, ready algorithms | a second database, synchronisation, ACL in two places, operating cost | rejected |
| D. One polymorphic node and edge table | uniform model | no FK to `assets`, manual cascades, harder partial indexes | rejected |
| E. Edges only in document content (wikilinks, front matter) | "the document is the source of truth" | does not work for PDF, Office, HTML; every relation change is a new document version | rejected as storage, kept as an extraction source |

Scale: about 240 assets today, up to 20 thousand expected over several years, about 5 edges
per document, so about 100 thousand rows. A depth 3 BFS is at most 6 indexed queries.

### 2. Vocabulary: eight types, stored once in canonical direction

Each edge is stored once, in its canonical direction. The API computes the inverse label,
so a pair of mirrored rows can never drift apart. Names follow OpenProject and PS where the
meaning matches.

| `relation_type` | Canonical direction | Inverse label | OP/PS equivalent | Example | System effect |
|---|---|---|---|---|---|
| `derived_from` | A was made from B | `basis_for` | none | design from business goals | traceability; a new version of B sets `basis_changed` on A |
| `supersedes` | A replaces B | `superseded_by` | none | specification v3 replaces v2 | B gets `freshness=superseded` for viewers who see A |
| `depends_on` | A needs B to be understood or valid | `required_by` | `requires` | annex on contract | an agent reading A gets B as a neighbour |
| `part_of` | A is a part of B | `has_part` | `partof` / `includes` | chapter of a manual | grouping in the project map |
| `references` | A mentions B | `referenced_by` | none | meeting notes mention an offer | weak edge, usually extracted |
| `relates_to` | symmetric | `relates_to` | `relates` | | none |
| `duplicates` | A duplicates B | `duplicated_by` | `duplicates` | the same file uploaded twice | candidate for merging |
| `contradicts` | symmetric | `contradicts` | none | two specifications that disagree | warning in the context pack |

Symmetric types (`relates_to`, `contradicts`) are stored with `source = least(a, b)` and
`target = greatest(a, b)`, so A to B and B to A are the same row. A new type must answer
"what does the system do differently because of it"; if nothing, it is `relates_to` with a
note.

### 3. Origin is informational, edges take effect immediately

There are no suggestions and no confirmation step. An edge exists from the moment it is
written, whoever wrote it. `origin` records where it came from and is shown in the UI and to
agents as a trust signal; it changes no behaviour except extraction ownership:

| Source | `origin` | How |
|---|---|---|
| Person in the UI | `manual` | "Add relation" dialog |
| Agent through MCP | `agent` | `ics_relation_add` |
| Document content | `extracted` | on every content write (below) |
| Integration (PS export) | `integration` | explicit export run |

`origin` is not part of the unique key. Extraction inserts with `ON CONFLICT DO NOTHING`, so
it never overwrites a manual edge; adding manually an edge that already exists as extracted
turns its `origin` into `manual`, after which extraction no longer removes it. Relations are
cheap to reverse and fully audited (`relation_added`, `relation_removed`), which is why no
confirmation is needed, including for `supersedes`.

**Graphs are independent.** A document does not need any relation. A graph can be a single
node or many; many documents can point at one; there is no required global project graph
and no root. An agent reads each node's metadata (`summary`, `doc_type`, `freshness`,
`estimated_tokens`) and decides itself whether to go further.

### 4. Extraction from content

`relations.extract_for(asset, version, text, actor)` runs in the same transaction as the
content write: from `commit_new_version` (next to `search_content`) and from every v1
creation path that bypasses it (multipart upload, `/collection`, `/html`, `/pdf`,
`/document`, `html-json`, empty file). For GitLab CI sync, where the actor is a string, the
binding owner (`gitlab_bindings.created_by`) is the actor.

1. Find references to ICS in the text: `https://<base_url>/v/<slug>`, `/s/<token>` (resolved
   to an asset on the server, revealing nothing to the author),
   `ics://asset/<slug>[/file/<path>]`, and the new wikilink `[[ics:<slug>]]`,
   `[[ics:<slug>/file.md#heading|alias]]`.
2. Keep every live (not deleted) target, whoever wrote the version. An extracted edge is a
   fact about the text, not a claim by a person, so the same text always yields the same
   edges; access is applied when the graph is read (section 5). Amended 2026-10-01: the
   first version kept only targets the author could see, which made the graph depend on
   who wrote or scanned last, and a write by an editor with less access erased edges its
   author had made.
3. In the version transaction, bring this source's `extracted` edges in line with the new
   set. Manual, agent and integration edges are untouched.
4. `app/markdown.py` renders `[[ics:...]]` as a normal link to `/v/<slug>`; the change to
   `markdown.py` invalidates the render cache by itself (ADR-0006).

Extracted edges are always `references`. HTML bundles are handled in a second step (the
security scanner already parses `href`).

**Rescan** (added 2026-10-01). Content stored before extraction existed has no extracted
edges until its next version. `POST /api/assets/{id}/relations/rescan`
(`ics_asset_rescan_relations`) runs the same extraction on the current version without a
new one. It needs `editor` on the source. The edges do not depend on the caller, but the
`added` and `removed` it answers and audits (`relations_rescanned`) count only targets the
caller can see: otherwise a rescan would tell whether a slug written into the text belongs
to a document the caller cannot open. The operator backfill
`python -m app.cli relations-rescan` runs it for every live asset.

Manual and agent edges keep the rule of section 5: they are a person's claim and need the
target to be visible to that person.

**Neighbourhood `skipped`.** The default neighbourhood follows strong types only, so a
document whose relations are all content links looked isolated. The response names the
root's edges per type outside `types`, counting only edges whose other end the caller can
see and that is not already in the result.

### 5. Graph access

Content access and graph access are different. Relations, task links (ADR-0018), the
neighbourhood, the context pack (ADR-0019) and the project map are available only to users
with **graph access** to the asset:

| Source of the user's role on the asset | Effective role | Reads content | Graph access |
|---|---|---|---|
| System admin (browser session or OAuth token, e.g. MCP) | `owner_file` | yes | yes |
| File owner | `owner_file` | yes | yes |
| Member of the asset's home project, role `owner` | `project_owner` | yes | yes |
| Member of the home project, role `editor` | `editor` | yes | yes |
| Member of the home project, role `viewer` | `viewer` | yes | yes |
| Member (any role) of a project the asset is assigned to (ADR-0017) | `viewer` or `editor` | yes | yes |
| Direct `AssetShare` with role `editor` | `editor` | yes | yes (editor from any source) |
| Direct `AssetShare` with role `viewer`, and no other source | `viewer` | yes | **no** |
| Guest of a `/s/<token>` share link | none | that document only | **no** |
| No source | none | no | no |

A viewer with only a direct share was given one document, not its neighbourhood; the graph
would show them titles and summaries of related documents they were never pointed to. A
share link guest sees the `summary` of the shared document (it has the same sensitivity as
the content) but no relations. A personal access token of an admin gets no admin bypass
(ADR-0020), so it has graph access only through the other rows.

Rules built on the table:

- No graph access to the asset asked about: `404 asset_not_found`, byte for byte the same as
  for a missing asset.
- An edge is returned only when the other end is **visible** to the viewer (any row of the
  table with "reads content: yes" except the link guest). Otherwise the edge does not exist
  for that viewer, and no count of hidden edges is shown.
- The neighbourhood BFS includes visible nodes but **expands only nodes where the viewer has
  graph access**. A node visible through a direct viewer share appears as a leaf.
- Adding an edge requires `editor` on the source and visibility of the target; an invisible
  target gives `404 asset_not_found`. Deleting requires `editor` on the source or the target
  and visibility of both ends, otherwise 404.
- An edge stays in the database when a user loses access; it only disappears from their
  responses. Otherwise a change of sharing would irreversibly erase graph data.
- `freshness=superseded` applies only when the successor is visible to the viewer
  (ADR-0015).

The predicate lives in `permissions.py` next to `effective_role` and `visible_assets_filter`
and joins the visibility parity test.

### Worked example: an edge between two projects

- Project **Acme** holds "Booking module: UX design" (D, home project Acme).
- Project **Platform** holds "Platform architecture" (R, home project Platform).
- Anna is a member of both projects. Bartek is an editor in Acme only. Celina is a viewer in
  Platform only. Dawid has a direct viewer share on D. Eve has a `/s/` link to D.

1. Anna adds `D depends_on R`: she is an editor on D and sees R, so the edge is created with
   `origin=manual`.
2. Bartek tries to add the same edge: he is an editor on D but cannot see R, so he gets
   `404 asset_not_found`, the same answer as for a slug that does not exist.
3. Bartek opens D's relations: he has graph access to D, but R is invisible to him, so the
   list is empty. Nothing says an edge was hidden.
4. Celina opens R's relations: she has graph access to R (project viewer), but D is
   invisible to her, so the incoming `required_by` edge is not shown.
5. Anna opens D's neighbourhood with depth 2: D, then R, then R's own neighbours that Anna
   can see, because she has graph access to R through Platform.
6. Dawid asks for D's relations: 404. He can read D, but a direct viewer share gives no
   graph access.
7. Eve sees D and its summary through the link, and no relations at all.
8. Platform later assigns D to itself as a viewer (ADR-0017). Celina now sees D and has
   graph access to it, so she sees the edge from both ends. Bartek still does not see R.

### 6. Traversal: BFS per level, ACL at every step

Not a recursive CTE: a CTE with a path array enumerates paths, not nodes (millions of rows
at depth 3 with 200 edges per node), and an `OR` join hits no index. Instead
`services/relations.py` runs one query per level:

```python
visited, frontier = {start_id}, {start_id}
for depth in range(1, max_depth + 1):                  # max_depth <= 3
    rows = edges_touching(frontier, types)             # UNION ALL of source-side and target-side lookups
    candidates = {other_end(r, frontier) for r in rows} - visited
    visible = await visible_ids(session, user, candidates)
    expandable = await graph_access_ids(session, user, visible)
    edges += [r for r in rows if both_ends_in(r, visited | visible)]
    visited |= visible
    frontier = expandable
    if len(visited) >= max_nodes or not frontier:      # max_nodes <= 200
        break
```

Each query hits an index (`uq_asset_relation` for the source side,
`ix_asset_relations_target` for the target side). A path through an invisible document does
not exist. The node limit cuts by depth first (nearer neighbours win) and within a level by
relation type weight. By default the neighbourhood follows the strong types
(`derived_from`, `depends_on`, `supersedes`, `part_of`, `contradicts`); `references`,
`relates_to` and `duplicates` on request.

### 7. `target_version` and `basis_changed`

An edge stores the target's version when it was made. When the target gets a newer version,
the API returns `target_changed: true` and `target_version_now` on the edge, and the source
gets the `basis_changed` flag for `derived_from` (ADR-0015). An agent can diff the target
between the two versions and, if the source is still valid, refresh the edge
(`PATCH /api/relations/{id}` with `refresh_target_version`), which clears the flag.

### 8. Cycles

`supersedes` and `part_of` must not form cycles. The check runs only in the subgraph visible
to the user making the change, so a `relation_cycle` refusal cannot reveal a hidden path.
Hidden cycles can therefore exist; freshness computation and BFS keep a visited set and are
safe against them. Other types may form cycles freely.

### 9. Limits and errors

| Limit | Value | Error |
|---|---|---|
| Edges per asset | 200 | `relation_limit` |
| Neighbourhood depth | 3 | validation |
| Nodes per response | 200 | truncated, with a hint |
| Summary in the compact shape | 200 characters | cut with an ellipsis |
| Note | 500 characters | validation |

Error codes: `relation_self`, `relation_exists`, `relation_type_invalid`, `relation_limit`,
`relation_cycle`; invisible ends give `asset_not_found`. All go to `docs/api-errors.md` and
`frontend/src/lib/errorMessages.ts`.

API: `GET /api/assets/by-slug/{slug}/relations`, `POST /api/assets/{id}/relations`,
`PATCH/DELETE /api/relations/{id}`, `GET /api/assets/by-slug/{slug}/neighbourhood`,
`GET /api/projects/{slug}/graph` (the project map: the project's documents where the viewer
has graph access, the edges between them and edges to other visible documents).

Estimate (phase 2, graph part): about 4 days backend, 4 days frontend, 1.5 days `ics-mcp`.

### 10. Compact shape for agents

Measured on the demo projects (September 2026), one verbose edge was about 380 characters
(three UUIDs, six nulls, two version numbers, `created_at`), edges took 76-87% of an
outline, and the 8000-character MCP limit cut a `depth=2` neighbourhood down to the nine
nodes of `depth=1`. Agents get a compact shape instead; the verbose shape stays the default
of the REST endpoints, which the web client reads.

- **Opt-in by parameter.** `shape=compact` on `GET .../relations`, `.../neighbourhood` and
  `.../outline` (the outline also takes `edges=false` to leave relations out). The context
  pack (ADR-0019) is compact only. The shaping is done in ICS, not in `ics-mcp`, so the pack
  and the graph endpoints share one serializer (`services/graph_compact.py`) and the pack's
  budget measures what the agent gets. `ics-mcp` asks for the compact shape by default and
  offers `detail="full"`.
- **Nodes keyed by slug**, no ids: `title`, then only what carries a decision: `kind` when
  not `md_single`, `doc_type`, `freshness` when not `current`, `superseded_by` as the
  successor's slug, `summary` cut to 200 characters, `estimated_tokens`; the neighbourhood
  adds `depth` and `expandable: false` for a leaf. Outline nodes carry no summary. The pack
  keeps its documents as an ordered list, because the order is the reading order.
- **Edges as triples** `[from, type, to]` in the stored direction, with a fourth element
  holding only what is set: `id` (relation list and single edge: what update and remove take),
  `source_path`, `target_path`, `target_anchor`, `note` and `changed`
  (`[recorded target version, current version]`). No nulls, no `origin`, no `created_at`.
- **Content links folded.** An extracted `references` edge between two documents that
  another edge already joins (either direction, any other type or origin) is left out: the
  link in the text is how the author expressed that relation. The verbose shape keeps both.
- **Neighbourhood direction.** `direction=out|in|both` on the neighbourhood follows only
  edges leaving or arriving at each expanded node (symmetric edges both ways), so the root
  of a `derived_from` chain is one call.
- **One edge.** `GET /api/relations/{id}` returns `{"edge": [from, type, to, {"id", ...}],
  "nodes": {slug: node}}` with both ends as outline nodes (no summary), from the same
  builders. It answers when the edge shows in the relation list of one of its ends: graph
  access to that end and the other end visible; anything else, a hidden end included, is
  `relation_not_found`, like a missing edge. `POST /api/assets/{id}/relations` and
  `PATCH /api/relations/{id}` return the same shape with `shape=compact`, so an agent gets
  the slugs and the `id` of what it wrote without a second call.
- **Outline sections.** Every heading gets `end_line` on read (computed from the stored
  outline, so outlines stored before the field existed carry it too), which lets a client
  read one section by anchor.

## Reactivation trigger

- More than about 100 thousand edges, or neighbourhood queries above 100 ms at p95: revisit
  batching or a materialised adjacency, then graph extensions.
- A need for graph algorithms (centrality, communities) in the product: re-evaluate Apache
  AGE.
- Wrong `supersedes` edges hiding current documents in practice: consider a confirmation
  step for that one type.
- A request to expose relations through share links: a separate decision on what a guest may
  see.

## Consequences

- Every read of relations, neighbourhood, task links, context pack and project map goes
  through the graph access predicate as well as visibility; the parity test covers the new
  queries.
- The same edge can look different to two users; responses never include counts of hidden
  edges.
- Extraction adds work to every content write, bounded by the edge limit and done in the
  version transaction.
- The `relations` routes start as a package (`_router.py`, `asset_relations.py`,
  `graph.py`) to stay under the 500 LOC budget.
- `ics-mcp` gains five tools and a plugin release.
- The frontend bundle budget (`frontend/scripts/check-bundle.mjs`) goes from 160 to 170
  JS files: six lazy views (project map, hygiene, task agent view, access tokens, admin
  doc types, mini graph) and seven small chunks the bundler splits out because several
  of those views share them (graph engine, card scene, project tabs, API and query
  helpers). No eager chunk grew; merging the views would break the lazy-view rule.

## References

- ADR-0006 (render cache), ADR-0015 (freshness), ADR-0017 (project shares),
  ADR-0018 (task links), ADR-0019 (context pack), ADR-0020 (PAT without admin bypass).
