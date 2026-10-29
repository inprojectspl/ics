"""Shared fixtures for the backend tests.

A single `session` (engine on the DB from env), a `client` (ASGI httpx),
plus `mk_user/mk_admin/mk_asset` helpers so new tests do not repeat
~10 lines of user creation in every file.

Some tests define their own local `session` fixture; pytest prefers the
closest one (local to the file), so conftest does not break them.

Every `session` starts with `create_all` (idempotent, tables persist
between tests). Tests avoid collisions by using random emails and slugs."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime

# pytest-xdist worker isolation. This must run before importing `app.config`,
# because `get_settings()` is `@lru_cache` and caches the URLs from env.
#
# Every worker (gw0, gw1, ...) gets:
#   - its own Postgres database `ics_test_<worker>` (created in the
#     session-scoped fixture below),
#   - its own Redis DB number (1..15, enough for up to 15 workers).
#
# Without this, two workers compete for the same users.email unique index,
# rate-limit keys, JTI blacklist and so on. The rewrite also applies to
# 'master' (no xdist, e.g. `pytest -p no:xdist`), otherwise it would write to
# the dev database `ics` and flush dev Redis `/0`.
# The app ships with no organisation domains; tests use a fixed one.
os.environ.setdefault("ICS_ALLOWED_DOMAINS", "example.com")

_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
_base_db_url = os.environ.get("ICS_DATABASE_URL", "postgresql+asyncpg://ics:ics@localhost:5432/ics")
_new_db_name = f"ics_test_{_xdist_worker}"
os.environ["ICS_DATABASE_URL"] = _base_db_url.rsplit("/", 1)[0] + f"/{_new_db_name}"
_base_redis_url = os.environ.get("ICS_REDIS_URL", "redis://localhost:6379/0")
# gwN -> 1..15; master -> 15 (dev uses /0, so we never flush it).
# master and gw14 never coexist (master means no xdist), so they cannot collide.
if _xdist_worker == "master":
    _redis_num = 15
else:
    _redis_num = int(_xdist_worker.removeprefix("gw")) % 15 + 1
os.environ["ICS_REDIS_URL"] = _base_redis_url.rsplit("/", 1)[0] + f"/{_redis_num}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Asset, DocType, User  # noqa: E402
from app.redis_client import get_redis  # noqa: E402
from app.slug import generate_slug  # noqa: E402
from app.storage import storage_from_url  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _ensure_worker_db():
    """Create a dedicated Postgres database for every worker (including 'master').

    CREATE DATABASE needs a separate connection (outside a transaction), so
    we connect to `postgres` as admin. Assumes the test user has CREATEDB
    (the `ics` user in compose has it as owner).
    """
    from urllib.parse import urlparse

    import asyncpg

    parsed = urlparse(
        os.environ["ICS_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    )
    admin = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    target = parsed.path.lstrip("/")
    try:
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{target}"')
        except Exception:
            pass
        await admin.execute(f'CREATE DATABASE "{target}"')
    finally:
        await admin.close()
    # Build the schema the way production does. `create_all` calls in the
    # fixtures below then find every table present and do nothing.
    # Subprocess: migrations/env.py runs its own event loop.
    import subprocess
    import sys
    from pathlib import Path

    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if migrated.returncode != 0:
        raise RuntimeError(f"alembic upgrade head failed:\n{migrated.stderr}")


@pytest.fixture(scope="session", autouse=True)
def _fast_argon2_for_tests():
    """Cut the Argon2 cost from ~200ms to ~1ms per hash.

    The production-grade `_hasher` (memory_cost=64MiB, time_cost=3) is
    validated in `test_passwords.py`. The other tests call `mk_user`, where
    the security parameters are not checked, only that hash and verify agree. One PasswordHasher instance
    for the whole session is enough."""
    from argon2 import PasswordHasher

    from app import passwords

    original = passwords._hasher
    passwords._hasher = PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)
    yield
    passwords._hasher = original


@pytest_asyncio.fixture(autouse=True)
async def _reset_module_globals():
    """Fresh event loop and clean Redis state per test.

    1) `FLUSHDB` before the test clears rate limits, sessions and cache.
       Without it the DCR tests (`OAUTH_DCR` 5/h per IP) hit 429 after a
       few calls from the same AsyncClient.
    2) After the test we reset the `lru_cache` of `get_redis()`: pytest
       gives every function a fresh event loop, so a client from the
       previous loop fails with 'Event loop is closed' in the next test.
    """
    try:
        pre_client = get_redis()
        await pre_client.flushdb()
    except Exception:
        pass
    yield
    try:
        post_client = get_redis()
    except Exception:
        post_client = None
    if post_client is not None:
        try:
            await post_client.aclose()
        except Exception:
            pass
    get_redis.cache_clear()
    # The Arq pool (`enqueue`) is a module global bound to the loop of the
    # test that first enqueued a job; a later test would await it on a
    # closed loop ("attached to a different loop").
    from app.jobs import queue as _queue

    if _queue._pool is not None:
        try:
            await _queue._pool.aclose()
        except Exception:
            pass
        _queue._pool = None


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Fresh async session on the DB from `ICS_DATABASE_URL`.

    Every test gets its own engine: safe for parallel runs and only
    marginally more expensive (the connection pool is single-use).
    """
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """FastAPI httpx AsyncClient with an in-process ASGI transport.

    Key point: we override `get_session` with the session fixture so HTTP
    requests use the same engine as the test code (otherwise every test
    with a new event loop diverges from the module-level `app.db.engine`
    and fails with "Event loop is closed").

    `cookies` persist between requests of one AsyncClient by default, so
    login-flow tests keep the session without passing cookies by hand.
    """
    from app.db import get_session
    from app.main import create_app

    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()


