# ADR-0015: Asset metadata model (columns vs JSONB, doc type vocabulary, computed freshness)

**Status:** Accepted, 2026-09-26. Not implemented yet (phase 1 of the document graph work).
**Decision owners:** Owner.
**Scope:** new columns on `assets` and `asset_versions` (`backend/app/models/assets.py`),
new table `doc_types`, the `search_tsv` generated column, `PATCH /api/assets/{id}/meta`,
`GET /api/doc-types`, `POST/PATCH /api/admin/doc-types`, the asset projections
(`AssetIndexItem`, `AssetSummary`, `/meta`, `/outline`), `/index` and `search-mcp` filters,
and the `ics-mcp` tools `ics_asset_set_meta` and `ics_doc_types`.

## Context

ICS holds about 240 documents (Markdown notes, collections, HTML bundles, PDFs, Office
documents). An asset has a title, tags, a kind, a project and versions, but nothing that
tells a reader, human or agent, what the document is, whether it can be relied on, who
answers for it, or when its content (not its row) last changed. `updated_at` moves on any
row write, including a tag change, so it cannot answer "when did the text change".

The main new consumer is an agent working through Project Standard (PS) tasks. It must
decide what to read before reading it: every full read of a 9k token specification costs
context. The document graph work (ADR-0016 to ADR-0019) builds on this metadata; this ADR
settles the model itself.

## Problem

1. Which fields exist, and which of them are typed columns versus free JSON.
2. How document types are defined, labelled in two languages and extended without a
   deployment.
3. Whether documents get a lifecycle status (draft, in review, approved, archived) and an
   approval workflow.
4. How "can I rely on this document" is expressed so that an agent does not have to combine
   five fields itself.
5. How the new fields take part in full text search.

## Decision

### 1. Storage: typed columns plus one `properties` JSONB

A field that system logic depends on (filters, freshness, permissions, indexes) is a typed
column. A field that is only informative and specific to one document type goes to
`properties` JSONB, validated against the JSON Schema of the asset's doc type.

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. Columns plus `properties` JSONB** | types and indexes where logic needs them; mypy and Pydantic see the fields; flexible for type-specific data | a migration for every new system field (rare) | **chosen** |
| B. Everything in JSONB | no migrations | no types, expression indexes for everything, key sprawl | rejected |
| C. EAV table (`asset_attributes`) | unlimited freedom | queries several times more expensive, hard validation, no types | rejected |
| D. Separate 1:1 `asset_metadata` table | lighter `assets` row | a JOIN on every list; `summary` can be deferred on `assets` anyway | rejected |

Fields on `assets`:

| Field | Type | Written by | Purpose |
|---|---|---|---|
| `summary` | `Text`, max 1000 characters, deferred | human or agent | 1-3 sentences on what the document is and what it is for; first item of every agent projection |
| `summary_source` | `human` \| `agent` | system | who wrote the summary; informational only |
| `summary_version` | `Integer` | system | content version the summary was written for |
| `doc_type` | `String(32)`, FK to `doc_types.key`, nullable | human or agent | kind of content (business goals, requirements, design, ...) |
| `maintainer_id` | FK `users`, `SET NULL`, indexed | human | person responsible for the content; defaults to the owner |
| `content_updated_at` | `TIMESTAMPTZ` | `commit_new_version` | when the content last changed |
| `content_updated_by` | FK `users`, `SET NULL` | `commit_new_version` | who changed it |
| `review_due_at` | `TIMESTAMPTZ`, nullable | human or the doc type rule | date after which the document needs a review |
| `reviewed_at`, `reviewed_by` | | "still current" action | review without a content change |
| `language` | `String(8)`, nullable | detection at write time or human | language of the document |
| `properties` | `JSONB`, default `{}`, max 16 KB | human or agent | type-specific fields |

On `asset_versions`: `change_note` (`Text`, nullable), the equivalent of a commit message,
set from the UI and from the MCP `change_note` parameter, so an agent can ask "what changed
since v3" without a diff.

