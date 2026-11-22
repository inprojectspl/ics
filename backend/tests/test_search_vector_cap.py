"""A text whose search vector would pass the 1 MiB tsvector cap is stored
whole and indexed as far as it fits (migration 0054)."""

from __future__ import annotations

import string
from itertools import islice, product

import pytest
from sqlalchemy import func, select

from app.models import Asset
from tests.conftest import mk_asset, mk_user

pytestmark = pytest.mark.asyncio


def _distinct_words(n: int) -> list[str]:
    return ["".join(w) for w in islice(product(string.ascii_lowercase, repeat=5), n)]


def _matches(word: str):
    return Asset.search_tsv.bool_op("@@")(func.to_tsquery("public.ics_search", word))


async def test_a_text_past_the_vector_cap_is_saved_and_its_start_found(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    words = _distinct_words(110_000)  # about 1.4 MB of vector, 660 kB of text
    asset.search_content = " ".join(words)
    await session.commit()

    found = await session.scalar(select(Asset.id).where(Asset.id == asset.id, _matches(words[0])))
    assert found == asset.id
    stored = await session.scalar(
        select(func.length(Asset.search_content)).where(Asset.id == asset.id)
    )
    assert stored == len(asset.search_content)
    # Only the tail past what fits is left out of the vector.
    assert (
        await session.scalar(select(Asset.id).where(Asset.id == asset.id, _matches(words[-1])))
        is None
    )


async def test_a_text_under_the_cap_is_indexed_whole(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    words = _distinct_words(20_000)
    asset.search_content = " ".join(words)
    await session.commit()
    assert await session.scalar(select(Asset.id).where(Asset.id == asset.id, _matches(words[-1])))