async def mk_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    role: str = "user",
    password: str | None = "TestPass123!",
    email_verified: bool = True,
    display_name: str = "Test User",
    auth_method: str = "password",
    locale: str | None = None,
) -> User:
    """Create a user with a password hash. Default: verified, role user.

    With `password=None` the user has no `password_hash` (e.g. SSO-only).
    """
    from app import passwords

    user = User(
        email=email or f"u+{generate_slug(6)}@example.com",
        display_name=display_name,
        role=role,
        auth_method=auth_method,
        email_verified_at=datetime.now(UTC) if email_verified else None,
        password_hash=passwords.hash_password(password) if password else None,
        locale=locale,
    )
    session.add(user)
    await session.flush()
    return user


async def mk_admin(session: AsyncSession, **kw) -> User:
    """Shortcut for `mk_user(role="admin")`."""
    return await mk_user(session, role="admin", **kw)


async def mk_asset(
    session: AsyncSession,
    owner: User,
    *,
    title: str = "Test Doc",
    kind: str = "md_single",
    entry_path: str | None = "doc.md",
    security_status: str = "clean",
) -> Asset:
    """Create a minimal Asset owned by `owner`."""
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        kind=kind,
        title=title,
        storage_prefix=generate_slug(8),
        entry_path=entry_path,
        security_status=security_status,
        version=1,
    )
    session.add(asset)
    await session.flush()
    return asset


async def mk_doc_type(
    session: AsyncSession,
    *,
    default_review_days: int | None = None,
    properties_schema: dict | None = None,
    archived: bool = False,
) -> DocType:
    """A doc type with a unique key (the table is shared across tests)."""
    key = f"t_{generate_slug(10).lower()}"
    doc_type = DocType(
        key=key,
        label_pl=f"Typ {key}",
        label_en=f"Type {key}",
        default_review_days=default_review_days,
        properties_schema=properties_schema or {},
        archived_at=datetime.now(UTC) if archived else None,
    )
    session.add(doc_type)
    await session.flush()
    return doc_type


async def put_blob(
    asset: Asset,
    path: str,
    content: bytes,
    *,
    versioned: bool = True,
    version: int | None = None,
) -> None:
    """Write bytes under the storage key matching the asset.

    `versioned=True` (default): `{prefix}/v{version}/{path}`, used by
    every endpoint that reads an asset (read_text, _doc_payload_for,
    viewer, file-mcp). This is the canonical layout, matching `stage_asset_files`.

    `version` writes into another version's tree than the current one.

    `versioned=False`: `{prefix}/{path}`, deprecated: no endpoint reads
    this layout, so tests should use the default `versioned=True`.
    """
    settings = get_settings()
    storage = storage_from_url(settings.storage_url, settings)

    async def _gen():
        yield content

    key = (
        f"{asset.storage_prefix}/v{version or asset.version}/{path}"
        if versioned
        else f"{asset.storage_prefix}/{path}"
    )
    await storage.put(key, _gen())


# ---------- Shared helpers for new tests ----------


