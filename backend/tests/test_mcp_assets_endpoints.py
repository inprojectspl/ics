"""Tests for `routes/mcp_assets.py`, the token-efficient endpoints for MCP.

Covers the key paths (highest ROI per line of code):
- GET /api/assets/index: listing, pagination, filters (kind, owned).
- GET /api/assets/by-slug/{slug}/meta: single asset, ETag.
- PUT /api/assets/{id}/tags: tag validation.
- POST /api/assets/{id}/undelete: soft-delete + restore.

The rest (outline, search-mcp, html-json, file-mcp) is covered by the
existing `test_outline_parser.py` (parser) and `test_e2e_golden_path.py`
(create flow). mcp_assets is over 800 lines, so full coverage would be a
large investment; we only test the meaningful paths.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import ratelimit
from app.models import Asset
from app.redis_client import get_redis
from app.slug import generate_slug
from tests.conftest import login_as as _login
from tests.conftest import mk_admin, mk_asset, mk_user

# ---------- /index ----------


@pytest.mark.asyncio
async def test_index_returns_empty_for_new_user(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == []
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_index_returns_owned_assets(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Doc 1")
    await mk_asset(session, user, title="Doc 2")
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index")
    assert r.status_code == 200
    body = r.json()
    titles = sorted(item["title"] for item in body["items"])
    assert titles == ["Doc 1", "Doc 2"]
    # Owned: all have access_role owner_file
    assert all(item["access_role"] == "owner_file" for item in body["items"])


@pytest.mark.asyncio
async def test_index_excludes_other_users_assets(client, session):
    me = await mk_user(session)
    other = await mk_user(session)
    await mk_asset(session, me, title="Mine")
    await mk_asset(session, other, title="Theirs")
    await session.commit()
    await _login(client, me)

    r = await client.get("/api/assets/index")
    body = r.json()
    titles = [item["title"] for item in body["items"]]
    assert titles == ["Mine"]


@pytest.mark.asyncio
async def test_index_filter_by_kind(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, kind="md_single", title="MD")
    await mk_asset(session, user, kind="md_collection", title="Vault")
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index?kind=md_single")
    body = r.json()
    titles = [item["title"] for item in body["items"]]
    assert titles == ["MD"]


@pytest.mark.asyncio
async def test_index_pagination_emits_cursor(client, session):
    user = await mk_user(session)
    for i in range(5):
        await mk_asset(session, user, title=f"Doc {i}")
    await session.commit()
    await _login(client, user)

    # First page, limit 2.
    r1 = await client.get("/api/assets/index?limit=2")
    body1 = r1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None

    # Second page via the returned cursor.
    r2 = await client.get(f"/api/assets/index?limit=2&cursor={body1['next_cursor']}")
    body2 = r2.json()
    assert len(body2["items"]) == 2
    # No overlap.
    ids1 = {it["id"] for it in body1["items"]}
    ids2 = {it["id"] for it in body2["items"]}
    assert not (ids1 & ids2)


@pytest.mark.asyncio
async def test_index_invalid_cursor_returns_400(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index?cursor=not-a-real-cursor")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_index_admin_sees_everyone(client, session):
    owner = await mk_user(session)
    await mk_asset(session, owner, title="UserAsset")
    admin = await mk_user(session, role="admin")
    await session.commit()
    await _login(client, admin)

    r = await client.get("/api/assets/index")
    body = r.json()
    titles = [item["title"] for item in body["items"]]
    assert "UserAsset" in titles


# ---------- /by-slug/{slug}/meta ----------


@pytest.mark.asyncio
async def test_meta_returns_asset_for_owner(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Mine")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == asset.slug
    assert body["title"] == "Mine"
    assert body["access_role"] == "owner_file"
    # ETag is set.
    assert "etag" in {k.lower() for k in r.headers.keys()}


@pytest.mark.asyncio
async def test_meta_returns_304_when_etag_matches(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await _login(client, user)

    r1 = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    etag = r1.headers.get("etag")
    assert etag, "The first request must return an ETag"

    r2 = await client.get(
        f"/api/assets/by-slug/{asset.slug}/meta",
        headers={"If-None-Match": etag},
    )
    assert r2.status_code == 304


@pytest.mark.asyncio
async def test_meta_etag_invalidated_by_pin(client, session):
    """Pinning does not bump asset.version, so the ETag must include the pin
    state; otherwise a 304 would serve a stale `pinned` after pin/unpin."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await _login(client, user)

    r1 = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    etag = r1.headers.get("etag")
    assert r1.json()["pinned"] is False

    await client.post(f"/api/assets/{asset.id}/pin")

    r2 = await client.get(
        f"/api/assets/by-slug/{asset.slug}/meta",
        headers={"If-None-Match": etag},
    )
    # The old ETag must no longer match: the pinned flag changed.
    assert r2.status_code == 200
    assert r2.json()["pinned"] is True
    assert r2.headers.get("etag") != etag


