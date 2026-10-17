"""Vault wikilink graph: parser, resolver, dedup, title extraction."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.graph import build_graph
from app.models import Asset, User
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _write(prefix: Path, asset: Asset, version: int, files: dict[str, str]) -> None:
    base = prefix / asset.storage_prefix / f"v{version}"
    base.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


async def _fs_settings(tmp_path: Path):
    s = get_settings()
    return SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        **{k: getattr(s, k) for k in vars(s).keys() if k != "storage_url"},
    )


async def _mk_asset(session) -> Asset:
    owner = User(email=f"o+{generate_slug(6)}@example.com", role="user")
    session.add(owner)
    await session.flush()
    asset = Asset(
        id=uuid4(),
        slug=generate_slug(),
        owner_id=owner.id,
        kind="md_collection",
        title="vault",
        storage_prefix=f"assets/{generate_slug(8)}",
        entry_path="README.md",
        security_status="clean",
        version=1,
        size_bytes=0,
    )
    session.add(asset)
    await session.commit()
    return asset


# ---------- resolver semantics ----------


@pytest.mark.asyncio
async def test_resolves_exact_path(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "See [[Notes/intro.md]].\n",
            "Notes/intro.md": "# Intro\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert ("README.md", "Notes/intro.md") in edges


@pytest.mark.asyncio
async def test_resolves_basename_only(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "See [[Intro]] next.\n",
            "Notes/Intro.md": "# Intro\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert ("README.md", "Notes/Intro.md") in edges


@pytest.mark.asyncio
async def test_alias_stripped_before_resolve(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "[[Intro|introduction]] next.\n",
            "Intro.md": "# Intro\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert ("README.md", "Intro.md") in edges


@pytest.mark.asyncio
async def test_broken_links_dropped(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "Links to [[Missing]] and [[Ghost]].\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    assert g["edges"] == []
    # README itself stays as a lone node; it does not disappear just
    # because nothing links to it.
    assert any(n["path"] == "README.md" for n in g["nodes"])


# ---------- dedup + degrees ----------


@pytest.mark.asyncio
async def test_parallel_edges_deduplicated(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "A.md": "[[B]] and also [[B|B again]] and [[B.md]].\n",
            "B.md": "# B\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    assert g["edges"] == [{"from": "A.md", "to": "B.md"}]
    node_b = next(n for n in g["nodes"] if n["path"] == "B.md")
    assert node_b["in_degree"] == 1
    node_a = next(n for n in g["nodes"] if n["path"] == "A.md")
    assert node_a["out_degree"] == 1


@pytest.mark.asyncio
async def test_self_link_dropped(tmp_path: Path, session):
    """A note linking to itself is a no-op on the graph: the node stays,
    with no self-loop edge."""
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "See [[README]].\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    assert g["edges"] == []


# ---------- title extraction ----------


@pytest.mark.asyncio
async def test_title_uses_first_heading_when_present(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "deep/nested/page.md": "# Big Title\n\nBody\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    node = next(n for n in g["nodes"] if n["path"] == "deep/nested/page.md")
    assert node["title"] == "Big Title"


@pytest.mark.asyncio
async def test_title_falls_back_to_basename(tmp_path: Path, session):
    asset = await _mk_asset(session)
    _write(
        tmp_path,
        asset,
        1,
        {
            "no-heading.md": "Body only, no heading.\n",
        },
    )
    settings = await _fs_settings(tmp_path)
    g = await build_graph(asset, settings)
    node = next(n for n in g["nodes"] if n["path"] == "no-heading.md")
    assert node["title"] == "no-heading"
