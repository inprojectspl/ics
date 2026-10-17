"""`assets.content_hash` (migration 0040) must equal the same hash computed
inline in SQL: SHA-256 of the lower-cased text with whitespace collapsed,
NULL for empty text."""

from __future__ import annotations

import hashlib
import re

import pytest
from sqlalchemy import text

from tests.conftest import mk_asset, mk_user

SAMPLES = [
    "Plain text",
    "  Crème\tBRÛLÉE \n\n naïve  ",
    r"back\slash \x41 and 'quotes'",
    "UPPER lower",
]


def _expected(value: str) -> str | None:
    normalised = re.sub(r"\s+", " ", value).strip(" ").lower()
    return hashlib.sha256(normalised.encode()).hexdigest() if normalised else None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [*SAMPLES, "", "   \n\t "])
async def test_generated_hash_matches_the_normalised_text(session, value):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    asset.search_content = value
    await session.flush()
    stored = await session.scalar(
        text("SELECT content_hash FROM assets WHERE id = :id"), {"id": asset.id}
    )
    inline = await session.scalar(
        text(
            "SELECT CASE WHEN coalesce(n, '') <> '' "
            "THEN encode(sha256(convert_to(n, 'UTF8')), 'hex') END "
            r"FROM (SELECT lower(btrim(regexp_replace(:v, '\s+', ' ', 'g'))) AS n) AS s"
        ),
        {"v": value},
    )
    assert stored == inline
    if value in SAMPLES:
        assert stored == _expected(value)


@pytest.mark.asyncio
async def test_null_content_has_no_hash(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    stored = await session.scalar(
        text("SELECT content_hash FROM assets WHERE id = :id"), {"id": asset.id}
    )
    assert stored is None
