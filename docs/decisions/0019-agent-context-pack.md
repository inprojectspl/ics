# ADR-0019: Agent context pack (ordering, budget, freshness signals)

**Status:** Accepted, 2026-09-26. Implemented (phase 3 of the document graph work).
**Decision owners:** Owner.
**Scope:** `GET /api/context`, `backend/app/services/context_pack.py`, the rate limiter
configuration, structured logging, and the `ics-mcp` tool `ics_task_context` (plus the PS
`task_start` hint and, later, the `IcsLive` block, which live in the PS repository).

## Context

ADR-0015 gives every document a summary, a type, a computed freshness and a token estimate.
ADR-0016 connects documents with typed relations. ADR-0018 links documents to OpenProject
work packages and marks some links as `required`. None of this helps an agent unless it gets
it in one call, in a form it can use without thinking, and without burning its context on
documents it does not need.

The agent works in a PS loop. At `task_start` PS knows the work package, its ancestors (from
the vault hierarchy, which ICS does not have) and the OP project. The agent needs a map
first, then decides which outlines and fragments to read.

## Problem

1. What the context pack takes as input and returns.
2. How documents are ordered, and what is cut when the response exceeds its budget.
3. How superseded documents, changed bases and hidden documents are shown.
4. How the endpoint avoids becoming a side channel or a load problem.

## Decision

### Principles

1. **Map first, terrain later.** The pack lists documents with summary, type, freshness and
   cost. Content is fetched separately and only the needed part.
2. **Freshness in every entry.** An agent never sees a document without `freshness`; a
   superseded document always points at its successor.
3. **Cost is explicit.** Every document has `estimated_tokens` (the same estimator as the
   agent view) and `has_outline`.
4. **The agent decides.** The pack does not tell the agent to read everything; it gives
   node metadata, and the agent decides whether to open a document or follow the graph.
5. **The user's permissions.** The agent sees what the person it acts for sees, and only
   documents where that person has graph access (ADR-0016).
6. **Content is data, not instructions.** The tool description says so explicitly.

### Options

| Option | Evaluation | Verdict |
|---|---|---|
| A. Agent composes the map itself from `ics_asset_external_refs`, `ics_asset_relations`, `ics_asset_meta` | 5 to 20 calls per task, each with its own permission check; ordering and inheritance reinvented in every skill | rejected |
| **B. One server-side context pack with a token budget** | one call, deterministic ordering, one place for permissions and truncation | **chosen** |
| C. Full document content in the pack | exceeds any sensible budget; defeats "map first" | rejected |
| D. PS mirrors ICS metadata into its vault | stale data, permissions frozen at pull time, another sync mechanism | rejected |

### Input: `GET /api/context`

| Parameter | Description |
|---|---|
| `system` | `openproject` (default) or `project_standard` |
| `wp` | OP work package id, or a PS node id for local nodes (ADR-0018) |
| `ancestors[]` | ancestors of the task, nearest first |
| `project` | OP project identifier or ICS project slug |
| `depth` | 0 to 2, graph steps from the task's documents (default 1) |
| `budget_tokens` | size budget of the response, default 1800, max 4000 |
| `include[]` | `deliverables` (add documents the task and its ancestors produced), `references` (also follow weak edges: `references`, `relates_to`, `duplicates`) |

The budget covers the whole response: documents, edges, warnings and the truncation note,
estimated with the JSON rule `tokens_for_json` in `app/token_estimate.py`: every string by
the prose rule of document estimates, slugs and other identifiers at 1.5 characters per token,
punctuation at 4. Calibrated against cl100k on real packs, it overcounts by 4-6% (the
whole-text prose rule undercounted them by about 20%, so a budget of 600 gave 623 tokens),
which keeps a pack within its budget. The response states its own size in
`estimated_tokens`. `ics_task_context` passes the pack through unchanged and raises its
response limit to the pack's own size, so a budget above the general 8000-character limit is
not cut twice.

### Ordering

Documents are ordered by the list below. Within a group, direct links come before inherited
ones and a nearer ancestor before a farther one.

1. Documents linked with `required = true` (any role except `deliverable`).
2. `context` documents linked directly to the task.
3. `context` documents inherited from ancestors, nearer ancestor first.
4. Project key documents, only when the task has fewer than 3 `context` documents in total
   (direct and inherited).
5. `reference` documents linked to the task itself: a document someone linked to the task
   always comes before graph neighbours, so a tight budget cuts neighbours first.
