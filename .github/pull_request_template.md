## What this change does

<!-- 1-3 sentences: feat, fix or refactor; which flow or component it touches; why. -->

## Related

- ADR / issue: <!-- e.g. ADR-0001, #123, or "none" -->
- Database migration: <!-- Alembic revision, or "none" -->

## Quality bar checklist (ADR-0002)

Tick each item that holds. Explain any unticked item below.

- [ ] **I1 - LOC budget**: no changed source file exceeds 500 lines.
- [ ] **I2 - Coverage**: the backend coverage gate (`--cov-fail-under=90`) and `npm run test:coverage` pass. A new frontend file has a test or an entry in the `vitest.config.ts` `exclude` list with a reason.
- [ ] **I3 - No `!` non-null assertions** in new production code. Where one is unavoidable, it carries a `// SAFE: <invariant>` comment.
- [ ] **I4 - No `time.sleep(N)` in tests.** Token expiry is mocked through `TimestampSigner.get_timestamp`.
- [ ] **I5 - Bundle**: no manual chunk for a dynamically imported library. If I added a manual chunk, the library is over 100 KB and not lazy-loaded.
- [ ] **I6 - No long "TODO / decision pending" comments** in code. Pending decisions go to an ADR in `docs/decisions/`.
- [ ] **I7 - Conventional Commits**: every commit has a type prefix (`feat:`, `fix:`, `refactor:`, `chore:`, ...).
- [ ] **I8 - New ADR (if relevant)**: numbered, with a status and the sections described in `docs/decisions/README.md`.
- [ ] **I9 - Simplification pass**: after implementing, I reviewed the change for reuse, quality and efficiency, and applied or noted the findings.
- [ ] **I10 - Database indexes**: every new `WHERE` filter has an index (composite or partial); every new foreign key has an index on its column.
- [ ] **I11 - Frontend lazy loading**: a new admin, setup or reset view uses `React.lazy()` with `<Suspense>`; a heavy component with dynamic imports is lazy at the consumer.
- [ ] **I12 - Virtualisation**: a new list that can exceed about 200 rows uses `@tanstack/react-virtual` or server pagination (25-50 per page).
- [ ] **UI strings**: new user-visible text goes through the i18n catalogue, with the key added to every locale.

## Test plan

<!-- What I tested by hand, where, and with what result. -->

- [ ] `scripts/test-backend.sh` passes.
- [ ] `cd frontend && npm test` passes.
- [ ] `cd frontend && npm run build` passes without chunk-size warnings over 500 KB (on-demand renderers excepted).
- [ ] Manual smoke test of the affected user flow.

## Notes for the reviewer

<!-- Anything non-obvious. Explicit beats implicit. -->
