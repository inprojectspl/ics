# ADR-0003: Major dependency upgrades (React 19, TS 6, shiki 4, ...) and a backend refresh

**Status:** Accepted, implemented 2026-06-01.
**Decision owners:** Tech lead.
**Scope:** `frontend/package.json`, `frontend/package-lock.json`, `backend/uv.lock`.

## Context

The dependency audit (2026-06-01) deliberately left the big frontend majors
as "a separate decision / ADR candidate": React 18→19, TypeScript 5→6,
lucide-react 0.469→1.x, shiki 1→4, jsdom 25→29. An earlier stage of the same
audit had already bumped the toolchain (vite 8, vitest 4) and cleared all
`npm audit` advisories.

The decision: do these breaking majors now, or keep postponing them.

## Decision

**Do all of them now, because they went in cleanly.** The upgrade was done in
stages, each gated by full verification (typecheck + build + the whole test
run + a dev server smoke test).

**Frontend (`chore/frontend-majors`):**
- shiki 1→4, lucide-react 0.469→1.17, jsdom 25→29 (low-risk batch).
  - shiki: the code already used the modern API (`createHighlighter` /
    `codeToHtml`), stable from v1 to v4, so no code changes.
  - lucide 1.x: kept the named icon exports we use (TS would have caught a
    rename), so no changes.
  - jsdom: test environment only.
- React 18→19, react-dom 19, @types/react / -dom 19, TypeScript 5.9→6.0
  (batch 2).
  - **No code changes.** The codebase already used the patterns React 19
    requires (`createRoot`, typed props on function components, no
    `defaultProps` or string refs). `@vitejs/plugin-react` 6 and
    `@testing-library/react` 16 support React 19.

**Backend (`chore/backend-hardening`):**
- `uv lock --upgrade` within the constraints: fastapi 0.136.3, starlette
  1.2.1, sqlalchemy 2.0.50, uvicorn 0.48, lxml, pyjwt, joserfc, ruff, ...

## Deliberately NOT done

- **redis 5→8 (backend).** `arq` pins `redis[hiredis]<6,>=4.2.0`, so redis 8
  is out of reach without dropping arq (our job queue). Reactivation trigger:
  arq releases a version that supports redis ≥6, or we change the queue.
  Until then redis stays on 5.x, with no known CVEs (`pip-audit`: clean).

## Verification (2026-06-01)

- Frontend: `tsc --noEmit` (TS 6 + @types/react 19) clean; `npm run build` OK;
  vitest **176/176** (renders real components and hooks under React 19 in
  jsdom); `npm audit` = 0; dev server smoke test in the container (vite
  8.0.16, React 19.2.6, `main.tsx` transforms cleanly, the `/api` proxy works).
- Backend: `uv sync --frozen` + clean `ruff` + **748 passed** on the bumped
  lock.

## Consequences

- The frontend is on a current, supported stack (React 19 / TS 6 / vite 8 /
  vitest 4).
- `npm audit` and `pip-audit` report no vulnerabilities.
- Redis stays behind (5.x) until arq relaxes its pin, the only remaining debt.
- The dev compose file does not mount `frontend/package-lock.json` (only
  `package.json`), so updating dependencies in the container goes through
  `npm install` (reconcile), not `npm ci`. A minor dev-only inconsistency, to
  be looked at separately.

## References

- The dependency audit, "deliberately deferred" section.
- `backend/pyproject.toml`: `arq>=0.26` (the redis<6 pin comes from arq).
