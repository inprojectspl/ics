# ADR-0017: Project shares as a fifth role source

**Status:** Accepted, 2026-09-26. Not implemented yet (phase 2 of the document graph work).
**Decision owners:** Owner.
**Scope:** new table `asset_project_shares`, `backend/app/permissions.py`
(`effective_role`, `visible_assets_filter`, `shared_with_user_filter`, the graph access
predicate of ADR-0016), `backend/tests/test_visibility_parity.py`, the share dialog and
project views in the frontend, and the `ics-mcp` sharing tools.

## Context

An asset has one `project_id`. Members of that project get a role on the asset according to
their project role; everyone else needs a direct `AssetShare` or a share link. Some
documents concern several projects: a company policy, a contract template, a price list, a
platform architecture that many product projects build on. Today such a document can be
shared with each person separately, which goes stale as project membership changes, or
duplicated into each project, which breaks versions and relations.

The relation graph (ADR-0016) adds a second reason. Graph access is given to members of the
asset's project, but not to viewers with only a direct share. A cross-project edge is
visible only to people who see both ends, so without a project level share a document that
many projects depend on stays invisible in their graphs.

`effective_role` today takes the strongest of four sources: system admin, file owner,
accepted project membership, direct `AssetShare`.

## Problem

How can one asset be available to the members of several projects, with a role, without
losing a single home for management (quota, ownership, project owner rights, deletion)?

## Decision

### Options (from the analysis, chapter 02)

| Option | Description | Evaluation | Estimate |
|---|---|---|---|
| A. Keep one project | other projects are linked only through relations and task links | simplest, but members of the second project have no access, so relations to the document are invisible to them | 0 days |
| B. Many-to-many without permissions | table `asset_projects`, no effect on ACL | misleading: the document "is in the project" and a project member cannot open it | about 1 day |
| **C. Home project plus project shares** | `project_id` stays the home; a new table `asset_project_shares(asset_id, project_id, role)` gives the members of another project the role `viewer` or `editor` | consistent with `effective_role` as a maximum over sources; one new source | about 1.5 days backend, 1 day frontend |

**Chosen: C.** It is rarely needed, but it is the only option in which "this document is
available in project X" means the same thing for access, lists and the graph.

### Model

```sql
CREATE TABLE asset_project_shares (
  asset_id    uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  project_id  uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  role        varchar(16) NOT NULL CHECK (role IN ('viewer', 'editor')),
  created_by  uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_id, project_id)
);
CREATE INDEX ix_asset_project_shares_project ON asset_project_shares (project_id);
```

- The home project (`assets.project_id`) cannot also be a share target.
- Creating or changing a project share requires the role that may share the asset today
  (`can_share_externally`: file owner or project owner of the home project). As when moving
  an asset into a project (`assert_project_contributor`), the caller must be an `owner` or
  `editor` member of the target project, so nobody can push documents into a project they
  barely belong to.
- A project share never grants `project_owner` rights on the asset: owners of the assigned
  project cannot delete, move or reshare it.

### Fifth role source

`effective_role` gains one source: for each project share of the asset where the user is an
accepted member of the target project, the candidate role is the share's role capped by the
member's project role (a project `viewer` gets at most `viewer`; `editor` and `owner` get
the share's role). The result stays the maximum over all sources.

`visible_assets_filter` (through `shared_with_user_filter`) gains an `EXISTS` over
`asset_project_shares` joined with accepted `project_members`. The existing parity test
(`test_visibility_parity.py`) makes sure the SQL predicate and `effective_role` agree, and
gets cases for the new source.

### Graph access

Any accepted member, of any role including `viewer`, of a project the asset is assigned to
has graph access to that asset (ADR-0016, graph access table). This is the difference from a
direct viewer share: a project share is a decision that the document belongs to the
project's working context, so its relations, task links and neighbourhood are part of that
context. The project map of the assigned project (`GET /api/projects/{slug}/graph`) lists
the shared asset as a node of that project, marked as shared in.

### API

- `GET/PUT/DELETE /api/assets/{id}/project-shares` (list, set a role, remove).
- Audit actions `asset_project_share_added`, `asset_project_share_removed`.
- Error code `project_share_home` (target is the home project); a caller who is not a
  contributor of the target project gets the existing error of `assert_project_contributor`.
  The new code is added to `docs/api-errors.md` and
  `frontend/src/lib/errorMessages.ts`.

## Reactivation trigger

- Project shares become common (for example most assets have one or more): consider real
  many-to-many membership and drop the idea of a single home.
- Requests for a project share that grants owner rights: revisit the "home manages" rule.
- Visibility queries slow down because of the extra `EXISTS`: add a composite index or a
  materialised visibility table.

## Consequences

- `effective_role` and `visible_assets_filter` carry one more source; every list, search
  and graph query gets it through the shared predicate, never through a copy.
- Removing a user from the assigned project, or deleting that project, removes their access
  through this source immediately. Edges stay in the database (ADR-0016).
- Quota, ownership and deletion stay with the home project and the file owner.
- The share dialog gains a "Projects" section; lists show shared-in documents in the
  assigned project with a marker.

## References

- ADR-0016 (graph access), `backend/app/permissions.py`.
