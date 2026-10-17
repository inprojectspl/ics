"""Link hierarchy: canonical address per asset + `/v/<slug>` resolver.

The rules in `services.link_resolution` are pure, so most of this file
needs no DB: it builds detached `ShareLink` rows and asserts ordering.
The HTTP half covers what only shows up over the wire: anonymous access
to the resolver, and the "no way in" answer being a plain 404.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ShareLink, User
from app.services import link_resolution as lr
from app.slug import generate_token
from tests.conftest import login_as, mk_asset, mk_user

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def share(mode: str, *, age_days: int = 0, **kw) -> ShareLink:
    """Detached ShareLink. `age_days` orders creation: higher = older, so
    tie-breaking on `created_at` is visible in the assertions."""
    kw.setdefault("view_count", 0)
    return ShareLink(
        asset_id=None,
        token=generate_token(),
        mode=mode,
        created_at=BASE - timedelta(days=age_days),
        **kw,
    )


def user(email: str) -> User:
    return User(email=email, display_name="u", role="user")


# ---------- is_usable ----------


def test_usable_link_is_usable():
    assert lr.is_usable(share("public"))


@pytest.mark.parametrize(
    "kw",
    [
        {"revoked_at": BASE},
        {"expires_at": BASE - timedelta(days=1)},
        {"max_views": 3, "view_count": 3},
    ],
    ids=["revoked", "expired", "budget-spent"],
)
def test_dead_links_are_not_usable(kw):
    assert not lr.is_usable(share("public", **kw), at=BASE)


# ---------- pick_canonical ----------


def test_canonical_prefers_org_sso_over_public():
    sso, public = share("org_sso"), share("public")
    assert lr.pick_canonical([public, sso]) is sso


def test_canonical_ignores_secret_bearing_modes():
    """A password or magic-email link cannot stand in as "the address of
    this document": the URL alone does not open it."""
    assert lr.pick_canonical([share("password"), share("magic_email")]) is None


def test_canonical_ignores_budgeted_link():
    """Otherwise the owner opening their own doc from the panel would
    spend the budget meant for the guest it was issued to."""
    assert lr.pick_canonical([share("public", max_views=1)]) is None


def test_canonical_ignores_dead_links():
    assert lr.pick_canonical([share("public", revoked_at=BASE)]) is None


def test_canonical_prefers_link_without_expiry():
    forever, expiring = share("public"), share("public", expires_at=BASE + timedelta(days=30))
    assert lr.pick_canonical([expiring, forever]) is forever


def test_canonical_breaks_tie_on_oldest():
    """Stable address: a freshly minted second link must not silently
    move the URL people already circulated."""
    older, newer = share("public", age_days=10), share("public", age_days=1)
    assert lr.pick_canonical([newer, older]) is older


# ---------- resolve_entry ----------


def test_role_holder_views_in_place():
    decision = lr.resolve_entry(
        role="viewer", user=user("a@example.com"), shares=[], allowed_domains=["example.com"]
    )
    assert decision == lr.EntryDecision("view")


def test_org_user_gets_sso_link_ahead_of_public():
    sso, public = share("org_sso"), share("public")
    decision = lr.resolve_entry(
        role=None,
        user=user("a@example.com"),
        shares=[public, sso],
        allowed_domains=["example.com"],
    )
    assert decision == lr.EntryDecision("redirect", sso.token)


def test_outside_user_falls_through_to_public():
    sso, public = share("org_sso"), share("public")
    decision = lr.resolve_entry(
        role=None,
        user=user("a@other.example"),
        shares=[sso, public],
        allowed_domains=["example.com"],
    )
    assert decision == lr.EntryDecision("redirect", public.token)


def test_anonymous_gets_public_link():
    public = share("public")
    decision = lr.resolve_entry(
        role=None, user=None, shares=[public], allowed_domains=["example.com"]
    )
    assert decision == lr.EntryDecision("redirect", public.token)


def test_password_link_is_offered_with_its_challenge():
    pwd = share("password")
    decision = lr.resolve_entry(role=None, user=None, shares=[pwd], allowed_domains=["example.com"])
    assert decision == lr.EntryDecision("redirect", pwd.token)


def test_public_wins_over_password():
    pwd, public = share("password"), share("public")
    decision = lr.resolve_entry(
        role=None, user=None, shares=[pwd, public], allowed_domains=["example.com"]
    )
    assert decision == lr.EntryDecision("redirect", public.token)


def test_magic_link_only_for_a_listed_recipient():
    magic = share("magic_email", allowed_emails=["invited@other.example"])
    listed = lr.resolve_entry(
        role=None,
        user=user("INVITED@other.example"),
        shares=[magic],
        allowed_domains=["example.com"],
    )
    stranger = lr.resolve_entry(
        role=None,
        user=user("nobody@other.example"),
        shares=[magic],
        allowed_domains=["example.com"],
    )
    assert listed == lr.EntryDecision("redirect", magic.token)
    assert stranger is None