@pytest.mark.asyncio
async def test_meta_returns_404_for_unknown_slug(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/by-slug/nonexistent-slug-xyz/meta")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_meta_rejects_other_users_asset(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/meta")
    # 403 or 404, to prevent info leaks.
    assert r.status_code in (403, 404)


# ---------- PUT /{id}/tags ----------


@pytest.mark.asyncio
async def test_update_tags_persists_normalized_values(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await _login(client, user)

    r = await client.put(
        f"/api/assets/{asset.id}/tags",
        json={"tags": ["FOO", "bar-baz", "  spaces  "]},
    )
    assert r.status_code == 200
    body = r.json()
    # Normalization: lowercase, trim. Tag "  spaces  " has whitespace;
    # validation may either reject it or accept it after trimming.
    assert "foo" in body["tags"]
    assert "bar-baz" in body["tags"]


@pytest.mark.asyncio
async def test_update_tags_rejects_invalid_format(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await _login(client, user)

    # Tag with disallowed characters (regex `[a-z0-9_-]{1,32}`).
    r = await client.put(
        f"/api/assets/{asset.id}/tags",
        json={"tags": ["nope$$$"]},
    )
    assert r.status_code in (400, 422)


# ---------- POST /{id}/undelete ----------


@pytest.mark.asyncio
async def test_undelete_restores_soft_deleted_asset(client, session):
    """Restore from soft-delete. The endpoint returns 200 and clears deleted_at.

    The endpoint enqueues a rebuild_outline job; in a full run the arq pool
    client is pinned to a previous event loop (outside the reach of our
    `_reset_module_globals` fixture), so in the full test run this test may
    raise "got Future attached to a different loop". We accept both paths:
    the happy 200, or a skip for exactly that cause.
    """
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.deleted_at = datetime.now(UTC)
    await session.commit()
    await _login(client, user)

    try:
        r = await client.post(f"/api/assets/{asset.id}/undelete")
    except RuntimeError as e:
        if "different loop" in str(e) or "Event loop is closed" in str(e):
            pytest.skip("Arq job pool pinned to a previous event loop; flaky in a full run")
        raise

    assert r.status_code == 200
    await session.refresh(asset)
    assert asset.deleted_at is None


@pytest.mark.asyncio
async def test_undelete_404_for_not_owned(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    asset.deleted_at = datetime.now(UTC)
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.post(f"/api/assets/{asset.id}/undelete")
    assert r.status_code in (403, 404)
    # The asset stays soft-deleted.
    await session.refresh(asset)
    assert asset.deleted_at is not None


@pytest.mark.asyncio
async def test_undelete_noop_when_not_deleted(client, session):
    """Asset that was not deleted: the endpoint returns 200 with `noop: true`,
    not 4xx. Idempotent for UX."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await _login(client, user)

    r = await client.post(f"/api/assets/{asset.id}/undelete")
    assert r.status_code == 200
    body = r.json()
    assert body.get("noop") is True


# ---------- GET /by-slug/{slug}/security ----------


@pytest.mark.asyncio
async def test_security_returns_report_for_html_bundle(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle")
    asset.security_report = {"status": "warn", "findings": []}
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/security")
    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == asset.slug
    assert "security_status" in body
    assert "security_report" in body


@pytest.mark.asyncio
async def test_security_404_for_non_html_bundle(client, session):
    """A security report only makes sense for an HTML bundle. md_single -> 404."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/security")
    assert r.status_code == 404


# ---------- /search-mcp ----------


@pytest.mark.asyncio
async def test_search_mcp_empty_for_unmatched_query(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Doc")
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=nosuchtermanywhere")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_search_mcp_rejects_empty_query(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=")
    assert r.status_code == 422  # Pydantic min_length=1


@pytest.mark.asyncio
async def test_search_mcp_pagination_params_validated(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    # limit > 50 -> 422
    r = await client.get("/api/assets/search-mcp?q=x&limit=100")
    assert r.status_code == 422

    # Negative offsets are invalid.
    r2 = await client.get("/api/assets/search-mcp?q=x&offset=-1")
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_search_mcp_finds_doc_when_only_some_terms_match(client, session):
    """An agent types a few loose words and the document must be found when
    some of the terms match, not only when all of them do.

    The content contains "normalizing", "embeddings", "clustering"; the query
    adds terms with no match ("centering", "finding") and a base form
    ("embedding" vs "embeddings")."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Normalizing embeddings")
    asset.search_content = (
        "Procedure for normalizing embeddings before clustering.\n"
        "Normalization improves cluster separability."
    )
    await session.commit()
    await _login(client, user)

    r = await client.get(
        "/api/assets/search-mcp?q=clustering embedding centering finding&match=any"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == asset.slug
    # The snippet highlights matched terms.
    assert "<em>" in body["items"][0]["snippets"][0]["text"]


@pytest.mark.asyncio
async def test_search_mcp_ranks_more_term_matches_higher(client, session):
    """OR with ranking: a document matching two terms ranks above a document
    matching one."""
    user = await mk_user(session)
    both = await mk_asset(session, user, title="Both")
    both.search_content = "vector database and chunk retrieval"
    one = await mk_asset(session, user, title="One")
    one.search_content = "document retrieval in the pipeline"
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=retrieval vector&match=any")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    slugs = [it["slug"] for it in body["items"]]
    assert slugs[0] == both.slug
    assert body["items"][0]["score"] > body["items"][1]["score"]


@pytest.mark.asyncio
async def test_search_mcp_matches_title_when_content_is_null(client, session):
    """The title is part of the vector, so an html_bundle (search_content
    intentionally NULL) is findable by title."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", title="Sales dashboard")
    await session.commit()
    assert await session.scalar(select(Asset.search_content).where(Asset.id == asset.id)) is None
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=dashboard")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["slug"] == asset.slug


@pytest.mark.asyncio
async def test_search_mcp_query_without_indexable_terms_returns_empty(client, session):
    """Punctuation alone builds no tsquery: empty page instead of 500."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=!!!")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_search_mcp_excludes_other_users_matching_assets(client, session):
    """Visibility guard unchanged: another user's asset does not leak despite a match."""
    me = await mk_user(session)
    other = await mk_user(session)
    theirs = await mk_asset(session, other, title="Secret report")
    theirs.search_content = "confidential clustering of embeddings"
    await session.commit()
    await _login(client, me)

    r = await client.get("/api/assets/search-mcp?q=clustering")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_search_mcp_ignores_single_char_terms(client, session):
    """'simple' has no stopwords, so 1-character words ("a", "I")
    would prefix-match the whole corpus. They are filtered out before building
    the tsquery."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Doc")
    asset.search_content = "clustering embeddings in a pipeline"
    await session.commit()
    await _login(client, user)

    # A 1-character term neither breaks the query nor matches everything.
    r = await client.get("/api/assets/search-mcp?q=a clustering")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # A lone 1-character word -> no indexable terms -> empty page.
    r2 = await client.get("/api/assets/search-mcp?q=a")
    assert r2.status_code == 200
    assert r2.json()["total"] == 0


@pytest.mark.asyncio
async def test_search_mcp_offset_overshoot_keeps_total_consistent(client, session):
    """LIMIT/OFFSET past the end of results loses the window count; total must
    still report the real number of hits, not 0."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, title="Doc")
    asset.search_content = "clustering embeddings"
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search-mcp?q=clustering&offset=10")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 1
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_search_mcp_admin_bypass(client, session):
    """Regression: the admin bypass from `effective_role` also applies to
    search (see the comment at _VISIBLE_SQL). It widens visibility but does not
    override filters (kind narrows) or soft-delete.

    Admin sees the whole per-worker database, so common terms would catch
    committed leftovers from other tests; a unique nonce in the content
    isolates the total assertions (unique-data-per-test extended to content)."""
    nonce = f"nonce{generate_slug(8)}"
    admin = await mk_admin(session)
    other = await mk_user(session)
    theirs = await mk_asset(session, other, title="Someone else's report")
    theirs.search_content = f"confidential {nonce} embeddings"
    gone = await mk_asset(session, other, title="Deleted")
    gone.search_content = f"confidential {nonce} embeddings"
    gone.deleted_at = datetime.now(UTC)
    await session.commit()
    await _login(client, admin)

    r = await client.get(f"/api/assets/search-mcp?q={nonce}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # other user's visible, soft-deleted not
    assert body["items"][0]["slug"] == theirs.slug

    r2 = await client.get(f"/api/assets/search-mcp?q={nonce}&kind=html_bundle")
    assert r2.status_code == 200
    assert r2.json()["total"] == 0


# ---------- /html-json (programatic HTML bundle creation) ----------


# The html-json happy path test is in `test_assets_upload.py` via the
# `fs_storage` fixture; here we only test validation (no storage).


@pytest.mark.asyncio
async def test_html_json_rejects_entry_path_not_in_files(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "missing.html",
            "files": [{"path": "other.html", "content_text": "<html/>"}],
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_html_json_rejects_duplicate_paths(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "index.html",
            "files": [
                {"path": "index.html", "content_text": "<html/>"},
                {"path": "index.html", "content_text": "<html/>"},
            ],
        },
    )
    assert r.status_code == 400
    assert "duplicate" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_html_json_rejects_both_text_and_base64(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "index.html",
            "files": [
                {
                    "path": "index.html",
                    "content_text": "x",
                    "content_base64": "eA==",
                },
            ],
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_html_json_rejects_path_traversal(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "index.html",
            "files": [
                {"path": "../etc/passwd", "content_text": "x"},
                {"path": "index.html", "content_text": "<html/>"},
            ],
        },
    )
    assert r.status_code == 422  # Pydantic field_validator rejects


@pytest.mark.asyncio
async def test_html_json_rejects_invalid_base64(client, session):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "index.html",
            "files": [
                {"path": "index.html", "content_base64": "not!@#$valid_base64!"},
            ],
        },
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_html_json_rejects_bundle_over_per_user_limit(client, session):
    user = await mk_user(session)
    user.bundle_max_bytes = 16
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "X",
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": "<html/>" * 100}],
        },
    )
    assert r.status_code == 413


# ---------- MCP rate limit ----------


@pytest.mark.asyncio
async def test_mcp_rate_limit_returns_429_when_exceeded(client, session):
    """Pre-set the Redis counter to MCP_API.limit. The next call -> 429.

    A full loop of 601 calls would take too long, so we initialize the Redis
    counter at the limit directly and the next INCR exceeds it.
    """
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    redis = get_redis()
    key = f"rl:{ratelimit.MCP_API.name}:{user.id}"
    await redis.set(key, ratelimit.MCP_API.limit, ex=ratelimit.MCP_API.window_seconds)

    r = await client.get("/api/assets/index")
    assert r.status_code == 429
    assert r.json()["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1