async def login_as(client: AsyncClient, user: User, password: str = "TestPass123!") -> None:
    """POST /api/auth/login + assert 200. A helper rather than a fixture,
    because it needs a specific user and an optional password, which a
    fixture would have to parametrize."""
    r = await client.post(
        "/api/auth/login",
        json={"email": user.email, "password": password},
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def fs_storage(monkeypatch):
    """Fresh FS storage per test in a temp dir, cleaned up afterwards.

    Note: it monkeypatches the global `Settings().storage_url`.
    """
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(get_settings(), "storage_url", f"fs://{tmp}")
        yield tmp


# ---------- OAuth/PKCE helpers ----------

import base64  # noqa: E402
import hashlib  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
from urllib.parse import parse_qs, urlparse  # noqa: E402

STATE_TOKEN_RE = re.compile(r'name="state_token"\s+value="([^"]+)"')


def make_pkce() -> tuple[str, str]:
    """Generate a (code_verifier, code_challenge) pair for PKCE S256."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def resource_uri() -> str:
    """Audience accepted by the server (mcp_resource_uri || issuer)."""
    s = get_settings()
    return s.mcp_resource_uri or s.base_url.rstrip("/")


async def register_oauth_client(client: AsyncClient, *, name: str = "Test Client") -> dict:
    """POST /oauth/register, asserts 201, returns the DCR body with client_id."""
    r = await client.post(
        "/api/auth/oauth/register",
        json={"client_name": name, "redirect_uris": ["http://localhost:9000/callback"]},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def signed_in_oauth_client(client: AsyncClient, session: AsyncSession) -> dict:
    """A registered OAuth client and a signed-in user ready to authorize it."""
    dcr = await register_oauth_client(client)
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    return dcr


async def do_authorize_get_code(
    client: AsyncClient,
    dcr_client_id: str,
    code_challenge: str,
    *,
    state: str | None = None,
) -> str:
    """GET /authorize -> parse state_token from HTML -> POST allow -> extract code."""
    params = {
        "response_type": "code",
        "client_id": dcr_client_id,
        "redirect_uri": "http://localhost:9000/callback",
        "scope": "ics",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": resource_uri(),
    }
    if state:
        params["state"] = state
    r = await client.get("/api/auth/oauth/authorize", params=params)
    assert r.status_code == 200, r.text
    state_token = STATE_TOKEN_RE.search(r.text).group(1)
    r2 = await client.post(
        "/api/auth/oauth/authorize",
        data={"state_token": state_token, "decision": "allow"},
        follow_redirects=False,
    )
    assert r2.status_code == 302, r2.text
    return parse_qs(urlparse(r2.headers["location"]).query)["code"][0]


async def full_oauth_flow(client: AsyncClient, dcr_client_id: str) -> dict:
    """Full flow up to a token: PKCE -> /authorize -> /token. Returns the body with access+refresh."""
    code_verifier, code_challenge = make_pkce()
    code = await do_authorize_get_code(client, dcr_client_id, code_challenge)
    r = await client.post(
        "/api/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": code_verifier,
            "client_id": dcr_client_id,
            "resource": resource_uri(),
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------- Tar.gz bundle ----------

import io  # noqa: E402
import tarfile  # noqa: E402


def make_tar_gz(entries: dict[str, bytes], *, force_links: bool = False) -> bytes:
    """Build an in-memory tar.gz from a `rel_path -> bytes` dict."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        if force_links:
            link_info = tarfile.TarInfo(name="link")
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = "/etc/passwd"
            t.addfile(link_info)
    return buf.getvalue()


# ---------- Google OAuth mock (Authlib) ----------

from unittest.mock import AsyncMock, MagicMock  # noqa: E402


def patch_google_creds(monkeypatch) -> None:
    """Open the `require_google_oidc` gate with dummy creds; nothing ever calls Google."""
    s = get_settings()
    monkeypatch.setattr(s, "google_oidc_client_id", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_oidc_client_secret", "test-secret")


def mock_google_oauth(
    token_payload: dict | None = None, *, raise_on_token: Exception | None = None
):
    """OAuth MagicMock shaped the way routes/auth/google.py expects."""
    from starlette.responses import RedirectResponse

    google = MagicMock()
    if raise_on_token is not None:
        google.authorize_access_token = AsyncMock(side_effect=raise_on_token)
    else:
        google.authorize_access_token = AsyncMock(return_value=token_payload or {})
    google.authorize_redirect = AsyncMock(
        return_value=RedirectResponse(
            url="https://accounts.google.com/o/oauth2/v2/auth?...",
            status_code=302,
        ),
    )
    oauth = MagicMock()
    oauth.google = google
    return oauth


# ---------- Asset setup helpers ----------


async def mk_md_single(
    client: AsyncClient,
    session: AsyncSession,
    *,
    content: str = "# Hello\nbody\n",
    entry: str = "notes.md",
) -> tuple[User, Asset]:
    """Owner + md_single asset with the `entry` file in storage + a logged-in client."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path=entry)
    await session.commit()
    await put_blob(asset, entry, content.encode("utf-8"))
    await login_as(client, user)
    return user, asset


async def mk_md_collection(
    client: AsyncClient,
    session: AsyncSession,
    files: dict[str, str],
) -> tuple[User, Asset]:
    """Owner + md_collection with files in storage + a logged-in client."""
    user = await mk_user(session)
    entry = "README.md" if "README.md" in files else next(iter(files))
    asset = await mk_asset(session, user, kind="md_collection", entry_path=entry)
    await session.commit()
    for rel, content in files.items():
        await put_blob(asset, rel, content.encode("utf-8"))
    await login_as(client, user)
    return user, asset


async def mk_html_bundle(
    client: AsyncClient,
    session: AsyncSession,
    files: dict[str, bytes],
) -> tuple[User, Asset]:
    """Owner + html_bundle with files in storage + a logged-in client."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await session.commit()
    for rel, content in files.items():
        await put_blob(asset, rel, content)
    await login_as(client, user)
    return user, asset
