# ADR-0018: External references and task linking (OpenProject work package as the task identity)

**Status:** Accepted, 2026-09-26. Not implemented yet (phase 3 of the document graph work).
**Decision owners:** Owner.
**Scope:** new tables `asset_external_refs`, `project_external_refs`,
`project_key_documents`, `backend/app/services/external_refs.py`, the external routes in
`backend/app/routes/relations/`, the task and project link panels in the frontend, and the
`ics-mcp` tools `ics_task_link`, `ics_task_unlink`, `ics_asset_external_refs`,
`ics_project_links`.

## Context

Work is planned in OpenProject (OP) and executed by agents through Project Standard (PS).
Documents that a task needs (goals, design, specification) and documents it produces
(reports, analyses) are in ICS, but nothing connects them to the task. The agent context pack
(ADR-0019) needs to answer "which documents belong to work package 4711" for any team member
and any agent.

Facts that shape the design:

- PS is local: each developer has their own vault outside git, and the PS MCP server runs on
  their machine. ICS cannot call PS; calls always go from PS or an agent to ICS.
- PS node ids are not shared: a pull from OP assigns random `n-...` ids, so the same task has
  different ids for two people. The shared identity of a task is the **OP work package id**,
  and of a project the **OP project identifier**.
- PS never writes to external systems itself; an agent does, through the relevant MCP.
- ICS has no connection to OP and does not verify work package ids or titles.

## Problem

1. Where the document to task link is stored, and what identifies a task.
2. How tasks without an OP work package (local PS projects, local nodes) are handled.
3. How an ICS project maps to an OP project.
4. What a link means for the agent (input, output, loose mention; mandatory or not).
5. What a link means for permissions, and what it may reveal.

## Decision

### Where the link lives

| Option | Description | Pros | Cons | Verdict |
|---|---|---|---|---|
| A. Only in PS (artifacts, "Links" section) | PS remembers the task's documents | no change in ICS | visible to one person (local vault); ICS does not know the document is used; other agents cannot find it | rejected |
| B. Copy in OP (comment, custom field, description) | ICS link in the work package | visible in OP | unstructured text PS must parse; OP knows no roles | rejected |
| **C. In ICS, keyed by the OP work package id** | `asset_external_refs(system='openproject', entity='work_package')` | one source for the whole team and every agent; ICS can show "where is this used"; ICS ACL filters the result | needs API and UI in ICS | **chosen** |

ICS is the source of truth. A PS `doc` artifact with an `ics://` reference is evidence of a
deliverable, and a link in an OP comment (through `op_update_brief`) is information for
people; neither is authoritative.

### `asset_external_refs`

```sql
CREATE TABLE asset_external_refs (
  id              uuid PRIMARY KEY,
  asset_id        uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  system          varchar(32) NOT NULL,  -- openproject | project_standard | gitlab | url
  entity          varchar(32) NOT NULL,  -- work_package | project | version | node | merge_request | page
  external_id     text NOT NULL,         -- '4711', 'n-8f2c...'
  external_scope  text,                  -- OP project identifier; PS project id for nodes
  role            varchar(16) NOT NULL,  -- context | deliverable | reference
  required        boolean NOT NULL DEFAULT false,
  label           text,                  -- task title snapshot from the client, untrusted
  url             text,
  asset_path      text,                  -- file inside a collection
  pinned_version  integer,               -- document version the task was based on
  note            text,
  origin          varchar(16) NOT NULL,  -- manual | agent | integration, informational
  created_by      uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_asset_external_ref ON asset_external_refs
  (asset_id, system, entity, external_id, role, coalesce(asset_path, ''));
CREATE INDEX ix_asset_external_refs_lookup ON asset_external_refs
  (system, entity, external_id);          -- "which documents does WP 4711 have"
```

**Task identity.** An OP task is `system='openproject', entity='work_package',
external_id=<wp id>`. A PS node that has no OP counterpart (a node in a local PS project, or
a local node in a mirrored project) is `system='project_standard', entity='node',
external_scope=<PS project id>, external_id=<node id>`. Such a link is useful only to the
vault that owns the node, which matches how local projects are used (one person). For a
local node inside a mirrored project PS sends the node key as the task and the nearest
ancestor with an OP id first in `ancestors`, so epic documents from OP are inherited by
locally added tasks too.

**Roles.**

- `context`: an input document the agent should use (goals, design, specification).
- `deliverable`: a document the task produced (report, analysis, documentation).
- `reference`: a loose connection.

**`required` instead of a priority.** The analysis proposed three levels (`must_read`,
`recommended`, `optional`). The owner replaced them with one boolean: `required = true`
marks a mandatory document, for example the user story or the mockup description the task
implements. Task documents are information for the agent; `required` is an option PS may
enforce (a gate check that the agent recorded reading it), ICS does not enforce anything.
Three levels invited endless debate about the middle one and gave the agent no clearer
instruction than "mandatory or not".

