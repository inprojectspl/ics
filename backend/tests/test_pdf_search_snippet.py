"""A PDF search snippet that crosses a page break must not carry the form
feed that separates pages in the search blob."""

from __future__ import annotations

import pytest

from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


@pytest.mark.asyncio
async def test_snippet_across_pages_has_no_form_feed(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    data = make_pdf(["Kangaroo field guide", "Second page about wombats"])
    r = await client.post("/api/assets/pdf", files=pdf_file("guide.pdf", data))
    assert r.status_code == 201, r.text

    hits = (await client.get("/api/assets/search-mcp?q=wombats")).json()["items"]
    snippet = hits[0]["snippets"][0]
    assert "\f" not in snippet["text"]
    assert "Kangaroo field guide\n\nSecond page about <em>wombats</em>" in snippet["text"]
    assert snippet["page"] == 2
