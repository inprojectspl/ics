"""Real PostgreSQL regressions for the browser and MCP search contract."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.models import (
    Asset,
    AssetPin,
    AssetProjectShare,
    AssetShare,
    Project,
    ProjectMember,
    ShareLink,
)
from app.slug import generate_slug
from app.util import now as utc_now
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user


async def hits(client, path, q, **params):
    response = await client.get(path, params={"q": q, **params})
    assert response.status_code == 200, response.text
    body = response.json()
    return body if isinstance(body, list) else body["items"]


PATHS = ("/api/assets", "/api/assets/search", "/api/assets/search-mcp", "/api/assets/index")


@pytest.mark.parametrize("path", PATHS)
async def test_same_document_fields_and_polish_accents(client, session, path):
    user = await mk_user(session)
    title = await mk_asset(session, user, title="Zażółć gęślą jaźń")
    summary = await mk_asset(session, user, title="Description")
    summary.summary = "Żółć and gęślą"
    tagged = await mk_asset(session, user, title="Labels")
    tagged.tags = ["gesla"]
    body = await mk_asset(session, user, title="Body")
    body.search_content = "Gęślą in the body"
    await session.commit()
    await login_as(client, user)
    assert {r["slug"] for r in await hits(client, path, "GESLA")} == {
        title.slug,
        summary.slug,
        tagged.slug,
        body.slug,
    }
    assert [r["slug"] for r in await hits(client, path, title.slug)] == [title.slug]


async def test_all_words_any_words_phrases_and_relevance(client, session):
    user = await mk_user(session)
    exact = await mk_asset(session, user, title="SDLC AI")
    exact.content_updated_at = utc_now() - timedelta(days=90)
    reversed_title = await mk_asset(session, user, title="AI for SDLC")
    body = await mk_asset(session, user, title="New unrelated title")
    body.search_content = "SDLC AI " * 1000
    one = await mk_asset(session, user, title="SDLC alone")
    split = await mk_asset(session, user, title="Architecture SDLC")
    split.summary = "AI system"
    await session.commit()
    await login_as(client, user)

    orders = []
    for path in PATHS[:3]:
        found = await hits(client, path, "sdlc ai")
        orders.append([r["slug"] for r in found])
        assert orders[-1][0] == exact.slug
        assert set(orders[-1]) == {exact.slug, reversed_title.slug, body.slug, split.slug}
        assert {r["slug"] for r in await hits(client, path, '"sdlc ai"')} == {exact.slug, body.slug}
        assert {r["slug"] for r in await hits(client, path, "sdlc ai", match="any")} == {
            exact.slug,
            reversed_title.slug,
            body.slug,
            one.slug,
            split.slug,
        }
    assert orders[0] == orders[1] == orders[2]


@pytest.mark.parametrize("q", ["  ", "%", "___", "!!!", "w", '""'])
async def test_empty_or_operator_only_input_never_matches_everything(client, session, q):
    user = await mk_user(session)
    await mk_asset(session, user, title="secret relevant document")
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        assert await hits(client, path, q) == []


async def test_query_uses_words_after_the_eighth_and_handles_identifiers(client, session):
    user = await mk_user(session)
    doc = await mk_asset(session, user, title="Project Standard v1.3")
    doc.search_content = "one two three four five six seven eight nine"
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        assert await hits(client, path, "one two three four five six seven eight missing") == []
        assert [r["slug"] for r in await hits(client, path, "project v1.3")] == [doc.slug]
        assert await hits(client, path, "project & !'absent':*") == []


async def test_filtered_search_pages_include_old_shared_documents_and_metadata(client, session):
    viewer, owner = await mk_user(session), await mk_user(session)
    doc_type = await mk_doc_type(session)
    # The sought hit sits behind 210 newer documents, past 50- and 200-row windows.
    for i in range(210):
        await mk_asset(session, viewer, title=f"Needle recent {i}")
    target = await mk_asset(session, owner, title="Needle older", kind="pdf_doc")
    target.summary = "A shared summary"
    target.tags = ["wanted"]
    target.doc_type = doc_type.key
    target.content_updated_at = utc_now() - timedelta(days=100)
    session.add_all(
        [
            AssetShare(asset_id=target.id, user_id=viewer.id, role="viewer"),
            AssetPin(asset_id=target.id, user_id=viewer.id),
        ]
    )
    await session.commit()
    await login_as(client, viewer)
    params = {"q": "needle", "page_size": 25, "f": "type:pdf_doc", "facets": "true"}
    response = await client.get("/api/assets", params=params)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 1
    assert page["scope_counts"]["all"] == 211
    assert page["scope_counts"]["state:shared-with-me"] == 1
    assert page["filter_counts"]["type:md_single"] == 210
    assert page["filter_counts"]["type:pdf_doc"] == 1
    row = page["items"][0]
    assert row["slug"] == target.slug
    assert row["access_source"] == "direct"
    assert row["my_role"] == "viewer"
    assert row["tags"] == ["wanted"]
    assert row["summary"] == target.summary
    assert row["doc_type"] == doc_type.key
    assert row["pinned_at"] is not None
    assert row["owner"]["id"] == str(owner.id)
    for scope, count in (("state:mine", 0), ("state:shared-with-me", 1), ("state:pinned", 1)):
        response = await client.get("/api/assets", params={**params, "scope": scope})
        assert response.json()["total"] == count


async def test_paging_and_total_continue_beyond_500_results(client, session):
    user = await mk_user(session)
    for i in range(507):
        await mk_asset(session, user, title=f"Paginationneedle {i}")
    await session.commit()
    await login_as(client, user)
    seen = []
    for offset in range(0, 550, 50):
        response = await client.get(
            "/api/assets/search-mcp",
            params={
                "q": "paginationneedle",
                "limit": 50,
                "offset": offset,
            },
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["total"] == 507
        assert page["has_more"] == (offset < 500)
        seen.extend(r["slug"] for r in page["items"])
    assert len(seen) == len(set(seen)) == 507
    response = await client.get("/api/assets", params={"q": "paginationneedle", "page": 99})
    assert response.json()["total"] == 507
    assert response.json()["items"] == []


async def test_metadata_and_content_changes_are_searchable_in_the_same_commit(client, session):
    user = await mk_user(session)
    doc = await mk_asset(session, user, title="Initialterm")
    await session.commit()
    await login_as(client, user)
    assert await hits(client, "/api/assets", "initialterm")
    doc.title, doc.summary, doc.tags, doc.search_content = (
        "Newterm",
        "Summaryterm",
        ["tagterm"],
        "Bodyterm",
    )
    await session.commit()
    for path in PATHS:
        assert await hits(client, path, "initialterm") == []
        for q in ("newterm", "summaryterm", "tagterm", "bodyterm"):
            assert [r["slug"] for r in await hits(client, path, q)] == [doc.slug]


async def test_accent_search_uses_the_stored_gin_index(session):
    from app.services.document_search import search_filter

    user = await mk_user(session)
    await mk_asset(session, user, title="Żółta gęś")
    # With one row PostgreSQL correctly prefers the tiny live-assets index.
    # Give the planner realistic selectivity for this regression.
    await session.execute(
        text("""
        INSERT INTO assets (id, owner_id, slug, title, kind, storage_prefix)
        SELECT gen_random_uuid(), :owner, 'index-fixture-' || n,
               'Unrelated document ' || n, 'md_single', 'index-fixture/' || n
        FROM generate_series(1, 2000) AS n
    """),
        {"owner": user.id},
    )
    await session.commit()
    await session.execute(text("SELECT gin_clean_pending_list('ix_assets_search_tsv')"))
    await session.execute(text("ANALYZE assets"))
    statement = select(Asset.id).where(Asset.deleted_at.is_(None), search_filter("zolta"))
    compiled = statement.compile(session.bind.sync_engine, compile_kwargs={"literal_binds": True})
    plan = "\n".join((await session.execute(text(f"EXPLAIN {compiled}"))).scalars())
    assert "ix_assets_search_tsv" in plan


async def test_phrases_stay_in_one_field_and_survive_long_or_repetitive_text(client, session):
    user = await mk_user(session)
    split = await mk_asset(session, user, title="Split fields")
    split.summary, split.tags, split.search_content = "alpha", ["beta"], "gamma"
    long_doc = await mk_asset(session, user, title="Long document")
    long_doc.search_content = "filler " * 17000 + "alpha beta"
    repeated = await mk_asset(session, user, title="Repeated word")
    repeated.search_content = "alpha " * 300 + "beta"
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        found = {r["slug"] for r in await hits(client, path, '"alpha beta"')}
        assert found == {long_doc.slug, repeated.slug}
        assert await hits(client, path, '"beta gamma"') == []
    # Broad mode must still respect each quoted phrase.
    assert {
        r["slug"]
        for r in await hits(client, "/api/assets/search-mcp", '"alpha beta" missing', match="any")
    } == {long_doc.slug, repeated.slug}


async def test_single_digit_is_exact_in_all_discovery_paths(client, session):
    user = await mk_user(session)
    exact = await mk_asset(session, user, title="Report 1")
    await mk_asset(session, user, title="Report 19")
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        assert [row["slug"] for row in await hits(client, path, "1")] == [exact.slug]


async def test_quoted_identifiers_cannot_match_a_prefix_or_suffix(client, session):
    user = await mk_user(session)
    version = await mk_asset(session, user, title="alpha v1.3.1")
    version.summary = "v1.3"
    suffix = await mk_asset(session, user, title="prefix.alpha beta")
    suffix.summary = "alpha"
    exact = await mk_asset(session, user, title="alpha v1.3")
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        assert [row["slug"] for row in await hits(client, path, '"alpha v1.3"')] == [exact.slug]
        assert await hits(client, path, '"alpha beta"') == []


async def test_compound_identifiers_survive_position_limits_without_crossing_fields(
    client, session
):
    user = await mk_user(session)
    long_doc = await mk_asset(session, user, title="Late identifier")
    long_doc.search_content = "filler " * 17000 + "project-standard 2026-10-15"
    split = await mk_asset(session, user, title="2026")
    split.summary = "-10 -15"
    await session.commit()
    await login_as(client, user)
    for path in PATHS:
        for query in ("project-sta", '"project-standard"', "2026-10-15", '"2026-10-15"'):
            assert [row["slug"] for row in await hits(client, path, query)] == [long_doc.slug]


async def test_filter_groups_facets_and_project_assignments(client, session):
    user = await mk_user(session)
    doc_type = await mk_doc_type(session)
    project = Project(slug=generate_slug(), name="Visible project")
    hidden = Project(slug=generate_slug(), name="Hidden project")
    session.add_all([project, hidden])
    await session.flush()
    session.add(
        ProjectMember(project_id=project.id, user_id=user.id, role="viewer", accepted_at=utc_now())
    )
    docs = []
    for tag in ("wanted", "alternate", "unused"):
        doc = await mk_asset(session, user, title="Filterneedle")
        doc.tags, doc.doc_type = [tag], doc_type.key
        doc.review_due_at = utc_now() - timedelta(days=1)
        session.add(ShareLink(asset_id=doc.id, token=generate_slug(), mode="public"))
        session.add(AssetProjectShare(asset_id=doc.id, project_id=project.id, role="viewer"))
        docs.append(doc)
    session.add(AssetProjectShare(asset_id=docs[0].id, project_id=hidden.id, role="viewer"))
    await session.commit()
    await login_as(client, user)
    response = await client.get(
        "/api/assets",
        params={
            "q": "filterneedle",
            "facets": "true",
            "f": [
                f"project:{project.id}",
                "tag:wanted",
                "tag:alternate",
                f"doctype:{doc_type.key}",
                "type:md_single",
                "fresh:review_overdue",
                "state:public",
                "source:manual",
            ],
        },
    )
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["total"] == 2
    assert {row["slug"] for row in page["items"]} == {docs[0].slug, docs[1].slug}
    assert page["filter_counts"]["tag:unused"] == 1
    assert page["filter_counts"][f"project:{project.id}"] == 2
    assert f"project:{hidden.id}" not in page["filter_counts"]


@pytest.mark.parametrize(
    "value", ["missing-group", "unknown:value", "project:invalid", "fresh:invalid"]
)
async def test_invalid_filters_return_a_domain_error(client, session, value):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    response = await client.get("/api/assets", params={"f": value})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
