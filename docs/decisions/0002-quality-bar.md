# ADR-0002: Quality bar: what "high standard" means in ICS

**Status:** Accepted (2026-05-17).
**Scope:** all application code (`backend/app/**`, `frontend/src/**`) and infrastructure as code (`compose*.yaml`, `.github/workflows/ci.yml`).

## Goal

Keep quality at **9-10/10**, measured empirically (LOC budgets, coverage gates, performance regressions). This ADR is a **ratchet**: a threshold is never lowered without a new ADR.

Each invariant has:
1. **Definition** (what exactly it means).
2. **Measurement** (how we verify it in CI or locally).
3. **Reactivation trigger** (when we lower the threshold, and what has to happen first).

## Invariants

### I1. Source file ≤500 LOC

**Definition**: no file in `backend/app/**` or `frontend/src/**` exceeds 500 LOC. Test files are exempt (they may grow with the number of scenarios).

**Measurement**:
```bash
find backend/app frontend/src \( -name "*.py" -o -name "*.ts" -o -name "*.tsx" \) \
  | xargs wc -l | sort -rn | head -10
```

After the split-mega-files session (2026-05-16) the top file was `Home.tsx` at ~480 LOC.

**Trigger**: when a file approaches 400 LOC, plan a split (patterns: `routes/assets/`, `routes/mcp_assets/`, the `VaultGraph/` package). 500+ LOC blocks review in the MR.

**Do we lower the threshold?** No. Splitting into a package is always possible.

### I2. Coverage gates

**Definition**:
- Backend: 90% lines (measured by `pytest-cov`, gate in `.github/workflows/ci.yml`: `--cov-fail-under=90`). The gate started at 80% and has been raised since.
- Frontend: 80% lines/statements, 75% functions, 80% branches (`vitest.config.ts` `thresholds`).

The frontend coverage `include` is `src/lib/**`, `src/components/**`, `src/views/**` and `src/api/**`; `exclude` lists files without unit tests (end-to-end candidates, static data). The exclude list grows only through a deliberate addition with a justification.

**Measurement**:
- Backend: `uv run pytest --cov=app --cov-fail-under=90` in the pipeline.
- Frontend: `npm run test:coverage` (vitest fails by itself when a threshold is not met).

**Trigger**: lowering a threshold requires an ADR. Coverage can be raised without an ADR; only lowering needs a justification.

### I3. No `!` non-null assertion in production hot-path code

**Definition**: in code that runs 60 times a second (canvas render, force simulation, pointer handlers) we do not use `arr[i]!`. Instead: a guard, `const x = arr[i]; if (!x) continue;`. In tests `!` is allowed (we control the data).

**Measurement**: `grep -rE '\[[^]]+\]!' frontend/src/components/VaultGraph` → 0 results. For now this is caught manually in `/simplify`.

**Trigger**: introducing `!` in a hot path requires a `// SAFE: <invariant>` comment with a justification (e.g. a specific test guarantees the index is in range).

### I4. Test run ≤ 2 minutes (with xdist)

**Definition**: the full backend test run on 8-10 vCPU takes ~2 min. The frontend tests take ~20 s.

**Measurement**: `uv run pytest -q` locally + the CI run.

**Trigger**: growth of >50% (to >3 min): look for a regression (slow fixture, missing clock mock, pointless sleeps).

**Patterns**:
- `time.sleep(N)` in tests is **forbidden**. Use `patch.object(TimestampSigner, "get_timestamp", return_value=int(time.time()) + N)` instead.
- Per-worker DB isolation through `PYTEST_XDIST_WORKER` at the very top of `backend/tests/conftest.py`, before `app.config` is imported (`lru_cache` on the env).
- Unique data per test (`generate_slug()`, random email); without it xdist produces IntegrityErrors on unique constraints.

### I5. Initial paint ≤ 250KB gzip

**Definition**: the sum of gzipped chunks loaded on the first page open (index + vendor-react + vendor-tanstack + vendor-lucide + index.css). On-demand chunks (mermaid, shiki per language, cytoscape) do not count.

**Measurement**: `npm run build` → sum of the relevant lines in the output. Currently ~194KB.

**Trigger**: growth of 30KB → audit. Vite warns about chunks >500KB (the limit is raised to 1024 for on-demand bundles).

**Pattern**: `frontend/vite.config.ts` `manualChunks`: an exact package boundary regex, stable vendors only. Renderers loaded with dynamic import (`mermaid`, `shiki`) are left to Rollup.

### I6. No misleading UX ("TODO" comments become ADRs)

**Definition**: every "decision pending" / "feature deferred" / "TODO product call" goes to `docs/decisions/`. The code carries at most a 2-3 line pointer. Pattern: ADR-0001.

**Measurement**: code review. Heuristic: if a code comment is >10 lines and describes "what should be done someday", it is an ADR, not a comment.

### I7. Conventional Commits

