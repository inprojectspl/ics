"""Admin bypass workflow for critical-flagged html_bundle assets.

End-to-end: scanner flips status -> share creation 403 -> admin bypass ->
share creation 201 -> new version flips back -> bypass auto-cleared.

Plus per-user auto-acceptance (`User.html_autobypass`): the same path,
except the uploader's flag makes the decision instead of an admin in the queue.
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
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


async def _mk_critical_asset(session, *, bypass=False, owner=None) -> Asset:
    if owner is None:
        owner = User(email=f"owner+{generate_slug(6)}@example.com", role="user")
        session.add(owner)
        await session.flush()
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        kind="html_bundle",
        title="t",
        storage_prefix="x",
        entry_path="index.html",
        security_status="critical",
        security_report={
            "status": "critical",
            "findings": [
                {
                    "severity": "critical",
                    "rule": "eval_call",
                    "file": "app.js",
                    "line": 1,
                    "message": "eval()",
                }
            ],
        },
        security_bypass=bypass,
        version=1,
    )
    session.add(asset)
    await session.commit()
    return asset


def test_visitor_gate_blocks_critical_without_bypass():
    from app.routes.assets import assert_bundle_renderable_for_visitors

    asset = SimpleNamespace(security_status="critical", security_bypass=False)
    with pytest.raises(HTTPException) as exc:
        assert_bundle_renderable_for_visitors(asset)
    assert exc.value.status_code == 410


def test_visitor_gate_passes_critical_with_bypass():
    from app.routes.assets import assert_bundle_renderable_for_visitors

    asset = SimpleNamespace(security_status="critical", security_bypass=True)
    assert_bundle_renderable_for_visitors(asset)  # no raise


def test_visitor_gate_passes_warn_and_clean():
    from app.routes.assets import assert_bundle_renderable_for_visitors

    for status in ("clean", "warn"):
        asset = SimpleNamespace(security_status=status, security_bypass=False)
        assert_bundle_renderable_for_visitors(asset)


@pytest.mark.asyncio
async def test_grant_bypass_writes_audit_and_columns(session):
    from app.routes.admin import BypassIn, grant_security_bypass

    admin = User(email=f"admin+{generate_slug(6)}@example.com", role="admin")
    session.add(admin)
    await session.flush()
    asset = await _mk_critical_asset(session)

    body = BypassIn(reason="reviewed manually, demo code only")
    out = await grant_security_bypass(asset.id, body, admin, session)

    assert out["security_bypass"] is True
    assert out["security_bypass_by"] == str(admin.id)
    assert out["security_bypass_reason"] == "reviewed manually, demo code only"
    assert out["security_bypass_at"] is not None


@pytest.mark.asyncio
async def test_grant_bypass_rejects_non_critical(session):
    from app.routes.admin import BypassIn, grant_security_bypass

    admin = User(email=f"admin+{generate_slug(6)}@example.com", role="admin")
    session.add(admin)
    await session.flush()
    asset = Asset(
        slug=generate_slug(),
        owner_id=admin.id,
        kind="html_bundle",
        title="t",
        storage_prefix="x",
        entry_path="index.html",
        security_status="warn",  # not critical
        version=1,
    )
    session.add(asset)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await grant_security_bypass(
            asset.id,
            BypassIn(reason="some long enough reason"),
            admin,
            session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_grant_bypass_conflict_if_already_granted(session):
    from app.routes.admin import BypassIn, grant_security_bypass

    admin = User(email=f"admin+{generate_slug(6)}@example.com", role="admin")
    session.add(admin)
    await session.flush()
    asset = await _mk_critical_asset(session, bypass=True)

    with pytest.raises(HTTPException) as exc:
        await grant_security_bypass(
            asset.id,
            BypassIn(reason="trying twice should fail"),
            admin,
            session,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_review_queue_lists_only_pending(session):
    from app.routes.admin import list_review_queue

    admin = User(email=f"admin+{generate_slug(6)}@example.com", role="admin")
    session.add(admin)
    await session.flush()
    pending = await _mk_critical_asset(session)
    bypassed = await _mk_critical_asset(session, bypass=True)

    rows = await list_review_queue(admin, session)
    pending_ids = {row["id"] for row in rows}
    # Other tests in the same file may leave residual critical rows in the
    # DB (no per-test rollback), so check membership rather than exact count.
    assert str(pending.id) in pending_ids
    assert str(bypassed.id) not in pending_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored,header,expected",
    [
        (None, None, "eval() call: runs arbitrary code from a string."),
        (None, "pl", "Wywołanie eval(): wykonuje dowolny kod ze stringa."),
        ("en", "pl", "eval() call: runs arbitrary code from a string."),
    ],
)
async def test_review_queue_renders_findings_in_admin_locale(session, stored, header, expected):
    from app.routes.admin import list_review_queue

    admin = User(email=f"admin+{generate_slug(6)}@example.com", role="admin", locale=stored)
    session.add(admin)
    await session.flush()
    pending = await _mk_critical_asset(session)

    rows = await list_review_queue(admin, session, accept_language=header)
    row = next(r for r in rows if r["id"] == str(pending.id))
    assert row["security_report"]["findings"][0]["message"] == expected


@pytest.mark.asyncio
async def test_apply_scan_clears_bypass(tmp_path):
    from app.bundle_scan import apply_scan_if_html

    # The bundle on disk still contains eval: a bypass granted for an earlier
    # version must be cleared by the fresh scan.
    prefix = tmp_path / "assets" / "x" / "v2"
    prefix.mkdir(parents=True)
    (prefix / "app.js").write_text("eval(x)", encoding="utf-8")
    asset = SimpleNamespace(
        kind="html_bundle",
        storage_prefix="assets/x",
        version=2,
        security_status="critical",
        security_report={"status": "critical", "findings": []},
        security_bypass=True,
        security_bypass_at="2026-01-01T00:00:00+00:00",
        security_bypass_by="00000000-0000-0000-0000-000000000000",
        security_bypass_reason="approved on v1",
    )
    settings = SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        security_policy="strict",
        trusted_cdn_hosts="",
        trusted_cdn_hosts_set=frozenset(),
    )
    summary = await apply_scan_if_html(asset, settings)

    assert summary["status"] == "critical"
    assert asset.security_bypass is False
    assert asset.security_bypass_at is None
    assert asset.security_bypass_by is None
    assert asset.security_bypass_reason is None


async def _mk_bundle_with_eval(session, tmp_path, *, autobypass: bool):
    """An html_bundle asset with a real `eval()` in storage, plus its owner."""
    owner = User(
        email=f"owner+{generate_slug(6)}@example.com",
        role="user",
        html_autobypass=autobypass,
    )
    session.add(owner)
    await session.flush()

    slug = generate_slug()
    version_dir = tmp_path / "assets" / slug / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "app.js").write_text("eval(x)", encoding="utf-8")

    asset = Asset(
        slug=slug,
        owner_id=owner.id,
        kind="html_bundle",
        title="t",
        storage_prefix=f"assets/{slug}",
        entry_path="index.html",
        version=1,
        security_status="clean",
    )
    session.add(asset)
    await session.flush()
    return owner, asset


def _fs_settings(tmp_path):
    from app.config import Settings

    s = Settings()
    s.storage_url = f"fs://{tmp_path}"
    s.security_policy = "strict"
    return s


@pytest.mark.asyncio
async def test_autobypass_grants_on_upload_for_flagged_user(session, tmp_path):
    from app.services import asset_security

    owner, asset = await _mk_bundle_with_eval(session, tmp_path, autobypass=True)

    summary = await asset_security.scan_and_apply(
        asset, _fs_settings(tmp_path), session, actor=owner
    )

    # Status and report stay untouched so the admin can see what the scanner
    # found. Only whether publication is held back changes.
    assert summary["status"] == "critical"
    assert summary["auto_bypass"] is True
    assert asset.security_status == "critical"
    assert asset.security_bypass is True
    assert asset.security_bypass_by == owner.id
    assert asset.security_bypass_reason == asset_security.AUTO_BYPASS_REASON
    assert asset_security.publication_blocked(asset) is False


@pytest.mark.asyncio
async def test_without_flag_critical_still_waits_for_admin(session, tmp_path):
    from app.services import asset_security

    owner, asset = await _mk_bundle_with_eval(session, tmp_path, autobypass=False)

    summary = await asset_security.scan_and_apply(
        asset, _fs_settings(tmp_path), session, actor=owner
    )

    assert summary["status"] == "critical"
    assert "auto_bypass" not in summary
    assert asset.security_bypass is False
    assert asset_security.publication_blocked(asset) is True


@pytest.mark.asyncio
async def test_autobypass_does_not_touch_clean_bundle(session, tmp_path):
    from app.services import asset_security

    owner, asset = await _mk_bundle_with_eval(session, tmp_path, autobypass=True)
    # Replace the content with a clean one: the flag has nothing to accept.
    (tmp_path / "assets" / asset.slug / "v1" / "app.js").write_text(
        "console.log(1)", encoding="utf-8"
    )

    summary = await asset_security.scan_and_apply(
        asset, _fs_settings(tmp_path), session, actor=owner
    )

    assert summary["status"] == "clean"
    assert asset.security_bypass is False
    assert asset.security_bypass_reason is None


@pytest.mark.asyncio
async def test_autobypass_writes_audit_entry(session, tmp_path):
    from sqlalchemy import select

    from app.models import AuditLog
    from app.services import asset_security

    owner, asset = await _mk_bundle_with_eval(session, tmp_path, autobypass=True)
    await asset_security.scan_and_apply(asset, _fs_settings(tmp_path), session, actor=owner)
    await session.flush()

    rows = (
        (await session.execute(select(AuditLog).where(AuditLog.target == f"asset:{asset.id}")))
        .scalars()
        .all()
    )
    granted = [r for r in rows if r.action == "security_bypass_granted"]
    assert len(granted) == 1
    assert granted[0].payload["auto"] is True
