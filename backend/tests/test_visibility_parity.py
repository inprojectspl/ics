"""Visibility parity test: /index and /search-mcp must agree on who sees
which assets, and both must match the semantics of
`permissions.effective_role`.

The visibility rule has a single source (`permissions.visible_assets_filter`);
any drift between the listing paths fails here.

Matrix: 8 principals x 5 assets (plain / project / direct-share /
assigned to a second project (ADR-0017) / soft-deleted), all tagged with a unique nonce in title and content. The index
is scoped with `q=` (title substring), search runs full-text; both return
exactly the same expected set of slugs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.slug import generate_slug
from tests.conftest import login_as as _login
from tests.conftest import mk_admin, mk_asset, mk_user


async def _seed_matrix(session):
    """Builds the matrix: an owner with 4 assets (nonce in title+content),
    a project with an accepted and a pending member, a direct share."""
    from app.models import AssetProjectShare, AssetShare, Project, ProjectMember

    nonce = f"nonce{generate_slug(8)}"

    owner = await mk_user(session)
    member_ok = await mk_user(session)
    member_pending = await mk_user(session)
    share_viewer = await mk_user(session)
    admin = await mk_admin(session)
    stranger = await mk_user(session)
    assigned_viewer = await mk_user(session)
    assigned_pending = await mk_user(session)

    project = Project(slug=generate_slug(), name=f"Parity {nonce}", created_by=owner.id)
    assigned_project = Project(slug=generate_slug(), name=f"Assigned {nonce}", created_by=owner.id)
    session.add_all([project, assigned_project])
    await session.flush()
    session.add_all(
        [
            ProjectMember(
                project_id=project.id,
                user_id=member_ok.id,
                role="editor",
                accepted_at=datetime.now(UTC),
            ),
            ProjectMember(
                project_id=project.id,
                user_id=member_pending.id,
                role="editor",
                accepted_at=None,
            ),
            ProjectMember(
                project_id=assigned_project.id,
                user_id=assigned_viewer.id,
                role="viewer",
                accepted_at=datetime.now(UTC),
            ),
            ProjectMember(
                project_id=assigned_project.id,
                user_id=assigned_pending.id,
                role="editor",
                accepted_at=None,
            ),
        ]
    )

    async def _asset(title_suffix: str, **kw):
        a = await mk_asset(session, owner, title=f"{nonce} {title_suffix}", **kw)
        a.search_content = f"content {nonce} {title_suffix}"
        return a

    a_plain = await _asset("plain")
    a_proj = await _asset("project")
    a_proj.project_id = project.id
    a_shared = await _asset("shared")
    session.add(AssetShare(asset_id=a_shared.id, user_id=share_viewer.id, role="viewer"))
    a_assigned = await _asset("assigned")
    await session.flush()
    session.add(
        AssetProjectShare(asset_id=a_assigned.id, project_id=assigned_project.id, role="editor")
    )
    a_deleted = await _asset("deleted")
    a_deleted.deleted_at = datetime.now(UTC)

    await session.commit()

    principals = {
        "owner": (owner, {a_plain.slug, a_proj.slug, a_shared.slug, a_assigned.slug}),
        "member_ok": (member_ok, {a_proj.slug}),
        "member_pending": (member_pending, set()),
        "share_viewer": (share_viewer, {a_shared.slug}),
        "admin": (admin, {a_plain.slug, a_proj.slug, a_shared.slug, a_assigned.slug}),
        "stranger": (stranger, set()),
        "assigned_viewer": (assigned_viewer, {a_assigned.slug}),
        "assigned_pending": (assigned_pending, set()),
    }
    return nonce, principals, a_plain


@pytest.mark.asyncio
async def test_index_and_search_agree_on_visibility_matrix(client, session):
    nonce, principals, _ = await _seed_matrix(session)

    for name, (principal, expected) in principals.items():
        await _login(client, principal)

        r_index = await client.get(f"/api/assets/index?q={nonce}")
        assert r_index.status_code == 200, (name, r_index.text)
        index_slugs = {item["slug"] for item in r_index.json()["items"]}

        r_search = await client.get(f"/api/assets/search-mcp?q={nonce}")
        assert r_search.status_code == 200, (name, r_search.text)
        search_slugs = {item["slug"] for item in r_search.json()["items"]}

        for path in ("/api/assets/search", "/api/assets"):
            response = await client.get(path, params={"q": nonce})
            assert response.status_code == 200, (name, response.text)
            body = response.json()
            items = body if isinstance(body, list) else body["items"]
            assert {item["slug"] for item in items} == expected, (name, path)

        assert index_slugs == expected, f"{name}: /index sees {index_slugs}, expected {expected}"
        assert search_slugs == expected, f"{name}: /search sees {search_slugs}, expected {expected}"


@pytest.mark.asyncio
async def test_index_access_role_matches_meta_for_admin(client, session):
    """/index and /by-slug/{slug}/meta (effective_role) both report
    access_role='owner_file' to an admin on other users' assets, through the
    admin bypass in _build_role_case."""
    nonce, principals, a_plain = await _seed_matrix(session)
    admin = principals["admin"][0]
    await _login(client, admin)

    r_index = await client.get(f"/api/assets/index?q={nonce}")
    roles = {item["slug"]: item["access_role"] for item in r_index.json()["items"]}
    assert roles[a_plain.slug] == "owner_file"

    r_meta = await client.get(f"/api/assets/by-slug/{a_plain.slug}/meta")
    assert r_meta.json()["access_role"] == "owner_file"


@pytest.mark.asyncio
async def test_index_scope_flags_still_narrow_visibility(client, session):
    """Index scope filters (`shared_with_me`, `owned=false`) still narrow to
    'access through someone else'."""
    nonce, principals, _ = await _seed_matrix(session)
    member_ok, _expected = principals["member_ok"]
    await _login(client, member_ok)

    r = await client.get(f"/api/assets/index?q={nonce}&shared_with_me=true")
    slugs = {item["slug"] for item in r.json()["items"]}
    assert slugs == _expected  # the project asset is the member's only access through someone else

    owner, owner_expected = principals["owner"]
    await _login(client, owner)
    r2 = await client.get(f"/api/assets/index?q={nonce}&shared_with_me=true")
    # The owner has nothing through someone else: all 4 are their own.
    assert {item["slug"] for item in r2.json()["items"]} == set()
    r3 = await client.get(f"/api/assets/index?q={nonce}")
    assert {item["slug"] for item in r3.json()["items"]} == owner_expected


@pytest.mark.asyncio
async def test_index_access_role_matches_meta_for_project_share(client, session):
    """A project share (ADR-0017) is capped by the member's project role: an
    editor share seen by a project viewer is `viewer`, in /index and in meta
    alike. `shared_with_me` includes it, because it is someone else's file."""
    nonce, principals, _ = await _seed_matrix(session)
    assigned_viewer, expected = principals["assigned_viewer"]
    await _login(client, assigned_viewer)

    r_index = await client.get(f"/api/assets/index?q={nonce}")
    roles = {item["slug"]: item["access_role"] for item in r_index.json()["items"]}
    assert set(roles) == expected
    (slug,) = expected
    assert roles[slug] == "viewer"
    r_meta = await client.get(f"/api/assets/by-slug/{slug}/meta")
    assert r_meta.json()["access_role"] == "viewer"

    r_scope = await client.get(f"/api/assets/index?q={nonce}&shared_with_me=true")
    assert {item["slug"] for item in r_scope.json()["items"]} == expected


