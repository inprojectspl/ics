# Contributing to ICS

Thanks for your interest in ICS. This guide covers the local setup and the
conventions every change is expected to follow. By participating you agree to
the [Code of Conduct](./CODE_OF_CONDUCT.md). Security problems go through
[SECURITY.md](./SECURITY.md), not the issue tracker.

## Development setup

You need Docker with Compose v2, `make`, [`uv`](https://docs.astral.sh/uv/)
and Node.js 22.12 or newer.

```bash
make dev-init   # build dev images, start Postgres and Redis, run migrations
make dev        # full stack with hot reload on http://localhost:5173
```

The [README](./README.md#quick-start-development) lists the dev
credentials, ports and all `make` targets.

Before opening a pull request, run:

```bash
# backend
cd backend
uv sync --group dev
uv run ruff check app tests --fix
uv run ruff format app tests
../scripts/test-backend.sh

# frontend
cd frontend
npm ci
npm run typecheck
npm run lint
npm run test:coverage
```

## Workflow

- Branch from the latest `main` and keep one topic per branch.
- Keep the diff to what the change needs. Refactors noticed along the way
  belong in a separate change or an issue.
- Fill in the pull request template, including the quality
  checklist.

## Commits

We use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
with a scope where it helps:

```
feat(backend): add per-user share with editor and viewer roles
fix(frontend): keep the file input reference across the upload await
docs: describe the binding CI snippet
chore(ci): cache the uv environment
```

Write commit messages in English, in the imperative, short and specific.
User-facing changes also get an entry in [CHANGELOG.md](./CHANGELOG.md)
([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)).

## Language

Code, identifiers, comments, docstrings, log messages, API error `detail`
texts, commit messages and documentation are in English
([ADR-0009](./docs/decisions/0009-english-first-with-ui-i18n.md)).

- API errors return an English `detail` plus a stable machine-readable
  `code`. Clients react to `code`, never to the `detail` text.
- The UI must not hard-code user-visible text. Every string goes through the
  i18n catalogue, and each new key is added to **every** locale file (`pl`
  and `en`), not only one.

Comments explain *why*, not *what*. Do not leave changelog-style comments
about your own edits in the code.

## Code size

No source file in `backend/app/**` or `frontend/src/**` may exceed **500
lines**. Start planning a split at about 400:

- Backend route modules with several endpoint groups become a package: a
  shared `router` in `_router.py`, one module per group, `__init__.py`
  re-exporting the router (see `app/routes/assets/`). DTOs go to
  `_models.py`, SQL helpers to `_shared.py`.
- A route module over 400 lines with real business logic moves that logic to
  `app/services/`: async functions without FastAPI types, raising domain
  exceptions that the route maps to HTTP.
- Frontend components over about 300 lines with independent parts become a
  `Component/` folder with an `index.ts`; pure helpers live in their own
  module so they can be tested without effects (see
  `components/VaultGraph/`).

## Backend

- Lint and format with **ruff** (config in `backend/pyproject.toml`); CI runs
  both `ruff check` and `ruff format --check`. There is no mypy gate.
- FastAPI parameters use `Annotated[T, Query()] = default` and
  `Annotated[T, Depends(dep)]`, never `= Query(...)` or `= Depends(...)` as
  defaults. No mutable defaults.
- Use `datetime.now(UTC)`.
- Render asset Markdown through `render_asset_file()` in
  `app/render_cache.py`, not `render_markdown_async` directly
  ([ADR-0006](./docs/decisions/0006-rendered-markdown-cache.md)).
- Every column filtered in a hot-path `WHERE` needs an index (composite or
  partial where it fits), and every foreign key with `ON DELETE` needs an
  index on its column. Add a migration with the endpoint.
- Observability is structured logging with `structlog`. Do not add
  Prometheus, a metrics middleware or a `/metrics` endpoint.

## Frontend

- TypeScript runs with every strict flag, including
  `noUncheckedIndexedAccess`. Do not turn any off.
- No `!` non-null assertions in production code; narrow with a guard instead.
  Tests may use them.
- Use the domain unions from `src/api/types.ts` (`AssetKind`, `ShareMode`,
  ...) instead of `string`, and switch over them without a `default` so new
  members are caught.
- List row components are wrapped in `memo()`, with callbacks stabilised by
  the parent (`useCallback`, `useMemo`).
- Admin, setup and other secondary views are loaded with `React.lazy()`;
  heavy components with dynamic imports (graph, Mermaid) are lazy at the
  consumer. Lists that can exceed about 200 rows are virtualised or
  server-paginated.
- Styling follows [docs/DESIGN.md](./docs/DESIGN.md).

## Tests

Backend tests use pytest against a real PostgreSQL and Redis (no database
mocks); frontend tests use Vitest. We do not chase full coverage. We test:

- security-critical paths (signature verification, binding config
  validation, Markdown/HTML sanitising, password hashing, rate limiting);
- core business logic (asset lifecycle, share link modes, replay
  protection);
- non-obvious edge cases we have already been bitten by.

We do not write tests for trivial getters, plain DTOs or FastAPI handlers
without branching.

Rules every new backend test follows:

- Unique data per test through the `mk_user()` and `mk_asset()` helpers in
  `tests/conftest.py` and `app.slug.generate_slug()`; tests run in parallel
  under pytest-xdist and hard-coded e-mails or slugs collide.
- Write to storage only through the `put_blob()` fixture helper.
- Mock time for token expiry (patch `TimestampSigner.get_timestamp`), never
  `sleep`.
- Assert on status codes and error `code`s, not on message substrings.

Coverage thresholds are a ratchet: the backend gate is 90%
(`.github/workflows/ci.yml`) and the frontend thresholds live in
`frontend/vitest.config.ts`. Do not lower them. A frontend file that cannot
be unit tested may be added to the coverage `exclude` list with a comment
explaining why.

## Documentation

The site at <https://inprojectspl.github.io/ics/> is built with
[MkDocs](https://www.mkdocs.org) and [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
from `docs/` and `mkdocs.yml`. The Docs workflow builds it for every pull request that touches
them and publishes it to GitHub Pages from `main`. To preview it locally:

```sh
pip install -r docs/requirements.txt
mkdocs serve
```

`mkdocs build --strict` must pass: a broken link or anchor fails the build. Link to files outside
`docs/` by their full GitHub URL. In a fork, set **Settings > Pages > Source** to
**GitHub Actions** before the first deploy.

## Architectural decisions

Decisions such as "we choose library X because Y", "we defer this feature" or
"we change approach" are recorded as ADRs in
[`docs/decisions/`](./docs/decisions/) (`NNNN-slug.md`, next free number).
Sections: Status, Context, Problem, Decision (options with rough costs),
Reactivation trigger, Consequences. A code comment next to such a decision is
a two or three line pointer to the ADR, not the reasoning itself.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](./LICENSE) of this project.