`pinned_version` works like `target_version` on relations (ADR-0016): if the document moved
past it, the context pack flags `basis_changed` on the link.

Limit: 100 external references per asset (`external_ref_limit`).

### `project_external_refs`: one home per OP project

```sql
CREATE TABLE project_external_refs (
  project_id   uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  system       varchar(32) NOT NULL,   -- openproject | project_standard
  external_id  text NOT NULL,          -- OP project identifier, e.g. 'acme-portal'
  created_by   uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, system, external_id)
);
CREATE UNIQUE INDEX uq_project_external ON project_external_refs (system, external_id);
```

One OP project has exactly one ICS project as its document home; one ICS project may have
several OP projects (for example maintenance and development of the same system). The
mapping is set by an owner of the ICS project. PS resolves a project in this order: its own
`ics.projectSlug` setting, then `GET /api/projects/by-external?system=openproject&id=...`,
then no mapping (a warning in `task_start`, never a refusal).

**`project_external_taken` is a deliberate small leak.** Mapping an OP project that already
has a home gives `409 project_external_taken` without saying which ICS project holds it. It
reveals only that a mapping exists. OP project identifiers are not secret, and the
alternative (silently accepting a second home, or a 404 that makes the conflict
undebuggable) is worse. `GET /api/projects/by-external` returns 404 both when there is no
mapping and when the caller is not a member of the mapped project.

### `project_key_documents`

```sql
CREATE TABLE project_key_documents (
  project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  asset_id    uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  position    integer NOT NULL,
  reason      text,                 -- "project charter", "business goals"
  PRIMARY KEY (project_id, asset_id)
);
CREATE INDEX ix_project_key_documents_asset ON project_key_documents (asset_id);
```

The agent's entry point when a task has little or nothing linked: project charter, business
goals, glossary, architecture. Usually 3 to 7 documents, set by an owner of the ICS project.

### Rekey

`POST /api/external-refs/rekey` (owner of the ICS project) moves links from one key to
another in one transaction, for example from a PS node to the OP work package created for it
when a local project is later pushed to OP. It changes only links on assets the caller has
`editor` on and reports how many it moved.

### Permissions and what a link reveals

- **Linking gives nobody access.** An OP project member without access in ICS does not see
  the document in the context pack. Access is granted in ICS only (project, direct share,
  project share of ADR-0017).
- Creating or deleting a link requires `editor` on the asset. ICS does not check that the
  caller can see the work package in OP (it has no OP connection). Someone can link a
  document to a foreign task; the effect is limited (only authorised people see it) and
  audited.
- Reading a document's task links requires graph access to the asset (ADR-0016): a viewer
  with only a direct share and a share link guest get 404.
- `label` is a snapshot provided by the client. It can be stale and is untrusted text:
  rendered as text, never as HTML, and never used for anything but display.
- A query by task returns only documents the caller has graph access to; there is no count
  of hidden ones except `hidden_count` for owners of the mapped project (ADR-0019).

### API and errors

`GET/POST /api/assets/{id}/external-refs`, `DELETE /api/external-refs/{id}`,
`GET/PUT /api/projects/{slug}/external-refs`, `GET/PUT /api/projects/{slug}/key-documents`,
`GET /api/projects/by-external`, `POST /api/external-refs/rekey`. Error codes
`external_ref_invalid`, `external_ref_exists`, `external_ref_limit`,
`project_external_taken`. Audit actions `external_ref_added`, `external_ref_removed`,
`external_refs_rekeyed`, `project_external_ref_set`, `project_key_documents_set`.

Estimate (phase 3, without the context pack): about 2 days backend, 2 days frontend, 1 day
`ics-mcp`.

## Reactivation trigger

- ICS gets its own OP API key: verify work package ids and fetch titles server side, and drop
  the untrusted `label`.
- PS vaults become shared (for example in git): PS node keys become a real shared identity.
- A second task tracker appears: a new `system` value, same table.
- Teams want OP projects documented in two ICS projects: revisit the single home rule.

## Consequences

- One table answers "documents of a task" for everyone, filtered by ICS permissions; OP and
  PS keep only pointers.
- ICS stores task ids and titles it cannot verify; the damage is bounded by permissions and
  the audit log.
- The 409 on a taken OP project is documented as a known, accepted disclosure.
- PS changes (the `ics` project setting, `ics://` references, the `documents` hint in
  `task_start`) are done in the PS repository and are not governed by this ADR.

## References

- ADR-0016 (graph access), ADR-0017 (project shares), ADR-0019 (context pack).
