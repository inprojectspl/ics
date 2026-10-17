"""Email templates: well-formed HTML, plain-text fallback, basic
HTML-escaping of injected values."""

import pytest

from app import email_templates
from app.i18n import t


def _is_balanced_html(html: str) -> bool:
    """Cheap sanity check: doctype + body + table + closing tags exist."""
    return (
        "<!doctype html>" in html.lower()
        and "<body" in html
        and "</body>" in html
        and "<table" in html
        and "</table>" in html
    )


@pytest.mark.parametrize(
    "purpose,ctx",
    [
        ("invite", {"invited_by_email": "admin@example.com", "setup_url": "https://x/s?t=1"}),
        ("reinvite", {"invited_by_email": "admin@example.com", "setup_url": "https://x/s?t=1"}),
        ("password_reset_user", {"reset_url": "https://x/r?t=1"}),
        (
            "password_reset_admin",
            {
                "reset_url": "https://x/r?t=1",
                "requested_by_admin": True,
                "admin_email": "boss@example.com",
            },
        ),
        (
            "magic_link",
            {
                "owner_email": "anna@example.com",
                "asset_title": "Q3 report",
                "share_url": "https://x/s/abc?m=tok",
            },
        ),
        ("verify_email", {"verify_url": "https://x/v?t=1"}),
        (
            "project_invite",
            {
                "invited_by_email": "anna@example.com",
                "project_name": "Q3",
                "role": "editor",
                "accept_url": "https://x/p/q3/accept?t=1",
                "setup_url": "https://x/setup?token=1",
            },
        ),
    ],
)
@pytest.mark.parametrize("locale", ["en", "pl"])
def test_template_returns_subject_text_html(purpose, ctx, locale):
    fn_name = {
        "invite": "invite",
        "reinvite": "reinvite",
        "password_reset_user": "password_reset",
        "password_reset_admin": "password_reset",
        "magic_link": "magic_link",
        "verify_email": "verify_email",
        "project_invite": "project_invite",
    }[purpose]
    fn = getattr(email_templates, fn_name)
    subject, text, html = fn(**ctx, locale=locale)
    assert isinstance(subject, str) and subject
    assert isinstance(text, str) and len(text) > 20
    assert _is_balanced_html(html)
    # The URL must be present in both parts so clients without HTML
    # (or with a paranoid renderer) can still copy it out.
    url = next(v for k, v in ctx.items() if k.endswith("_url"))
    assert url in text
    assert url in html
    assert f'<html lang="{locale}">' in html
    assert t("email.footer", locale) in html


def test_html_escapes_injected_values():
    """User-controllable fields go through html.escape, otherwise a
    malicious display_name like '<script>alert(1)</script>' would
    execute in someone's Outlook preview pane."""
    _, _, html = email_templates.magic_link(
        owner_email="<script>alert(1)</script>",
        asset_title="<img src=x onerror=alert(1)>",
        share_url="https://x/s/abc",
        locale="en",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # The dangerous form is `<img ... onerror=...` as an actual HTML tag.
    # html.escape converts the `<` to `&lt;` so the tag never opens; the
    # string "onerror=" can survive in text content, harmless.
    assert "<img" not in html  # no raw <img tag in output
    assert "&lt;img" in html


def test_admin_reset_includes_admin_email_in_both_parts():
    _subj, text, html = email_templates.password_reset(
        reset_url="https://x/r?t=1",
        requested_by_admin=True,
        admin_email="boss@example.com",
        locale="en",
    )
    assert "boss@example.com" in text
    assert "boss@example.com" in html


def test_self_reset_does_not_mention_admin():
    _subj, text, html = email_templates.password_reset(reset_url="https://x/r?t=1", locale="en")
    assert "boss" not in text and "boss" not in html


def test_html_includes_color_scheme_meta_for_dark_mode():
    _, _, html = email_templates.invite(
        invited_by_email="a@b.c",
        setup_url="https://x/s?t=1",
        locale="en",
    )
    # Both meta tags are required by Apple Mail / Outlook 365 web for
    # the @media(prefers-color-scheme) inside <style> to apply.
    assert 'name="color-scheme"' in html
    assert "prefers-color-scheme" in html


def test_project_invite_translates_the_role():
    ctx = {
        "invited_by_email": "anna@example.com",
        "project_name": "Q3",
        "role": "viewer",
        "accept_url": "https://x/a",
        "setup_url": None,
    }
    subject_pl, text_pl, _ = email_templates.project_invite(**ctx, locale="pl")
    subject_en, text_en, _ = email_templates.project_invite(**ctx, locale="en")
    assert subject_pl == "ICS: zaproszenie do projektu „Q3”"
    assert subject_en == "ICS: invitation to project “Q3”"
    assert "Twoja rola: czytelnik." in text_pl
    assert "Your role: viewer." in text_en


def test_bold_parameters_are_escaped_inside_translated_sentences():
    _, _, html = email_templates.invite(
        invited_by_email="<i>x</i>@example.com", setup_url="https://x/s", locale="pl"
    )
    assert "<strong>&lt;i&gt;x&lt;/i&gt;@example.com</strong>" in html
    assert "zaprosił cię do ICS" in html