**`content_updated_at` vs `updated_at`.** `updated_at` stays the technical timestamp of a
row write. Every "last changed" shown in the UI and in MCP moves to `content_updated_at`,
which only `commit_new_version` sets. The migration backfills it with
`max(asset_versions.created_at)` per asset. The `updated_since` filter in `/index` and
`ics_assets_list` changes meaning accordingly; the change goes into the CHANGELOG of both
repositories, and the old meaning stays available as `touched_since`.

### 2. Doc type vocabulary: a table, labels stored in the table

`doc_types` is an organisation-wide table managed by admins:

| Column | Description |
|---|---|
| `key` | primary key, snake case (`business_goals`, `requirements`, `design`, ...) |
| `label_pl`, `label_en` | display name; the UI falls back to `label_en`, as `t()` does |
| `agent_hint` | one English sentence for an agent: when this type matters ("Read before any design or scoping work.") |
| `default_review_days` | review period after a content change (e.g. policy 365, runbook 180, notes null) |
| `properties_schema` | JSON Schema for `properties` |
| `position` | order in the UI |
| `archived_at` | retires a type without deleting it; existing assets keep it, new ones cannot pick it |

The labels are **data, not UI text**. Admins add types in a running system, while the i18n
catalogues of ADR-0010 and ADR-0011 change only with a deployment. That is why they are
columns and not catalogue keys; both ADRs carry a note pointing here. Only the fixed UI
around the vocabulary (the "Document type" field label, the admin screen) goes through the
catalogues.

| Option | Verdict |
|---|---|
| **Table with `label_pl`/`label_en`** | chosen: editable at runtime, one row carries labels, hint, review rule and schema |
| Keys in the i18n catalogues, types in code | rejected: every new type needs a deployment |
| Tags | rejected as the type mechanism: a tag is a free label, a type has semantics (agent hint, review period, schema). Tags stay for free grouping |
| Per project vocabulary | rejected for now: the same type means the same thing in every project, and agents rely on stable keys |

The starting vocabulary has 14 types (`business_goals`, `requirements`, `design`,
`specification`, `decision`, `research`, `report`, `meeting_notes`, `contract`, `offer`,
`manual`, `runbook`, `policy`, `presentation`), to be trimmed with project owners. The
frontend treats `DocType` as a `string` from the API, not a union.

### 3. No lifecycle status and no approval workflow

A document either exists or it does not. There is no `lifecycle_status` column, no
`draft`/`approved` states and no version approval. The analysis proposed a nullable status
and a later approval phase; the owner rejected both on 2026-09-26:

- a status nobody maintains is worse than none: about 240 existing documents would become
  either "draft" (an agent would ignore them) or "unknown" (no information);
- the question an agent actually needs answered is "is there something newer" and "is this
  past its review date", both of which follow from relations and dates;
- an approval flow is a separate product (who approves, per type lists, notifications) with
  no current demand.

The planned ADR-0021 (document approval workflow) is therefore not written. Reviews stay
one action: "still current" sets `reviewed_at`/`reviewed_by` and moves `review_due_at` by
the doc type's `default_review_days`.

### 4. Freshness is computed at projection time

The backend computes `freshness` for every projection of an asset, for the viewer asking.
There is no column to keep in sync. The first matching rule wins:

| `freshness` | Condition | What an agent does |
|---|---|---|
| `superseded` | a `supersedes` relation (ADR-0016) points at this asset and its successor is visible to the viewer | moves to the successor (`superseded_by` in the response, `latest` for the newest visible document of the chain) |
| `review_overdue` | `review_due_at < now()` | reads it, notes the risk in the task log |
| `current` | otherwise | relies on it |

A successor the viewer cannot see does not make the document superseded for that viewer;
otherwise the flag would confirm that a hidden document exists. The `freshness` list filter
(`/api/assets/index`, `search-mcp`) applies the same order, so `review_overdue` never lists
a superseded document.

