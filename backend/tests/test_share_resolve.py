"""Tests for `routes/shares/resolve.py`: POST /api/share/{token}/resolve.

Bearer/cookie-authenticated one-shot resolve for MCP agents:
- mode-aware authorization without a session cookie (public / inline password /
  org_sso by domain / magic_email by account address),
- 401 for a missing or wrong password, plus a rate limit shared with POST /auth,
- 410 for revoked/expired/max_views (the same gates as the viewer),
- content: raw markdown + tree (collections) / files (html_bundle),
- view_count: same semantics as GET /doc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Asset, ShareLink
from app.passwords import hash_password
from app.slug import generate_slug, generate_token
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _mk_share(session, asset: Asset, mode: str = "public", **kwargs) -> ShareLink:
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode=mode,
        **kwargs,
    )
    session.add(share)
    await session.flush()
    return share


async def _resolve(client, token: str, **body) -> object:
    return await client.post(f"/api/share/{token}/resolve", json=body)


@pytest.mark.asyncio
async def test_resolve_requires_authentication(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await put_blob(asset, "doc.md", b"# Hello")
    share = await _mk_share(session, asset)
    await session.commit()

    r = await _resolve(client, share.token)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_unknown_token_404(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await _resolve(client, "no-such-token")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resolve_public_returns_raw_content_and_counts_view(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# Hello\n\ntext")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, reader)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == "# Hello\n\ntext"
    assert body["asset"]["slug"] == asset.slug
    assert body["asset"]["kind"] == "md_single"
    assert body["share"]["mode"] == "public"
    assert body["share"]["view_count"] == 1
    assert body["tree"] is None
    assert body["files"] is None

    await session.refresh(share)
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_resolve_markdown_format_drops_comments(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"<!-- generator v1 -->\n# Hello")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, format="markdown")
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "\n# Hello"

    r = await _resolve(client, share.token)
    assert r.json()["content"] == "<!-- generator v1 -->\n# Hello"


@pytest.mark.asyncio
async def test_resolve_untitled_asset(client, session, fs_storage):
    # `title` is nullable, so the response model must accept None.
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    asset.title = None
    await put_blob(asset, "doc.md", b"# Hello")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 200
    assert r.json()["asset"]["title"] is None


@pytest.mark.asyncio
async def test_resolve_password_share_without_password_401(client, session, fs_storage):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Secret")
    share = await _mk_share(
        session, asset, mode="password", password_hash=hash_password("VisitorPass1!")
    )
    await session.commit()
    await _login(client, stranger)

    r = await _resolve(client, share.token)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_password_share_wrong_password_401(client, session, fs_storage):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Secret")
    share = await _mk_share(
        session, asset, mode="password", password_hash=hash_password("VisitorPass1!")
    )
    await session.commit()
    await _login(client, stranger)

    r = await _resolve(client, share.token, password="wrong-password")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_password_share_correct_password_200(client, session, fs_storage):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Secret")
    share = await _mk_share(
        session, asset, mode="password", password_hash=hash_password("VisitorPass1!")
    )
    await session.commit()
    await _login(client, stranger)

    r = await _resolve(client, share.token, password="VisitorPass1!")
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "# Secret"


@pytest.mark.asyncio
async def test_resolve_password_rate_limited_after_failures(client, session, fs_storage):
    """Once the SHARE_PASSWORD bucket is exhausted even the correct password gets
    401: resolve shares the limiter with POST /auth, so it opens no second pool of attempts."""
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Secret")
    share = await _mk_share(
        session, asset, mode="password", password_hash=hash_password("VisitorPass1!")
    )
    await session.commit()
    await _login(client, stranger)

    for _ in range(5):
        r = await _resolve(client, share.token, password="wrong-password")
        assert r.status_code == 401

    r = await _resolve(client, share.token, password="VisitorPass1!")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_resolve_org_sso_allowed_domain_200(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)  # default email in the example.com domain
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Org doc")
    share = await _mk_share(session, asset, mode="org_sso")
    await session.commit()
    await _login(client, reader)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "# Org doc"


@pytest.mark.asyncio
async def test_resolve_org_sso_foreign_domain_403(client, session, fs_storage):
    owner = await mk_user(session)
    outsider = await mk_user(session, email=f"out+{generate_slug(6)}@outside.example")
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Org doc")
    share = await _mk_share(session, asset, mode="org_sso")
    await session.commit()
    await _login(client, outsider)

    r = await _resolve(client, share.token)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_resolve_magic_email_listed_account_200(client, session, fs_storage):
    """An account authenticated with a whitelisted address needs no magic link;
    matching is case-insensitive."""
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# For you")
    share = await _mk_share(
        session, asset, mode="magic_email", allowed_emails=[reader.email.upper()]
    )
    await session.commit()
    await _login(client, reader)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "# For you"


@pytest.mark.asyncio
async def test_resolve_magic_email_unlisted_account_403(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Not for you")
    share = await _mk_share(
        session, asset, mode="magic_email", allowed_emails=["someone-else@example.com"]
    )
    await session.commit()
    await _login(client, reader)

    r = await _resolve(client, share.token)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_resolve_revoked_410(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Gone")
    share = await _mk_share(session, asset, revoked_at=datetime.now(UTC))
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_resolve_expired_410(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Gone")
    share = await _mk_share(session, asset, expires_at=datetime.now(UTC) - timedelta(hours=1))
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_resolve_max_views_exhausted_410(client, session, fs_storage):
    owner = await mk_user(session)
    guest = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Limited")
    share = await _mk_share(session, asset, max_views=1)
    await session.commit()
    await _login(client, guest)

    r = await _resolve(client, share.token)
    assert r.status_code == 200

    r = await _resolve(client, share.token)
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_resolve_collection_entry_and_tree(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"# Index")
    await put_blob(asset, "notes/foo.md", b"# Foo")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == "# Index"
    assert body["path"] == "index.md"
    assert set(body["tree"]) == {"index.md", "notes/foo.md"}


@pytest.mark.asyncio
async def test_resolve_collection_specific_path(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"# Index")
    await put_blob(asset, "notes/foo.md", b"# Foo")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, path="notes/foo.md")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == "# Foo"
    assert body["path"] == "notes/foo.md"


@pytest.mark.asyncio
async def test_resolve_collection_missing_path_404(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"# Index")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, path="no/such.md")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_resolve_path_traversal_400(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"# Index")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, path="../../etc/passwd")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resolve_path_rejected_for_md_single_400(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# Solo")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, path="doc.md")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resolve_html_bundle_metadata_only(client, session, fs_storage):
    """Bundle: file list without content; view_count does not grow (same as
    GET /doc, a view is counted only by /html-grant)."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html><body>hi</body></html>")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] is None
    assert body["files"] == ["index.html"]

    await session.refresh(share)
    assert share.view_count == 0


