"""CDN allowlist: host validation, env+DB union, cache invalidation,
admin CRUD shape, dynamic CSP composition."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import cdn_allowlist
from app.config import get_settings
from app.db import Base
from app.html_bundle import BUNDLE_CSP, build_csp
from app.models import CdnAllowlist, User
from app.routes.admin import CdnAddIn, add_cdn_host, list_cdn_allowlist, remove_cdn_host
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


# ---------- host validation ----------


@pytest.mark.parametrize(
    "host",
    [
        "cdn.jsdelivr.net",
        "fonts.googleapis.com",
        "example.io",
        "a.b.c.d",
    ],
)
def test_is_acceptable_host_accepts_reasonable(host):
    assert cdn_allowlist.is_acceptable_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "",
        "example",  # no dot
        "example.com/path",  # path
        "https://example.com",  # scheme
        "example.com:8080",  # port
        "localhost",  # local
        "127.0.0.1",  # loopback
        "10.0.0.1",  # private
        ".example.com",  # leading dot
        "example.com.",  # trailing dot
    ],
)
def test_is_acceptable_host_rejects_bad(host):
    assert cdn_allowlist.is_acceptable_host(host) is False


# ---------- env + DB union ----------


@pytest.mark.asyncio
async def test_trusted_hosts_unions_env_and_db(session):
    cdn_allowlist.invalidate()
    s = SimpleNamespace(
        trusted_cdn_hosts="cdn.jsdelivr.net,unpkg.com",
        trusted_cdn_hosts_set=frozenset({"cdn.jsdelivr.net", "unpkg.com"}),
    )
    hosts = await cdn_allowlist.trusted_hosts(session, s)
    assert "cdn.jsdelivr.net" in hosts
    assert "unpkg.com" in hosts

    # Add a runtime entry, unique per test run, because the fixture does
    # not roll back between tests.
    unique = f"runtime-{generate_slug(6)}.example.io"
    cdn_allowlist.invalidate()
    session.add(CdnAllowlist(host=unique, note="internal"))
    await session.commit()

    hosts = await cdn_allowlist.trusted_hosts(session, s)
    assert unique in hosts
    assert "cdn.jsdelivr.net" in hosts  # env baseline still there


@pytest.mark.asyncio
async def test_trusted_hosts_cached_until_invalidated(session):
    s = SimpleNamespace(
        trusted_cdn_hosts="cdn.jsdelivr.net",
        trusted_cdn_hosts_set=frozenset({"cdn.jsdelivr.net"}),
    )
    cdn_allowlist.invalidate()
    first = await cdn_allowlist.trusted_hosts(session, s)

    # Insert a row without invalidating: the cached result still applies.
    unique = f"cached-{generate_slug(6)}.example.io"
    session.add(CdnAllowlist(host=unique))
    await session.commit()
    second = await cdn_allowlist.trusted_hosts(session, s)
    assert unique not in second
    assert first == second

    # After invalidation the next call picks up the new row.
    cdn_allowlist.invalidate()
    third = await cdn_allowlist.trusted_hosts(session, s)
    assert unique in third


# ---------- admin endpoints (via route handlers) ----------


async def _mk_admin(session) -> User:
    u = User(email=f"a+{generate_slug(6)}@example.com", role="admin")
    session.add(u)
    await session.flush()
    return u


@pytest.mark.asyncio
async def test_add_endpoint_rejects_built_in(session):
    cdn_allowlist.invalidate()
    admin = await _mk_admin(session)
    settings = SimpleNamespace(
        trusted_cdn_hosts="cdn.jsdelivr.net",
        trusted_cdn_hosts_set=frozenset({"cdn.jsdelivr.net"}),
    )
    with pytest.raises(HTTPException) as exc:
        await add_cdn_host(
            CdnAddIn(host="cdn.jsdelivr.net"),
            admin,
            session,
            settings,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_add_endpoint_rejects_invalid_shape(session):
    cdn_allowlist.invalidate()
    admin = await _mk_admin(session)
    settings = SimpleNamespace(
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    # Pydantic min_length=3 catches bare ones; semantic check catches "no dot".
    with pytest.raises(HTTPException) as exc:
        await add_cdn_host(
            CdnAddIn(host="bareword"),
            admin,
            session,
            settings,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_add_then_list_then_remove_roundtrip(session):
    cdn_allowlist.invalidate()
    admin = await _mk_admin(session)
    settings = SimpleNamespace(
        trusted_cdn_hosts="cdn.jsdelivr.net",
        trusted_cdn_hosts_set=frozenset({"cdn.jsdelivr.net"}),
    )
    unique = f"client-{generate_slug(6)}.example.io"
    out = await add_cdn_host(
        CdnAddIn(host=unique, note="for client demo"),
        admin,
        session,
        settings,
    )
    listing = await list_cdn_allowlist(admin, session, settings)
    assert "cdn.jsdelivr.net" in listing["builtin"]
    hosts = [r["host"] for r in listing["runtime"]]
    assert unique in hosts

    await remove_cdn_host(__import__("uuid").UUID(out["id"]), admin, session)
    listing2 = await list_cdn_allowlist(admin, session, settings)
    hosts2 = [r["host"] for r in listing2["runtime"]]
    assert unique not in hosts2


# ---------- CSP composition ----------


def test_build_csp_falls_back_to_default_when_empty():
    assert build_csp(None) == BUNDLE_CSP
    assert build_csp(frozenset()) == BUNDLE_CSP


def test_build_csp_includes_hosts_in_relevant_directives():
    csp = build_csp(frozenset({"cdn.jsdelivr.net", "fonts.gstatic.com"}))
    # Hosts join script-src, style-src, font-src, connect-src.
    assert "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.gstatic.com" in csp
    assert "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.gstatic.com" in csp
    assert "font-src 'self' data: cdn.jsdelivr.net fonts.gstatic.com" in csp
    assert "connect-src 'self' cdn.jsdelivr.net fonts.gstatic.com" in csp


def test_build_csp_does_not_pollute_img_src():
    """img-src is wildcarded to https: independent of the CDN list, because
    AI demos pull images from arbitrary hosts."""
    csp = build_csp(frozenset({"cdn.jsdelivr.net"}))
    assert "img-src 'self' data: blob: https:;" in csp


def test_build_csp_keeps_frame_ancestors_and_object_locks():
    csp = build_csp(frozenset({"cdn.jsdelivr.net"}))
    # These never relax: the bundle must not be embeddable cross-origin
    # nor able to instantiate plugins.
    assert "frame-ancestors 'self'" in csp
    assert "object-src 'none'" in csp
    assert "form-action 'none'" in csp
