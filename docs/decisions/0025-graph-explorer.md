# ADR-0025: Graph explorer, an incremental walk through the document graph

**Status:** Accepted, 2026-10-06.
**Scope:** `frontend/src/views/GraphExplorer/`, route `/graph`.

## Context

The relation graph (ADR-0016) is shown in two places: the project map (one
project, laid out whole) and the mini graph in the reader's side panel (one
document, depth 1 or 2, in a narrow column). Neither lets a reader follow
relations across projects, and the mini graph gets cramped past a dozen
neighbours.

## Problem

Give a signed-in user one full-screen view in which they can wander through
every document they can read, starting from their projects or from one
document, without loading a whole graph that can have thousands of nodes and
without showing anything the permission checks would hide.

## Decision

1. **One view, two start points.** `/graph` starts from the user's projects;
   `/graph?doc=<slug>` starts from one document, opened one level deep. The
   reader can link to the second form instead of growing the mini graph.
2. **Data per expansion, from the existing endpoints.** Expanding a document
   calls `GET /neighbourhood?depth=1` with every relation type; expanding a
   project calls `GET /projects/{slug}/graph`. Both keep their React Query
   keys, so the mini graph and the project map share the cache. No new
   endpoint: the backend already filters by the viewer at read time, and a
   node the viewer cannot expand arrives with `expandable: false`.
3. **A tree, not a force layout.** A node belongs to the expansion that
   found it first; every other relation between cards on the canvas is a
   quiet cross edge. The layout is a tidy tree, left to right, with children
   in insertion order, so cards the reader has already seen stay in place
   when something new appears. It is a pure module on the shared card engine
   (`components/graph`), no new graph library.
4. **Limits as named constants.** At most `CHILD_PAGE` (12) children per
   node, the rest behind a "+N more" card. At most `MAX_CARDS` (500) cards
   in the browser: past it the least recently used expanded branches that do
   not hold the selection are collapsed and the reader is told. The data of
   a collapsed branch stays in the query cache for a quick re-expand.

Options considered: a server endpoint that walks several levels at once
(rejected: the neighbourhood endpoint with depth 1 is enough and is cached
per document); the existing layered layout per step (rejected: it reorders
the whole scene on every expansion).

### Search: walking to a document

A search field over the canvas finds documents among the loaded cards and in
ICS (`/api/assets/search`). Picking one that is not on the canvas does not
start a new graph: `POST /api/assets/by-slug/{slug}/path` returns the shortest
walk (at most 6 hops, over the relation types in the filter) from a document
or a project already on the canvas, and the explorer expands its steps in
order, pins them past the "more" cards and selects the result. The search is
breadth-first from the target, one statement per level, and every hop before
the target needs graph access, the rule the neighbourhood applies before it
expands a node, so a path never leads through a document the reader cannot
open. Projects the caller is not a member of are ignored. A POST because the
ids of up to 500 cards do not fit a URL. When no walk exists the reader is
told and may start a graph from the result instead.

Options considered: walking in the browser with one neighbourhood call per
level (rejected: many round trips and no shortest path); opening the result
as a new graph (rejected: the reader loses the context they built).

## Reactivation trigger

Revisit when readers ask for paths between two given documents, when 6 hops
turn out too few, or when 500 cards turn out too few or too many in practice.

## Consequences

- One more lazy chunk: the bundle budget in `frontend/scripts/check-bundle.mjs`
  goes from 175 to 176 JS files.
- The legend of relation types moved to `components/graph/RelationLegend.tsx`,
  shared by the project map and the explorer.
- `POST /api/assets/by-slug/{slug}/path` (`services/graph_path.py`) is a
  new read endpoint; it reuses the relation indexes of the neighbourhood.
