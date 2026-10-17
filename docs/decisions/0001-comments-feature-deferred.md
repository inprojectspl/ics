# ADR-0001: Comments feature (REJECTED)

**Status:** Rejected, feature removed 2026-05-17 (option 3 below).
**Decision owners:** Owner / Product.
**Scope:** router `app/routes/comments.py`, model `Comment`, migration `0008`, frontend `components/CommentsThread.tsx`.

## Implementing the decision (2026-05-17)

Full removal. Deleted:
- `backend/app/routes/comments.py` + endpoints
- `backend/tests/test_comments.py`
- `class Comment` from `backend/app/models.py`
- migration `0020_drop_comments.py`: drops the `comments` table + indexes
- `frontend/src/api/comments.ts`
- `frontend/src/components/CommentsThread.tsx`
- the `Comment` type from `frontend/src/api/types.ts`
- references in `main.py`, `api.ts`, `Viewer.tsx`

Migration `0008_comments.py` stays in the history (Alembic up-chain) and `0020` reverses it. Bringing the feature back requires a restore from git plus a decision for option 1 or 2.

---

## Context (historical)

Commit `8221189` (2026-05-13) shipped a "Comments" feature as an *editorial annotation layer*, available to the asset's **owner and admins**. How it worked:

- The owner sees and can add comments on their asset.
- An admin sees them and can moderate.
- **A share-link visitor does NOT see comments.**
- **Another user in the organization (with the asset shared through `asset_shares`) does not see them either.**

## Problem

The "Comments" label in the UI promises a **social / discussion** feature that the system *does not deliver*. An owner leaving a comment on their own asset is writing a **private note**, not a dialogue. A visitor clicking "Comments" on a shared document **sees nothing**, which is confusing.

The UX is **misleading**. Three options:

1. **Rebrand to "Notes"** with honest owner-only semantics in the UI (a "only you can see this" chip). Least code, fastest.
2. **A per-share `viewers_can_comment` toggle** (the visitor gets a moderated "guestbook" on the share link). Full implementation: a new ACL at the `share_link.allow_comments` level, API validation, a frontend toggle in `ShareDialog`. Estimate: ~3 days of work + tests.
3. **Remove the feature**: drop the router, model and frontend, soft-delete existing comments in a migration. This path means losing 1.5 weeks of work from `8221189` and the follow-up commits.

An inline note in `routes/comments.py:_asset_or_404` marked option 2 as the original author's preference, but product had not decided.

## Decision (interim)

`comments.router` is **NOT** mounted in `main.py` (commented-out import). All artifacts (router, model, migration 0008, frontend `CommentsThread`, tests) **stay in the tree**, so bringing the feature back is one line instead of a restore from git.

The frontend chrome shows the "Comments" tab only when the router responds with `200 OK`; with the router disabled the tab disappears automatically (the probe calls `/api/assets/{id}/comments` with a fallback).

## Reactivation trigger

Product chooses between options 1/2/3. After the choice:

- **Option 1 (rebrand)**: rename "Comments" to "Notes" in `frontend/src/components/CommentsThread.tsx` + an "only you can see this" chip in the owner view; mount the router; mark the ADR as `Accepted: option 1` with the date.
- **Option 2 (toggle)**: add a `share_links.allow_comments` column (migration), extend `_can_view` in `routes/shares/_shared.py` with that check, add a frontend toggle in `ShareDialog`; mount the router; mark the ADR as `Accepted: option 2` with the date.
- **Option 3 (drop)**: delete `app/routes/comments.py`, add a soft-delete migration, clean up the frontend, mark the ADR as `Rejected, feature removed` with the date.

## Consequences (while the status was Pending)

- The backend carried dead code (~74 LOC in `routes/comments.py` + 30 LOC of model). Ruff passed, with no orphaned imports.
- Frontend `CommentsThread.tsx` (excluded from the coverage scope in `vitest.config.ts`).
- Migration 0008 created the `comments` table, which was empty in production (the router had been unmounted since 2026-05-13). It was not cleaned up by retention (the append-only audit protected it from accidental deletion for a possible return).

## References

- Commit `8221189` (2026-05-13): the feature ship.
- `backend/app/routes/comments.py` (deleted; see the git history): the inline `_asset_or_404` note with the author's preference.
- The git history of `backend/app/main.py` around the `# app.include_router(comments.router)` line: the unmount history. The line itself was removed with the feature.
