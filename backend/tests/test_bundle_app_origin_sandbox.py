"""Bundle files served on the app origin (the legacy `/static/` links of
documents and shares) are sandboxed: a bundle opened there runs in an opaque
origin and cannot call the API as the signed-in visitor. The isolated viewer
origin keeps its own CSP without the sandbox."""

from __future__ import annotations

import pytest

from app.models import ShareLink
from app.routes.html_viewer import issue_grant, user_basis
from app.slug import generate_token
from tests.conftest import login_as, mk_asset, mk_user, put_blob

_PAGE = b"<!doctype html><script>fetch('/api/auth/me')</script>"


async def _bundle(session, owner):
    asset = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", _PAGE)
    await put_blob(asset, "logo.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")
    return asset


def _assert_sandboxed(response) -> None:
    assert response.status_code == 200, response.text
    csp = response.headers["content-security-policy"]
    directives = [d.strip() for d in csp.split(";") if d.strip()]
    sandbox = next(d for d in directives if d.startswith("sandbox"))
    assert "allow-scripts" in sandbox.split()
    assert "allow-same-origin" not in sandbox.split()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["index.html", "logo.svg"])
async def test_asset_static_is_sandboxed(client, session, fs_storage, path):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    await session.commit()
    await login_as(client, owner)

    _assert_sandboxed(await client.get(f"/api/assets/by-slug/{asset.slug}/static/{path}"))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["index.html", "logo.svg"])
async def test_share_static_is_sandboxed(client, session, fs_storage, path):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    token = generate_token()
    session.add(ShareLink(asset_id=asset.id, token=token, mode="public", created_by=owner.id))
    await session.commit()

    _assert_sandboxed(await client.get(f"/api/share/{token}/static/{path}"))


@pytest.mark.asyncio
async def test_isolated_viewer_is_not_sandboxed(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    await session.commit()

    r = await client.get(
        f"/html/_/grant?t={issue_grant(asset.id, basis=user_basis(owner.id))}",
        follow_redirects=False,
    )
    assert r.status_code == 302
    r = await client.get(f"/html/{asset.slug}/index.html")
    assert r.status_code == 200, r.text
    assert "sandbox" not in r.headers["content-security-policy"]