def test_anonymous_with_only_org_link_is_sent_to_login():
    """Logging in may produce a role or a matching domain, so the
    resolver asks for identity before giving up."""
    decision = lr.resolve_entry(
        role=None, user=None, shares=[share("org_sso")], allowed_domains=["example.com"]
    )
    assert decision == lr.EntryDecision("login")


def test_no_channel_is_no_decision():
    assert (
        lr.resolve_entry(role=None, user=None, shares=[], allowed_domains=["example.com"]) is None
    )


def test_budgeted_link_is_never_advertised():
    """`max_views` is a one-time pass issued to a specific person.
    Pointing someone who only knows the slug at it would burn that person's budget."""
    assert (
        lr.resolve_entry(
            role=None,
            user=None,
            shares=[share("public", max_views=1)],
            allowed_domains=["example.com"],
        )
        is None
    )


def test_magic_link_is_matched_per_link_not_per_mode():
    """Two magic-email links on one asset target different recipients.
    Checking only the oldest would turn away the holder of the newer one."""
    alice = share("magic_email", age_days=10, allowed_emails=["alice@other.example"])
    bob = share("magic_email", age_days=1, allowed_emails=["bob@other.example"])
    decision = lr.resolve_entry(
        role=None,
        user=user("bob@other.example"),
        shares=[alice, bob],
        allowed_domains=["example.com"],
    )
    assert decision == lr.EntryDecision("redirect", bob.token)


def test_dead_links_do_not_produce_a_decision():
    """A revoked link must not be advertised: the redirect would land on
    a 410 instead of the content."""
    assert (
        lr.resolve_entry(
            role=None,
            user=None,
            shares=[share("public", revoked_at=BASE)],
            allowed_domains=["example.com"],
        )
        is None
    )


# ---------- HTTP: GET /api/assets/by-slug/{slug}/entry ----------


