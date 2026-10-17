"""`estimated_tokens`: the calibrated rule (`app.token_estimate`) and the
stored size of the default agent read (`Asset.read_tokens`) per kind."""

from __future__ import annotations

import json
import math
from pathlib import Path

import orjson
import pytest

from app.html_markdown import html_to_markdown
from app.models import Asset
from app.token_estimate import tokens_for_chars, tokens_for_json, tokens_for_text
from tests.conftest import login_as, mk_asset, mk_user
from tests.pdf_factory import make_pdf, pdf_file

_POLISH = (
    "Zespół wdraża logowanie jednokrotne. Każda usługa sprawdza podpis tokenu, "
    "a błędy zgłaszamy w jednym formacie z kodem i krótkim opisem dla człowieka. "
)
_ENGLISH = (
    "The team rolls out single sign-on. Every service checks the token signature "
    "and reports errors in one format with a code and a short human description. "
)


def test_polish_text_counts_more_tokens_per_character_than_english():
    polish, english = _POLISH * 20, _ENGLISH * 20
    assert tokens_for_text(english) == math.ceil(len(english) / 4)
    assert tokens_for_text(polish) == math.ceil(len(polish) / 2.7)
    assert tokens_for_text("") == 0
    assert tokens_for_chars(10) == 3


# Real context packs (Polish demo data) with their size measured in cl100k.
_PACKS = json.loads((Path(__file__).parent / "fixtures" / "context_packs_cl100k.json").read_text())


@pytest.mark.parametrize("fixture", _PACKS, ids=[p["name"] for p in _PACKS])
def test_json_estimate_covers_real_packs_with_a_small_margin(fixture):
    measured = fixture["cl100k"]
    estimate = tokens_for_json(fixture["pack"])
    assert measured <= estimate <= measured * 1.08
    # The whole-text rule undercounts JSON full of slugs.
    assert tokens_for_text(orjson.dumps(fixture["pack"]).decode()) < measured


def test_json_estimate_counts_identifiers_and_literals():
    assert tokens_for_json({}) == 1
    assert tokens_for_json(["a1b2c3d4e5f6"]) == 8 + 1
    assert tokens_for_json([True, None, 1234]) == 1 + 1 + 2 + 1


async def _login(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    return user


async def _meta(client, slug: str) -> dict:
    r = await client.get(f"/api/assets/by-slug/{slug}/meta")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_markdown_single_and_new_version(client, session, fs_storage):
    await _login(client, session)
    r = await client.post(
        "/api/assets", files={"file": ("spec.md", _POLISH.encode(), "text/markdown")}
    )
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    assert (await _meta(client, slug))["estimated_tokens"] == tokens_for_text(_POLISH)

    asset_id = (await _meta(client, slug))["id"]
    longer = _ENGLISH * 5
    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files={"files": ("spec.md", longer.encode(), "text/markdown")},
    )
    assert r.status_code == 201, r.text
    assert (await _meta(client, slug))["estimated_tokens"] == tokens_for_text(longer)


@pytest.mark.asyncio
async def test_collection_reports_the_entry_file(client, session, fs_storage):
    await _login(client, session)
    entry, other = "# Start\n\nBriefly.\n", _POLISH * 30
    r = await client.post(
        "/api/assets/collection",
        files=[
            ("files", ("README.md", entry.encode(), "text/markdown")),
            ("files", ("long.md", other.encode(), "text/markdown")),
        ],
        data={"paths": ["README.md", "long.md"]},
    )
    assert r.status_code == 201, r.text
    meta = await _meta(client, r.json()["slug"])
    assert meta["estimated_tokens"] == tokens_for_text(entry)
    items = (await client.get("/api/assets/index")).json()["items"]
    assert items[0]["estimated_tokens"] == tokens_for_text(entry)


@pytest.mark.asyncio
async def test_pdf_reports_its_markdown(client, session, fs_storage):
    await _login(client, session)
    data = make_pdf(["Rivers and mountains in general terms. " * 10, "Second page text."])
    r = await client.post("/api/assets/pdf", files=pdf_file("atlas.pdf", data))
    assert r.status_code == 201, r.text
    slug = r.json()["slug"]
    read = await client.get(f"/api/assets/by-slug/{slug}/file-mcp")
    assert read.status_code == 200, read.text
    tokens = (await _meta(client, slug))["estimated_tokens"]
    # file-mcp joins the lines it returns; the stored estimate covers the same text.
    assert tokens == pytest.approx(tokens_for_text(read.json()["content"]), abs=2)
    assert tokens > 100


@pytest.mark.asyncio
async def test_html_bundle_reports_the_entry_page_as_markdown(client, session, fs_storage):
    await _login(client, session)
    html = (
        "<html><head><style>body{color:red}</style></head><body>"
        f"<h1>Report</h1><p>{_POLISH}</p><script>var x = 1;</script></body></html>"
    )
    r = await client.post(
        "/api/assets/html",
        files=[("files", ("index.html", html.encode(), "text/html"))],
        data={"paths": ["index.html"]},
    )
    assert r.status_code == 201, r.text
    meta = await _meta(client, r.json()["slug"])
    assert meta["estimated_tokens"] == tokens_for_text(html_to_markdown(html))


@pytest.mark.asyncio
async def test_rows_without_read_tokens_fall_back_to_their_size(client, session):
    user = await mk_user(session)
    md: Asset = await mk_asset(session, user, title="Old note")
    md.size_bytes = 400
    bundle = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    bundle.size_bytes = 400
    await session.commit()
    await login_as(client, user)
    assert (await _meta(client, md.slug))["estimated_tokens"] == 100
    assert (await _meta(client, bundle.slug))["estimated_tokens"] is None
