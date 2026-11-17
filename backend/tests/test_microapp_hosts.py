"""Short public hosts of micro-applications: allocation, permanent
reservation and the exact mapping of a host to one app environment."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.constants import MICRO_APPLICATION
from app.domain_errors import NotFoundError
from app.models import Asset, MicroAppEnvironment, MicroAppHostName
from app.services.micro_applications import hosts
from app.slug import _ALPHABET, generate_slug
from tests.conftest import mk_asset, mk_user


def _forced(monkeypatch, *names: str) -> None:
    """The generator returns these names in turn."""
    queue = list(names)
    monkeypatch.setattr(hosts, "generate_slug", lambda length: queue.pop(0))


async def _asset(session) -> Asset:
    owner = await mk_user(session)
    return await mk_asset(session, owner, kind=MICRO_APPLICATION, entry_path="public/index.html")


async def _app(session, name: str | None = None) -> MicroAppEnvironment:
    asset = await _asset(session)
    env = MicroAppEnvironment(
        asset_id=asset.id,
        environment="prod",
        asset_hex=asset.id.hex,
        host_name=name or await hosts.allocate_host_name(session, get_settings(), asset.id),
    )
    session.add(env)
    await session.commit()
    return env


async def test_a_name_has_eight_readable_characters_and_never_changes(session):
    settings = get_settings()
    env = await _app(session)
    assert len(env.host_name) == hosts.HOST_NAME_LENGTH == 8
    assert set(env.host_name) <= set(_ALPHABET)
    # Asking again (a new release, a restart) gives the reserved name back.
    assert await hosts.allocate_host_name(session, settings, env.asset_id) == env.host_name
    assert hosts.app_url(settings, env) == (
        f"{settings.microapps_app_scheme}://{env.host_name}.{settings.microapps_app_host_suffix}/"
    )
    # Other slugs keep their default length.
    assert len(generate_slug()) == 12


async def test_a_taken_name_is_drawn_again(session, monkeypatch):
    taken = (await _app(session)).host_name
    fresh = generate_slug(8)
    asset = await _asset(session)
    _forced(monkeypatch, taken, fresh)
    assert await hosts.allocate_host_name(session, get_settings(), asset.id) == fresh
    # The conflict left the transaction usable.
    await session.commit()


async def test_a_name_of_a_configured_alias_is_never_handed_out(session, monkeypatch):
    settings = get_settings()
    blocked, fresh = generate_slug(8), generate_slug(8)
    monkeypatch.setattr(
        settings,
        "microapps_public_aliases",
        f"{blocked}.{settings.microapps_app_host_suffix}={'c' * 32}",
    )
    asset = await _asset(session)
    _forced(monkeypatch, blocked, fresh)
    assert await hosts.allocate_host_name(session, settings, asset.id) == fresh


async def test_allocation_gives_up_after_a_run_of_conflicts(session, monkeypatch):
    taken = (await _app(session)).host_name
    asset = await _asset(session)
    _forced(monkeypatch, *[taken] * hosts.MAX_ATTEMPTS)
    with pytest.raises(RuntimeError):
        await hosts.allocate_host_name(session, get_settings(), asset.id)


async def test_parallel_allocations_wait_for_each_other_and_never_share_a_name(
    session, monkeypatch
):
    settings = get_settings()
    first_asset, second_asset = await _asset(session), await _asset(session)
    await session.commit()
    contested, other = generate_slug(8), generate_slug(8)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as a, factory() as b:
        _forced(monkeypatch, contested, contested, other)
        assert await hosts.allocate_host_name(a, settings, first_asset.id) == contested
        # B wants the same name while A has not committed yet: it waits on
        # the primary key, sees A's row after the commit and draws again.
        racer = asyncio.create_task(hosts.allocate_host_name(b, settings, second_asset.id))
        await asyncio.sleep(0.2)
        assert not racer.done()
        await a.commit()
        assert await racer == other
        await b.commit()

    # Many creations at once: every one gets its own name.
    monkeypatch.setattr(hosts, "generate_slug", generate_slug)
    assets = [await _asset(session) for _ in range(12)]
    await session.commit()

    async def one(asset_id):
        async with factory() as s:
            name = await hosts.allocate_host_name(s, settings, asset_id)
            await s.commit()
            return name

    names = await asyncio.gather(*(one(a.id) for a in assets))
    assert len(set(names)) == len(names)


async def test_parallel_requests_for_one_app_agree_on_its_name(session, monkeypatch):
    settings = get_settings()
    asset = await _asset(session)
    await session.commit()
    first, second = generate_slug(8), generate_slug(8)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as a, factory() as b:
        _forced(monkeypatch, first, second)
        assert await hosts.allocate_host_name(a, settings, asset.id) == first
        racer = asyncio.create_task(hosts.allocate_host_name(b, settings, asset.id))
        await asyncio.sleep(0.2)
        await a.commit()
        assert await racer == first
    rows = await session.scalars(
        select(MicroAppHostName.name).where(MicroAppHostName.asset_id == asset.id)
    )
    assert list(rows) == [first]


async def test_a_name_stays_reserved_after_its_asset_is_purged(session, monkeypatch):
    settings = get_settings()
    env = await _app(session)
    name, asset_id = env.host_name, env.asset_id
    await session.execute(delete(Asset).where(Asset.id == asset_id))
    await session.commit()
    assert (
        await session.scalar(
            select(MicroAppEnvironment).where(MicroAppEnvironment.host_name == name)
        )
        is None
    )
    held = await session.get(MicroAppHostName, name, populate_existing=True)
    assert held is not None and held.asset_id == asset_id

    host = f"{name}.{settings.microapps_app_host_suffix}"
    with pytest.raises(NotFoundError):
        await hosts.env_for_host(session, settings, host)
    newcomer = await _asset(session)
    fresh = generate_slug(8)
    _forced(monkeypatch, name, fresh)
    assert await hosts.allocate_host_name(session, settings, newcomer.id) == fresh


async def test_the_database_refuses_a_malformed_name(session):
    for bad in ("ABCDEFGH", "abcdefg0", "abcdefg", "abcdefghj"):
        # The check constraint, or the column type for a 9th character.
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO microapp_host_names (name, asset_id, environment) "
                    "VALUES (:n, :a, 'prod')"
                ),
                {"n": bad, "a": uuid.uuid4()},
            )
        await session.rollback()


async def test_a_host_selects_exactly_one_app(session, monkeypatch):
    settings = get_settings()
    suffix = settings.microapps_app_host_suffix
    env, other = await _app(session), await _app(session)
    alias = f"demo-{generate_slug(6)}.tunnel.example"
    monkeypatch.setattr(settings, "microapps_public_aliases", f"{alias}={other.asset_hex}")

    async def resolve(host):
        return (await hosts.env_for_host(session, settings, host)).id

    assert await resolve(f"{env.host_name}.{suffix}") == env.id
    assert await resolve(f"{env.host_name.upper()}.{suffix}") == env.id
    assert await resolve(f"a-{env.asset_hex}-prod.{suffix}") == env.id
    assert await resolve(alias) == other.id
    assert await resolve(f"{other.host_name}.{suffix}") == other.id
    # The alias replaces the advertised URL of its app, the others are short.
    assert hosts.app_url(settings, other) == f"https://{alias}/"
    assert hosts.app_url(settings, env).endswith(f"//{env.host_name}.{suffix}/")

    unknown = generate_slug(8)
    for host in (
        f"{unknown}.{suffix}",
        f"{env.host_name}.evil.example",
        f"{env.host_name}.{suffix}.evil.example",
        f"x.{env.host_name}.{suffix}",
        f"{env.host_name[:7]}.{suffix}",
        f"a-{env.asset_hex}-dev.{suffix}",
        f"a-{'0' * 32}-prod.{suffix}",
        env.host_name,
        suffix,
    ):
        with pytest.raises(NotFoundError):
            await resolve(host)