async def _mk_share(session, asset, mode: str, **kw) -> ShareLink:
    row = ShareLink(asset_id=asset.id, token=generate_token(), mode=mode, **kw)
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_entry_tells_role_holder_to_view(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    assert r.status_code == 200
    assert r.json()["action"] == "view"


@pytest.mark.asyncio
async def test_entry_redirects_anonymous_to_public_link(client, session):
    """The whole point: a pasted `/v/<slug>` opens for someone who never
    logged in, instead of a dead end asking for an /s/ link."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    link = await _mk_share(session, asset, "public")

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "redirect"
    assert body["url"].endswith(f"/s/{link.token}")


@pytest.mark.asyncio
async def test_entry_sends_anonymous_to_login_for_org_link(client, session):
    """The response carries the slug, not an SPA route: login routing
    belongs to the frontend and the backend must not know it."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await _mk_share(session, asset, "org_sso")

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    assert r.status_code == 200
    assert r.json() == {"action": "login", "slug": asset.slug}


@pytest.mark.asyncio
async def test_entry_hides_assets_without_any_channel(client, session):
    """404, identical to an unknown slug: the resolver must not turn a
    guessed slug into a confirmation that the document exists."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await session.commit()

    known = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    unknown = await client.get("/api/assets/by-slug/nosuchslug99/entry")
    assert known.status_code == 404
    assert unknown.status_code == 404
    assert known.json() == unknown.json()


@pytest.mark.asyncio
async def test_entry_ignores_deleted_asset(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await _mk_share(session, asset, "public")
    asset.deleted_at = datetime.now(UTC)
    await session.commit()

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_entry_prefers_org_link_for_a_colleague_without_a_role(client, session):
    """Someone from the organization but without a role on the asset gets the
    SSO link, even though the public one would also let them in: SSO
    identifies the visitor."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await _mk_share(session, asset, "public")
    sso = await _mk_share(session, asset, "org_sso")
    colleague = await mk_user(session)
    await session.commit()
    await login_as(client, colleague)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/entry")
    assert r.json()["url"].endswith(f"/s/{sso.token}")


# ---------- canonical_url in the doc payload ----------


@pytest.mark.asyncio
async def test_doc_payload_carries_share_url_when_one_exists(client, session, fs_storage):
    from tests.conftest import put_blob

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# hi")
    link = await _mk_share(session, asset, "public")
    await login_as(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    assert r.json()["canonical_url"].endswith(f"/s/{link.token}")


@pytest.mark.asyncio
async def test_doc_payload_hides_share_url_from_a_reader(client, session, fs_storage):
    """The token grants anonymous read access, and listing links is reserved
    for the asset owner and the project owner. So neither an editor nor an
    observer may get it in the payload: they would hand out access they are
    not allowed to grant."""
    from app.models import AssetShare
    from tests.conftest import put_blob

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# hi")
    await _mk_share(session, asset, "public")
    reader = await mk_user(session)
    session.add(AssetShare(asset_id=asset.id, user_id=reader.id, role="editor"))
    await session.commit()
    await login_as(client, reader)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    assert r.json()["canonical_url"].endswith(f"/v/{asset.slug}")


@pytest.mark.asyncio
async def test_doc_payload_falls_back_to_slug_url(client, session, fs_storage):
    from tests.conftest import put_blob

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# hi")
    await session.commit()
    await login_as(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.json()["canonical_url"].endswith(f"/v/{asset.slug}")


@pytest.mark.asyncio
async def test_notifications_advertise_the_same_link_as_the_ui(client, session):
    """The notification dispatcher and the address bar must pick the same
    canonical link for an asset."""
    from app.config import get_settings
    from app.services.notifications._link_resolver import resolve_asset_share_link

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await _mk_share(session, asset, "public")
    sso = await _mk_share(session, asset, "org_sso")
    settings = get_settings()

    link = await resolve_asset_share_link(session, asset.id, settings)
    canonical = await lr.canonical_url(session, settings, asset)
    assert link is not None
    assert link.url == canonical
    assert canonical.endswith(f"/s/{sso.token}")


@pytest.mark.asyncio
async def test_notifications_skip_a_budgeted_link(client, session):
    """A one-time pass is not the document's address: a notification with
    such a link would burn the budget on the first person to click."""
    from app.config import get_settings
    from app.services.notifications._link_resolver import resolve_asset_share_link

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await _mk_share(session, asset, "public", max_views=1)

    assert await resolve_asset_share_link(session, asset.id, get_settings()) is None


# ---------- role bypass on the /s/ side ----------


@pytest.mark.asyncio
async def test_password_link_does_not_challenge_its_own_owner(client, session):
    """A colleague forwards the owner their own password link; asking the
    owner for the password would be theatre."""
    from app.passwords import hash_password

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    link = await _mk_share(session, asset, "password", password_hash=hash_password("s3cret!"))
    await login_as(client, owner)

    r = await client.get(f"/api/share/{link.token}/info")
    assert r.status_code == 200
    body = r.json()
    assert body["requires_password"] is False
    assert body["has_access"] is True
    assert body["my_role"] == "owner_file"
    assert body["slug"] == asset.slug


@pytest.mark.asyncio
async def test_share_info_still_challenges_a_stranger(client, session):
    from app.passwords import hash_password

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    link = await _mk_share(session, asset, "password", password_hash=hash_password("s3cret!"))
    stranger = await mk_user(session)
    await session.commit()
    await login_as(client, stranger)

    r = await client.get(f"/api/share/{link.token}/info")
    assert r.json()["requires_password"] is True
    assert r.json()["my_role"] is None
    assert r.json()["slug"] is None


@pytest.mark.asyncio
async def test_logged_in_recipient_of_a_magic_link_is_not_sent_to_their_inbox(client, session):
    """The account proves mailbox ownership, so `mode_admits` lets a logged-in
    recipient in without clicking the email. The challenge in the response
    must match that access, otherwise the UI shows an "open the email" wall
    to someone the backend has already let in."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    invitee = await mk_user(session)
    link = await _mk_share(session, asset, "magic_email", allowed_emails=[invitee.email])
    await login_as(client, invitee)

    body = (await client.get(f"/api/share/{link.token}/info")).json()
    assert body["has_access"] is True
    assert body["requires_magic_link"] is False


@pytest.mark.asyncio
async def test_anonymous_visitor_of_a_magic_link_still_gets_the_challenge(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    link = await _mk_share(session, asset, "magic_email", allowed_emails=["someone@example.com"])
    await session.commit()

    body = (await client.get(f"/api/share/{link.token}/info")).json()
    assert body["has_access"] is False
    assert body["requires_magic_link"] is True


@pytest.mark.asyncio
async def test_org_link_opened_from_outside_the_domain_is_a_dead_end_not_a_login_prompt(
    client, session
):
    """Logged in from outside the allowed domain: logging in changes nothing,
    so the response must not ask for it. Based on that, the frontend shows a
    message instead of an endless "Loading"."""
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    outsider = await mk_user(session, email="someone@outside.example")
    link = await _mk_share(session, asset, "org_sso")
    await login_as(client, outsider)

    body = (await client.get(f"/api/share/{link.token}/info")).json()
    assert body["has_access"] is False
    assert body["requires_login"] is False
    assert body["my_role"] is None


@pytest.mark.asyncio
async def test_team_read_does_not_spend_the_view_budget(client, session, fs_storage):
    """`max_views` caps the strangers a link let in. The owner opening it
    is not one of them."""
    from tests.conftest import put_blob

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# hi")
    link = await _mk_share(session, asset, "public", max_views=5)
    await login_as(client, owner)

    assert (await client.get(f"/api/share/{link.token}/doc")).status_code == 200
    await session.refresh(link)
    assert link.view_count == 0


@pytest.mark.asyncio
async def test_guest_read_still_spends_the_view_budget(client, session, fs_storage):
    from tests.conftest import put_blob

    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    await put_blob(asset, "doc.md", b"# hi")
    link = await _mk_share(session, asset, "public", max_views=5)
    await session.commit()

    assert (await client.get(f"/api/share/{link.token}/doc")).status_code == 200
    await session.refresh(link)
    assert link.view_count == 1