@pytest.mark.asyncio
async def test_resolve_owner_bypasses_password_and_view_count(client, session, fs_storage):
    """A role on the asset (here: owner) skips the mode gate, with no password,
    and does not use up a view (max_views counts guests, not the team)."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Secret")
    share = await _mk_share(
        session, asset, mode="password", password_hash=hash_password("VisitorPass1!")
    )
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "# Secret"
    assert r.json()["share"]["view_count"] == 0

    await session.refresh(share)
    assert share.view_count == 0


@pytest.mark.asyncio
async def test_resolve_revoked_410_even_for_owner(client, session, fs_storage):
    """Link lifecycle gates apply to the owner too: a revoked link is dead
    regardless of the caller's role."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Gone")
    share = await _mk_share(session, asset, revoked_at=datetime.now(UTC))
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_resolve_lines_returns_slice_with_range_meta(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", "\n".join(f"line {i}" for i in range(1, 51)).encode())
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, reader)

    r = await _resolve(client, share.token, lines="10-12")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["content"] == "line 10\nline 11\nline 12"
    assert body["total_lines"] == 50
    assert body["returned_range"] == [10, 12]


@pytest.mark.asyncio
async def test_resolve_lines_clamped_to_file_end(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"a\nb\nc")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, lines="2-999")
    assert r.status_code == 200, r.text
    assert r.json()["content"] == "b\nc"
    assert r.json()["returned_range"] == [2, 3]


@pytest.mark.asyncio
async def test_resolve_lines_range_too_wide_400(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", "\n".join("x" for _ in range(2500)).encode())
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, lines="1-2500")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resolve_large_file_without_lines_400(client, session, fs_storage):
    """A file over the limit without `lines` gets an explicit 400 with pagination
    instructions, consistent with file-mcp (no unbounded blob is returned)."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", "\n".join("x" for _ in range(2500)).encode())
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_resolve_lines_bad_format_422(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# Doc")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, lines="abc")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_resolve_lines_rejected_for_html_bundle_400(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html></html>")
    share = await _mk_share(session, asset)
    await session.commit()
    await _login(client, owner)

    r = await _resolve(client, share.token, lines="1-10")
    assert r.status_code == 400