**Definition**: every commit has a `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `perf:`, `style:`, `ci:`, `build:` or `revert:` prefix. The scope is optional (e.g. `feat(backend):`).

**Measurement**: MR review against https://www.conventionalcommits.org/en/v1.0.0/.

### I8. An ADR before shelving a feature

No "comment out + push". A decision to shelve a feature produces an ADR describing the options with estimates and a reactivation trigger. Pattern: ADR-0001.

### I9. /simplify after a larger change

After every refactor, split or new feature, run the `/simplify` skill (3 agents in parallel: reuse / quality / efficiency). It catches structural regressions that a single review would miss.

### I10. DB queries: an index per filter combination

**Definition**: every column filtered in a hot-path query must be indexed. Composite indexes for filters combined with AND (`(user_id, accepted_at)`, `(email, timestamp) WHERE succeeded=false`). Partial indexes for rare values (`WHERE col IS NOT NULL`, `WHERE deleted_at IS NULL`).

**Measurement**: manual `EXPLAIN` in production. Heuristic: a `WHERE` on 2+ columns + a sort → composite index. A boolean filter with 5%+ skew → partial index.

**Trigger**: a new endpoint filtering on an unindexed column blocks review. A perf-only migration can be added proactively; Alembic `0017_perf_indexes` is the pattern.

**Partial index patterns**:
- `audit_log.client_id WHERE client_id IS NOT NULL` (~95% of rows are NULL)
- `auth_attempts (email, timestamp) WHERE succeeded=false` (brute-force detection hot path)
- `users.locked_until WHERE locked_until IS NOT NULL` (<1% of rows non-null)

**Anti-patterns**:
- **Do NOT put `index=True` on columns with `unique=True`**: the UNIQUE constraint already creates a B-tree index. Two indexes on the same column mean 2x write amplification on every INSERT/UPDATE. Migration `0019_drop_duplicate_indexes` removed 7 duplicates.
- **Do NOT proactively index FKs with `ondelete=SET NULL` on low-traffic parent tables** (e.g. `share_links.created_by`). Parent DELETEs are rare; index maintenance costs more than an occasional Seq Scan. **EXCEPTIONS**: FKs to `oauth_clients` (`audit_log.client_id`) and FKs to `assets` (cascade). Rule: index an FK when parent DELETEs are daily traffic OR the child table has >100k rows.

**`COUNT FILTER` instead of N separate COUNTs** (PG ≥ 9.4):
```sql
SELECT
  count(*) FILTER (WHERE last_login_at > :cutoff) AS active_30d,
  count(*) FILTER (WHERE locked_until > :now) AS locked
FROM users
```
Pattern: `admin_users/listing.py`.

**`COUNT(*) OVER ()` window function for list + total** in one query (pattern: `mcp_assets/search.py`) instead of two separate SELECTs.

**Always cap pagination**: a listing never returns >200 rows per response, even without an explicit `?limit=`. Pattern: `projects/crud.py:get_project` (cap of 200 with `assets_truncated: bool`).

**Parallel storage reads** under a semaphore when collection operations issue N separate GETs:
```python
sem = asyncio.Semaphore(8)
async def _fetch(rel: str) -> bytes:
    async with sem:
        return await read_text_at_version(asset, v, rel, settings)
results = await asyncio.gather(*(_fetch(rel) for rel in files))
```
Pattern: `routes/assets/_helpers.py:_stream_source`, `routes/assets/versions.py:diff_versions`.

### I11. Frontend lazy loading for rarely used routes

**Definition**: every admin / setup / reset-flow / per-feature route uses `React.lazy()` + `<Suspense>`. Only the common entry points (home dashboard, viewer, share view) stay eager.

**Measurement**: build → top 10 chunks. Every `View*.tsx` >5KB raw must have its own chunk and not be part of `index-*.js`.

**Pattern**: `frontend/src/App.tsx`: Home/Viewer/ShareView eager, the rest `lazy(() => import(...))`.

### I12. List/table virtualization threshold

**Definition**: a list rendering >200 rows at once requires virtualization (`@tanstack/react-virtual`). Lists with server pagination of 25-50 per page do not.

**Trigger**: a new endpoint returning a potentially unbounded set (audit log "load older", project file list) → cursor pagination + a virtualization plan.

## Consequences

**Benefits**:
- Consistency. A new contributor (or an AI agent) has a single source of truth.
- Predictability. Every change has a known bar.
- The "all good" signal is measurable: `top 10 LOC <500`, coverage gates met, `tests <2min`, `initial paint <250KB`. Four commands verify the state.

**Costs**:
- Time: splitting a 500 LOC file takes an hour or two.
- Discipline: ADRs mean writing instead of `# TODO`.
- A new contributor has to read ADR-0002, which adds ~30 min to onboarding.

## Reactivation trigger

This ADR evolves. Every "lower a threshold" or "add a new invariant" decision updates this ADR with a new version, with `Superseded by` in the old one.

## References

- ADR-0001: comments feature deferred (the ADR format template).
