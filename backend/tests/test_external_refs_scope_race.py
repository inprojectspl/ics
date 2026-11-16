"""Concurrent retries keep the public conflict contract under PostgreSQL uniqueness."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain_errors import ConflictError
from app.models import AssetExternalRef, User
from app.services.external_refs import add_ref
from tests.conftest import mk_asset, mk_user


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("system", ["project_standard", "openproject"])
async def test_racing_retry_is_a_conflict_and_preserves_the_winning_parameters(
    session, monkeypatch, changed, system
):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    asset.version = 2
    await session.commit()
    key = (
        {"system": system, "entity": "node", "external_id": "n-race", "external_scope": "project-a"}
        if system == "project_standard"
        else {"system": system, "entity": "work_package", "external_id": "4711"}
    )
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    both_checked = asyncio.Event()
    committed = asyncio.Event()
    original_scalar = AsyncSession.scalar
    checked = set()
    async with factory() as first, factory() as second:

        async def synchronized_scalar(current, statement, *args, **kwargs):
            value = await original_scalar(current, statement, *args, **kwargs)
            columns = getattr(statement, "column_descriptions", [])
            if (
                current in (first, second)
                and columns
                and columns[0].get("entity") is AssetExternalRef
                and columns[0].get("name") == "id"
            ):
                assert value is None
                checked.add(current)
                if len(checked) == 2:
                    both_checked.set()
                await both_checked.wait()
                if current is second:
                    await committed.wait()
            return value

        monkeypatch.setattr(AsyncSession, "scalar", synchronized_scalar)

        async def write(current, *, winner):
            actor = await current.get(User, owner.id)
            try:
                ref = await add_ref(
                    current,
                    actor=actor,
                    asset_id=asset.id,
                    role="context",
                    **key,
                    required=changed and not winner,
                    pinned_version=1 if changed and not winner else 2,
                )
                await current.commit()
                return ref.id
            finally:
                if winner:
                    committed.set()

        result = await asyncio.wait_for(
            asyncio.gather(
                write(first, winner=True), write(second, winner=False), return_exceptions=True
            ),
            timeout=10,
        )
        assert not isinstance(result[0], BaseException), result[0]
        assert isinstance(result[1], ConflictError), repr(result[1])
        assert result[1].code == "external_ref_exists"
        # The conflict is contained in a savepoint; the caller can still inspect
        # the winning link without rolling its entire transaction back.
        stored = (
            await second.scalars(
                select(AssetExternalRef).where(AssetExternalRef.asset_id == asset.id)
            )
        ).all()
        assert len(stored) == 1
        assert stored[0].id == result[0]
        assert stored[0].required is False
        assert stored[0].pinned_version == 2


async def test_non_unique_integrity_failure_is_not_reported_as_duplicate(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    with pytest.raises(IntegrityError) as exc:
        await add_ref(
            session,
            actor=owner,
            asset_id=asset.id,
            system="project_standard",
            entity="node",
            external_id="n-invalid",
            external_scope="project-a",
            role="context",
            origin="invalid",
        )
    assert "ck_asset_external_refs_origin" in str(exc.value)
