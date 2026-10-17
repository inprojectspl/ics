"""Backend message catalogue and locale resolution (ADR-0011)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import i18n
from app.i18n import SafeHtml, negotiate, plural_category, resolve_locale, t, t_html, tn
from app.models import EmailOutbox
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user

# ---------- catalogue integrity ----------

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def test_catalogues_have_identical_keys_and_no_empty_values():
    en, pl = i18n.CATALOGUES["en"], i18n.CATALOGUES["pl"]
    assert set(en) == set(pl), {"only_en": set(en) - set(pl), "only_pl": set(pl) - set(en)}
    for loc, cat in i18n.CATALOGUES.items():
        empty = [k for k, v in cat.items() if not v.strip()]
        assert not empty, f"{loc}: empty values {empty}"


def test_catalogues_use_the_same_placeholders():
    en, pl = i18n.CATALOGUES["en"], i18n.CATALOGUES["pl"]
    mismatched = [
        k for k in en if set(_PLACEHOLDER.findall(en[k])) != set(_PLACEHOLDER.findall(pl[k]))
    ]
    assert not mismatched


def test_every_scanner_rule_has_a_message():
    from app.bundle_scan._rules import HTML_RULES, JS_RULES, SVG_SCRIPT_RULE

    codes = {r.name for r in HTML_RULES + JS_RULES} | {
        SVG_SCRIPT_RULE,
        "external_script_src",
        "external_script_src_trusted",
    }
    missing = sorted(c for c in codes if f"scan.{c}" not in i18n.CATALOGUES["en"])
    assert not missing


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, None),
        ("", None),
        ("pl-PL,pl;q=0.9,en-US;q=0.8", "pl"),
        ("en-GB,en;q=0.9,pl;q=0.8", "en"),
        ("de-DE,de;q=0.9", None),
        ("de,pl;q=0.5,en;q=0.7", "en"),
        ("pl;q=0,en;q=0.1", "en"),
        ("*", None),
        ("pl;q=bogus,en", "en"),
    ],
)
def test_negotiate_accept_language(header, expected):
    assert negotiate(header) == expected


def test_resolve_prefers_stored_locales_in_order():
    assert resolve_locale(None, "pl", accept_language="en") == "pl"
    assert resolve_locale("en", "pl", accept_language="pl") == "en"
    # An unsupported stored value is skipped, not trusted.
    assert resolve_locale("xx", accept_language="pl-PL") == "pl"
    assert resolve_locale(None, accept_language="de") == "en"


def test_t_interpolates_and_falls_back_to_english(monkeypatch):
    assert t("scan.external_script_src", "pl", host="a.b") == (
        "<script src> z zewnętrznego hosta: a.b."
    )
    monkeypatch.setitem(i18n.CATALOGUES["en"], "only.en", "hello {name}")
    assert t("only.en", "pl", name="x") == "hello x"
    assert t("only.en", "fr", name="x") == "hello x"


def test_t_does_not_evaluate_format_expressions(monkeypatch):
    """Placeholders are plain names: attribute or index access in a
    catalogue value is left as text, never evaluated."""
    monkeypatch.setitem(i18n.CATALOGUES["en"], "evil", "{x.__class__} {x[0]} {x}")
    assert t("evil", "en", x="v") == "{x.__class__} {x[0]} v"


def test_missing_key_and_parameter_do_not_raise():
    assert t("no.such.key", "en") == "no.such.key"
    assert "{host}" in t("scan.external_script_src", "en")


def test_t_html_escapes_text_and_params_but_not_safe_html():
    out = t_html("email.invite.intro", "en", inviter="<b>x</b>")
    assert "&lt;b&gt;x&lt;/b&gt;" in out
    out = t_html("email.invite.intro", "en", inviter=SafeHtml("<strong>x</strong>"))
    assert "<strong>x</strong>" in out


@pytest.mark.parametrize(
    "n,pl,en",
    [
        (1, "one", "one"),
        (2, "few", "many"),
        (5, "many", "many"),
        (12, "many", "many"),
        (22, "few", "many"),
        (0, "many", "many"),
    ],
)
def test_plural_categories(n, pl, en):
    assert plural_category(n, "pl") == pl
    assert plural_category(n, "en") == en


def test_tn_picks_the_plural_form():
    assert tn("chat.files", 3, "pl") == "3 pliki"
    assert tn("chat.files", 5, "pl") == "5 plików"
    assert tn("chat.files", 3, "en") == "3 files"


# ---------- stored user locale ----------


@pytest.mark.asyncio
async def test_me_returns_and_patches_locale(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.get("/api/auth/me")
    assert r.json()["locale"] is None

    r = await client.patch("/api/auth/me", json={"locale": "pl"})
    assert r.status_code == 200
    assert r.json()["locale"] == "pl"
    await session.refresh(user)
    assert user.locale == "pl"

    r = await client.patch("/api/auth/me", json={"locale": None})
    assert r.status_code == 200
    assert r.json()["locale"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"locale": "de"}, {"locale": "PL"}, {}])
async def test_patch_me_rejects_unsupported_locale(client, session, body):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.patch("/api/auth/me", json=body)
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_patch_me_requires_login(client):
    r = await client.patch("/api/auth/me", json={"locale": "en"})
    assert r.status_code == 401


# ---------- locale of queued e-mails ----------


async def _outbox_subject(session, to_email: str) -> str:
    row = (
        await session.execute(select(EmailOutbox).where(EmailOutbox.to_email == to_email))
    ).scalar_one()
    return row.subject


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored,header,expected",
    [
        (None, None, "en"),
        (None, "pl-PL,pl;q=0.9,en;q=0.5", "pl"),
        ("en", "pl", "en"),
        ("pl", None, "pl"),
    ],
)
async def test_password_reset_mail_follows_user_then_request_locale(
    client, session, stored, header, expected
):
    user = await mk_user(session, locale=stored)
    await session.commit()
    headers = {"Accept-Language": header} if header else {}
    r = await client.post(
        "/api/auth/password-reset/request", json={"email": user.email}, headers=headers
    )
    assert r.status_code == 200
    assert await _outbox_subject(session, user.email) == t("email.reset.subject", expected)


@pytest.mark.asyncio
async def test_magic_link_uses_recipient_locale_or_the_sharers(client, session):
    owner = await mk_user(session, locale="pl")
    member = await mk_user(session, locale="en")
    asset = await mk_asset(session, owner)
    await session.commit()
    await login_as(client, owner)
    external = f"guest+{generate_slug(6)}@outside.example"

    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "magic_email", "allowed_emails": [external, member.email]},
        headers={"Accept-Language": "en"},
    )
    assert r.status_code == 201, r.text
    # No account: the sharer's stored locale beats their browser header.
    assert await _outbox_subject(session, external) == t(
        "email.magic.subject", "pl", title=asset.title
    )
    assert await _outbox_subject(session, member.email) == t(
        "email.magic.subject", "en", title=asset.title
    )