6. Graph neighbours of the documents in groups 1-4, up to `depth`: `depends_on` and
   `contradicts` (cheap to list, costly to miss) before `derived_from` before the rest.
7. `reference` documents inherited from ancestors.
8. `deliverable` documents of the task and its ancestors, only with `include=deliverables`.

A document reachable in several ways appears once, at its best position, with every way in
`via`. A `direct` or `inherited` item carries the link's `label` and `note` when they are set:
the reason for a link ("the API contract, do not start without it") often says more than its
role.

### Budget and truncation

The server estimates the response size and cuts from the end of the list. Neighbours are cut
before linked documents. The greedy pass charges each document with its own warnings and its
edges to documents already listed; a second pass measures the assembled response and drops
more from the end until it fits. `truncated` is data, not advice: the number of cut
`documents` and `neighbours`, `needed_tokens` (the size of the uncut pack),
`max_budget_tokens` and, when neighbours were cut, a listed `seed` to explore with
`ics_graph_neighbourhood`. Clients word the next step themselves (a larger budget while
`needed_tokens` fits the maximum, otherwise the seed or a narrower request).
**Required documents are never truncated**, even if they
alone exceed the budget: a mandatory user story or mockup description missing from the map
is worse than an oversized response.

### Superseded documents

A superseded document (ADR-0015: a visible successor exists) collapses to one line: its
slug, title, `freshness: "superseded"`, `collapsed: true` and `superseded_by` as the
successor's slug (the compact shape, ADR-0016 section 10). It takes almost no budget. The
successor takes the superseded document's place in the ordering and inherits its `required`
flag, so replacing a mandatory specification with a new one keeps it mandatory without
relinking. If the successor is already in the list, it moves up to the better position.

### Other signals

- The pack uses the compact graph shape (ADR-0016, section 10). An entry has `slug`,
  `title`, `version` and `via`, and only when set: `summary` (200 characters), `doc_type`,
  `kind` (not `md_single`), `freshness` (not `current`), `flags`, `required: true`,
  `estimated_tokens` and `has_outline: false`. No `ref` (it is `ics://asset/<slug>`) and
  no `content_updated_at`.
- `doc_types`: the agent hint of each document type among the listed documents, once per
  type instead of on every entry. The budget charges a hint with the first entry of its
  type.