Flags next to `freshness`, because they do not exclude it:

- `summary_stale`: `summary_version < version`, the summary may describe an older content;
- `basis_changed`: a `derived_from` relation of this asset points at a target whose version
  moved past the edge's `target_version` (ADR-0016).

`summary_source` is informational. A write through an MCP token sets `agent`, an edit in the
UI sets `human`. There is no confirmation flow and nothing is hidden or down-ranked because
of it; the UI shows a small "written by an agent" marker.

### 5. Search: weighted `search_tsv` via `SET EXPRESSION`

The generated column becomes

```sql
setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
setweight(to_tsvector('simple', coalesce(summary, '')), 'A') ||
setweight(to_tsvector('simple', ics_immutable_array_to_string(tags, ' ')), 'B') ||
setweight(to_tsvector('simple', coalesce(search_content, '')), 'C')
```

`array_to_string` is not `IMMUTABLE`, so tags go through a wrapper function marked
`IMMUTABLE`. Production runs PostgreSQL 17 or newer, so the migration changes the existing
column with `ALTER COLUMN search_tsv SET EXPRESSION AS (...)` and rebuilds the GIN index;
no drop and re-add of the column. The `simple` configuration stays (Polish and English
documents, predictable without stemming).

New filters in `/index` and `search-mcp`: `doc_type[]`, `freshness[]`, `tag[]` (also in
`search-mcp`, which has none today) and `maintainer`. Indexes: `(project_id, doc_type)
WHERE deleted_at IS NULL`, `(review_due_at) WHERE review_due_at IS NOT NULL`; a GIN
`jsonb_path_ops` index on `properties` only when a filter on a property appears.

### API and errors

- `PATCH /api/assets/{id}/meta` (editor or higher): `summary`, `doc_type`, `maintainer_id`,
  `review_due_at`, `language`, `properties`.
- `POST /api/assets/{id}/reviewed` (editor or higher).
- `GET /api/doc-types` (signed in), `POST/PATCH /api/admin/doc-types` (admin).
- New error codes `doc_type_unknown` and `metadata_invalid` (with `field`), added to
  `docs/api-errors.md` and `frontend/src/lib/errorMessages.ts`.
- Audit actions `asset_metadata_updated` (changed field names, not the summary text),
  `asset_reviewed`, `doc_type_created`, `doc_type_updated`.

Estimate (phase 1): about 3.5 days backend, 3 days frontend, 1.5 days `ics-mcp`.

## Reactivation trigger

- Teams ask for sign-off of a specific version (contracts, policies): write an approval ADR
  and revisit "no lifecycle status".
- Projects need their own document types: add a nullable `project_id` to `doc_types`.
- Search quality in Polish becomes a complaint: evaluate a Polish stemming configuration or
  semantic search as a separate decision.
- A filter on a `properties` field appears: add the GIN index.

## Consequences

- Migrations only extend the schema (nullable columns or `server_default`), so the previous
  image still runs on the new schema (`ICS_SKIP_MIGRATIONS`, rollback).
- Every projection that shows an asset to an agent includes `freshness`, which needs the
  `supersedes` lookup for the viewer; it is one indexed query per page of results.
- No stored status means nothing to backfill and nothing to go stale, but also no way to
  mark a document as "not binding yet" other than its summary or a `supersedes` relation.
- Doc type labels are not covered by the i18n parity tests; the admin form requires both
  labels instead. The Polish seed labels are in the migration under `backend/migrations`,
  outside the `backend/app` scope of `tests/test_english_source.py`.
- The `updated_since` meaning change is a breaking change for `ics-mcp` clients and is
  released with a major plugin version.

## References

- ADR-0006 (version content is immutable), ADR-0010 and ADR-0011 (i18n catalogues),
  ADR-0016 (relations that feed `superseded` and `basis_changed`).