@pytest.mark.asyncio
async def test_context_pack_follows_matrix_with_graph_access(client, session):
    """The context pack (ADR-0019) lists the same documents as /index, minus
    those reached only through a direct viewer share: those need graph access
    (ADR-0016), which such a share does not give."""
    import secrets

    from sqlalchemy import select

    from app.models import Asset, AssetExternalRef

    nonce, principals, _ = await _seed_matrix(session)
    wp = str(secrets.randbelow(10**9) + 1)
    matrix_assets = (
        await session.scalars(select(Asset).where(Asset.title.like(f"{nonce}%")))
    ).all()
    assert len(matrix_assets) == 5
    session.add_all(
        AssetExternalRef(
            asset_id=a.id,
            system="openproject",
            entity="work_package",
            external_id=wp,
            role="context",
            origin="manual",
        )
        for a in matrix_assets
    )
    await session.commit()
    shared_only = {"share_viewer"}

    for name, (principal, expected) in principals.items():
        await _login(client, principal)
        r = await client.get("/api/context", params={"wp": wp, "budget_tokens": 4000})
        assert r.status_code == 200, (name, r.text)
        pack = {d["slug"] for d in r.json()["documents"]}
        assert pack == (set() if name in shared_only else expected), name
        assert "hidden_count" not in r.json(), name