- `flags`: `basis_changed` (a `derived_from` target or a link's `pinned_version` moved on)
  and `summary_stale`. An overdue review shows as `freshness: "review_overdue"`.
- `edges` between listed documents as `[from, type, to]` triples, with
  `{target_anchor, target_path, note, changed}` only when set; `changed` is
  `[recorded target version, current version]`. A `references` edge extracted from a link
  in the text is left out when another edge joins the same two documents.
- `warnings`: a list of `{code, params}`, worded by the client like scanner findings:
  `superseded` (`slug`, `successor`, `required`), `basis_changed` (`slug`), `contradicts`
  (`from`, `to`) between listed documents, `project_unmapped` (`project`) and
  `task_unlinked` (`system`, `wp`) when no document the caller can see is linked to the task
  or its ancestors, even when project key documents fill the pack (a mistyped work package
  number would otherwise look like a normal pack).
- No ready-made tool calls: an entry gives `slug` and `has_outline`, and each client names
  its own read tools.

### Access and side channels

- The pack contains only documents where the caller has graph access (ADR-0016); edges only
  when both ends are listed.
- No accessible document gives an empty `documents` list with status 200, not 404. The
  endpoint cannot be used to learn whether anything is linked to a task.
- `hidden_count` (the number of linked documents the caller cannot see) is present only for
  owners of the ICS project mapped to the task's OP project. For everyone else the field does
  not exist, not even as 0.
- An unmapped OP project gives a pack without key documents and a `project_unmapped`
  warning.
- `task_unlinked` counts only documents with graph access, so a task whose links are all
  hidden gets the same warning as a task with no links.

### Load and observability

- Rate limit 120 requests per minute per user: an agent loop has no reason to ask more
  often.
- Reads are not audited (the audit log is not an access log). Each response logs one
  `structlog` event `context_pack_served` with `transport` (`cookie`, `bearer`, `pat`), the
  number of documents, neighbours and hidden documents, the estimated size and whether it was
  truncated. No titles, summaries or content in the log.

### Example response

Request:
`GET /api/context?system=openproject&wp=4711&ancestors=4700,4650&project=acme-portal&depth=1`

```json
{
  "project": {"slug": "sffyr92muy", "name": "Acme", "external": "acme-portal"},
  "task": {"system": "openproject", "wp": "4711", "ancestors": ["4700", "4650"]},
  "doc_types": {
    "requirements": "The source of acceptance criteria.",
    "business_goals": "Read before any design or scoping work."
  },
  "documents": [
    {
      "slug": "r3t5y7u9",
      "title": "User story: book a tool with conflict check",
      "summary": "As a site manager I book a tool for a date range and see a clear conflict message.",
      "doc_type": "requirements",
      "version": 2,
      "required": true,
      "via": [{"kind": "direct", "role": "context", "required": true,
               "note": "Acceptance criteria for this task"}],
      "estimated_tokens": 900
    },
    {
      "slug": "z1x7c3vb",
      "title": "Booking API: specification v2",
      "summary": "Endpoints, payloads and error codes of the booking API.",
      "doc_type": "specification",
      "version": 3,
      "required": true,
      "via": [{"kind": "successor_of", "slug": "a4s5d6fg", "required": true}],
      "estimated_tokens": 9400
    },
    {
      "slug": "a4s5d6fg",
      "title": "Booking API: specification v1",
      "freshness": "superseded",
      "collapsed": true,
      "superseded_by": "z1x7c3vb",
      "required": true
    },
    {
      "slug": "k2j9h4gf",
      "title": "Booking module: UX design",
      "summary": "Screens and flows of the booking module, including conflict states.",
      "doc_type": "design",
      "version": 7,
      "flags": ["basis_changed"],
      "via": [{"kind": "inherited", "wp": "4700", "role": "context", "required": false}],
      "estimated_tokens": 5800
    },
    {
      "slug": "q8w3er5t",
      "title": "Acme business goals 2026",
      "doc_type": "business_goals",
      "version": 4,
      "freshness": "review_overdue",
      "flags": ["summary_stale"],
      "via": [{"kind": "inherited", "wp": "4650", "role": "context", "required": false}],
      "estimated_tokens": 2100
    },
    {
      "slug": "t6y7u8io",
      "title": "Acme architecture",
      "doc_type": "design",
      "version": 5,
      "via": [{"kind": "neighbour", "from": "z1x7c3vb", "type": "depends_on"}],
      "estimated_tokens": 7300
    }
  ],
  "edges": [
    ["k2j9h4gf", "derived_from", "q8w3er5t", {"changed": [2, 4]}],
    ["z1x7c3vb", "derived_from", "k2j9h4gf"],
    ["z1x7c3vb", "supersedes", "a4s5d6fg"],
    ["z1x7c3vb", "depends_on", "t6y7u8io", {"target_anchor": "data-layer"}]
  ],
  "warnings": [
    {"code": "superseded",
     "params": {"slug": "a4s5d6fg", "successor": "z1x7c3vb", "required": true}},
    {"code": "basis_changed", "params": {"slug": "k2j9h4gf"}}
  ],
  "truncated": {"documents": 0, "neighbours": 2, "needed_tokens": 1900,
                "max_budget_tokens": 4000, "seed": "r3t5y7u9"},
  "hidden_count": 1,
  "estimated_tokens": 1240
}
```

`hidden_count` appears here because the caller owns the ICS project mapped to
`acme-portal`; for any other caller the key is absent.

Estimate: about 1.5 days backend and 0.5 day `ics-mcp`, within phase 3.

## Reactivation trigger

- Agents regularly ask for more neighbours than the default budget allows: raise the default
  or add per project defaults.
- Measured usage shows agents ignore the pack (fewer than 90% of `task_start` followed by a
  context call, from `context_pack_served`): move to the embedded `IcsLive` block in PS
  (ADR-0020 tokens).
- Rate limit hits in normal loops: revisit 120 per minute.
- Semantic search arrives: consider a "related by content" group after neighbours.

## Consequences

- One endpoint concentrates the ordering rules; skills and PS only render its output.
- Required documents can push a response above the budget; `ics-mcp` must tolerate that.
- The response depends on the caller: two team members can get different packs for the same
  task, which is correct and expected.
- `context_pack_served` gives usage metrics without Prometheus (the project does not
  use Prometheus) and without logging document data.

## References

- ADR-0015 (freshness, flags), ADR-0016 (graph access, BFS), ADR-0018 (task links,
  `required`), ADR-0020 (personal access tokens).
