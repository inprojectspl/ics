"""Metadata on asset creation and change notes on new versions (ADR-0015)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset
from app.oauth import tokens as tokens_mod
from tests.conftest import login_as, mk_doc_type, mk_md_collection, mk_md_single, mk_user
from tests.pdf_factory import make_pdf, pdf_file

_AUDIENCE = "https://ics-test.example/mcp"


def _bearer(user, monkeypatch) -> dict[str, str]:
    settings = get_settings()
    monkeypatch.setattr(settings, "mcp_resource_uri", _AUDIENCE)
    monkeypatch.setattr(settings, "debug", True)
    token, _jti = tokens_mod.sign_access_jwt(
        settings=settings,
        user=user,
        client_id_external="ics-mcp-stdio",
        scopes=["ics"],
        audience=_AUDIENCE,
    )
    return {"Authorization": f"Bearer {token}"}


async def _asset(session, asset_id: str) -> Asset:
    session.expire_all()
    return (await session.execute(select(Asset).where(Asset.id == asset_id))).scalar_one()


@pytest.mark.asyncio
async def test_markdown_upload_with_doc_type_and_summary(client, session, fs_storage):
    user = await mk_user(session)
    doc_type = await mk_doc_type(session, default_review_days=365)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/assets",
        files={"file": ("plan.md", b"# Plan\n", "text/markdown")},
        data={"doc_type": doc_type.key, "summary": "The delivery plan."},
    )
    assert r.status_code == 201, r.text
    meta = (await client.get(f"/api/assets/by-slug/{r.json()['slug']}/meta")).json()
    assert meta["doc_type"] == doc_type.key
    assert meta["summary"] == "The delivery plan."
    assert meta["summary_source"] == "human"
    assert meta["flags"] == []
    asset = await _asset(session, r.json()["id"])
    assert asset.summary_version == 1
    assert asset.review_due_at is not None


@pytest.mark.asyncio
async def test_unknown_doc_type_rejected_before_any_write(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post(
        "/api/assets/collection",
        files=[("files", ("a.md", b"# A\n", "text/markdown"))],
        data={"paths": ["a.md"], "doc_type": "no_such_type"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_unknown"
    count = (await session.execute(select(Asset).where(Asset.owner_id == user.id))).all()
    assert count == []

    r = await client.post(
        "/api/assets/pdf",
        files=pdf_file("a.pdf", make_pdf(["Hello"])),
        data={"doc_type": "no_such_type"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "doc_type_unknown"


@pytest.mark.asyncio
async def test_mcp_create_with_summary_is_agent_written(client, session, fs_storage, monkeypatch):
    user = await mk_user(session)
    await session.commit()
    headers = _bearer(user, monkeypatch)

    r = await client.post(
        "/api/assets",
        files={"file": ("n.md", b"# N\n", "text/markdown")},
        data={"summary": "Notes from the agent."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    asset = await _asset(session, r.json()["id"])
    assert asset.summary_source == "agent"

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "Dash",
            "entry_path": "index.html",
            "summary": "A dashboard.",
            "files": [{"path": "index.html", "content_text": "<h1>x</h1>"}],
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    summary, source = (
        await session.execute(
            select(Asset.summary, Asset.summary_source).where(Asset.id == r.json()["id"])
        )
    ).one()
    assert (summary, source) == ("A dashboard.", "agent")


@pytest.mark.asyncio
async def test_change_note_is_listed_with_versions(client, session, fs_storage):
    _user, asset = await mk_md_single(client, session, content="# One\n", entry="doc.md")

    r = await client.put(
        f"/api/assets/{asset.id}/content",
        json={"content": "# Two\n", "change_note": "  Fixed the title.  "},
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[("files", ("doc.md", b"# Three\n", "text/markdown"))],
        data={"change_note": "Rewrote from scratch."},
    )
    assert r.status_code == 201, r.text
    r = await client.post(f"/api/assets/{asset.id}/versions/2/restore?change_note=Back%20to%20v2")
    assert r.status_code == 201

    versions = (await client.get(f"/api/assets/{asset.id}/versions")).json()
    notes = {v["version"]: v["change_note"] for v in versions}
    assert notes[2] == "Fixed the title."
    assert notes[3] == "Rewrote from scratch."
    assert notes[4] == "Back to v2"


@pytest.mark.asyncio
async def test_change_note_on_collection_file_operations(client, session, fs_storage):
    _user, asset = await mk_md_collection(client, session, {"README.md": "# R\n"})

    r = await client.post(
        f"/api/assets/{asset.id}/files/empty",
        json={"path": "b.md", "change_note": "Stub for B."},
    )
    assert r.status_code == 201
    r = await client.patch(
        f"/api/assets/{asset.id}/files/move",
        json={"from_path": "b.md", "to_path": "c.md", "change_note": "Renamed."},
    )
    assert r.status_code == 200
    r = await client.delete(
        f"/api/assets/{asset.id}/files", params={"path": "c.md", "change_note": "Dropped."}
    )
    assert r.status_code == 200

    versions = (await client.get(f"/api/assets/{asset.id}/versions")).json()
    assert [v["change_note"] for v in versions] == ["Dropped.", "Renamed.", "Stub for B."]
