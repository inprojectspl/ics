"""HTML + plain text templates for outbound mail; each returns `(subject, text, html)`.

Table layout, inline CSS and no remote images because mail clients strip the rest;
dark mode via `e-*` classes is best effort. Wording is in the `app/i18n` catalogue.
"""

from __future__ import annotations

import html as html_lib

from app.i18n import Locale, has_key, strong, t, t_html

# Palette of the app (frontend/src/styles/theme.css), light and dark. Mail
# clients drop CSS variables, so the values are repeated here.
_BG = "#f5f7fa"
_CARD = "#ffffff"
_SUBTLE = "#f0f3f7"
_RULE = "#dce3ec"
_INK = "#182332"
_INK_SOFT = "#4b5b70"
_INK_MUTE = "#64748b"
_ACCENT = "#1769d2"
_ACCENT_SOFT = "#e8f2ff"
_SUCCESS = "#147d59"
_SUCCESS_SOFT = "#e6f4ee"
_DANGER = "#b42332"
_DANGER_SOFT = "#fcebed"
_BRAND = "#ff5500"

# Dark values; the `e-*` classes below swap them in clients that honour
# `prefers-color-scheme` (Apple Mail, iOS, some Outlook builds).
_DARK = {
    "bg": "#101419",
    "card": "#181f28",
    "subtle": "#202a36",
    "rule": "#323f51",
    "ink": "#f4f7fb",
    "soft": "#b7c3d2",
    "mute": "#a8b5c4",
    "accent": "#8abbff",
    "on_accent": "#071929",
    "accent_soft": "#193451",
    "success": "#5ad6a0",
    "success_soft": "#173a2e",
    "danger": "#ff8b93",
    "danger_soft": "#45222a",
}

# The app's UI stack; mail has no web fonts worth the weight.
_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
_FONT_MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

_DARK_CSS = f"""
  @media (prefers-color-scheme: dark) {{
    body, .e-bg {{ background:{_DARK["bg"]} !important; }}
    .e-card {{ background:{_DARK["card"]} !important; border-color:{_DARK["rule"]} !important; }}
    .e-subtle {{ background:{_DARK["subtle"]} !important; }}
    .e-rule {{ border-color:{_DARK["rule"]} !important; }}
    .e-ink {{ color:{_DARK["ink"]} !important; }}
    .e-soft {{ color:{_DARK["soft"]} !important; }}
    .e-mute {{ color:{_DARK["mute"]} !important; }}
    .e-cta {{ background:{_DARK["accent"]} !important; color:{_DARK["on_accent"]} !important; }}
    .e-cta-danger {{ background:{_DARK["danger"]} !important; color:{_DARK["bg"]} !important; }}
    .e-btn {{ background:{_DARK["card"]} !important; border-color:{_DARK["rule"]} !important; color:{_DARK["ink"]} !important; }}
    .e-accent {{ color:{_DARK["accent"]} !important; }}
    .e-tone-accent {{ background:{_DARK["accent_soft"]} !important; color:{_DARK["accent"]} !important; }}
    .e-tone-success {{ background:{_DARK["success_soft"]} !important; color:{_DARK["success"]} !important; }}
    .e-tone-danger {{ background:{_DARK["danger_soft"]} !important; color:{_DARK["danger"]} !important; }}
    .e-text-accent {{ color:{_DARK["accent"]} !important; }}
    .e-text-success {{ color:{_DARK["success"]} !important; }}
    .e-text-danger {{ color:{_DARK["danger"]} !important; }}
  }}"""


def _shell(*, title: str, preheader: str, content: str, locale: Locale) -> str:
    """Wrap a content block in the ICS e-mail frame: the orange ICS mark,
    one white card on the app's canvas, the footer with the policy line."""
    safe_title = html_lib.escape(title)
    safe_preheader = html_lib.escape(preheader)
    footer = t_html("email.footer", locale)
    return f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{safe_title}</title>
<style>{_DARK_CSS}
  a.e-cta:hover {{ opacity:0.92; }}
</style>
</head>
<body class="e-bg" style="margin:0;padding:0;background:{_BG};color:{_INK};font-family:{_FONT};font-size:15px;line-height:1.6;">
  <!-- preheader: shows up as preview text in inbox lists; hidden from body -->
  <div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:{_BG};">{safe_preheader}</div>

  <table role="presentation" class="e-bg" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_BG};">
    <tr><td align="center" style="padding:32px 16px 40px;">

      <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;width:100%;">

        <!-- Header: the orange mark is identity only, as in the app -->
        <tr><td style="padding:0 4px 16px;font-family:{_FONT};">
          <span style="font-size:18px;font-weight:700;letter-spacing:0.04em;color:{_BRAND};">ICS</span>
          <span class="e-mute" style="padding-left:8px;font-size:13px;color:{_INK_MUTE};">Internal Content Sharing</span>
        </td></tr>

        <!-- Card -->
        <tr><td class="e-card" style="background:{_CARD};border:1px solid {_RULE};border-radius:14px;padding:32px 28px;">
          {content}
        </td></tr>

        <!-- Footer -->
        <tr><td class="e-mute" style="padding:16px 4px 0;font-family:{_FONT};font-size:12px;color:{_INK_MUTE};line-height:1.6;">
          {footer}
        </td></tr>

      </table>

    </td></tr>
  </table>
</body>
</html>"""


def _h1(text: str) -> str:
    return (
        f'<h1 class="e-ink" style="margin:0 0 12px;font-family:{_FONT};'
        f"font-size:22px;font-weight:600;letter-spacing:-0.01em;color:{_INK};"
        f'line-height:1.3;">{html_lib.escape(text)}</h1>'
    )


def _p(html_inner: str, *, mute: bool = False) -> str:
    cls, color = ("e-soft", _INK_SOFT) if mute else ("e-ink", _INK)
    return (
        f'<p class="{cls}" style="margin:0 0 16px;font-family:{_FONT};'
        f'font-size:15px;line-height:1.6;color:{color};">{html_inner}</p>'
    )


def _cta(href: str, label: str, *, danger: bool = False) -> str:
    bg, cls = (_DANGER, "e-cta-danger") if danger else (_ACCENT, "e-cta")
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:8px 0 20px;"><tr><td>'
        f'<a class="{cls}" href="{html_lib.escape(href)}" '
        f'style="display:inline-block;padding:11px 20px;border-radius:10px;'
        f"background:{bg};color:#ffffff;text-decoration:none;"
        f'font-family:{_FONT};font-size:15px;font-weight:600;">'
        f"{html_lib.escape(label)}</a></td></tr></table>"
    )


def _fallback_link(href: str, locale: Locale) -> str:
    """Small link below the button, for clients that strip buttons and for
    readers who want to see where it goes."""
    escaped = html_lib.escape(href)
    return (
        f'<p class="e-mute" style="margin:0 0 4px;font-family:{_FONT};font-size:12px;'
        f'color:{_INK_MUTE};">{t_html("email.fallback_link", locale)}</p>'
        f'<p style="margin:0 0 8px;font-family:{_FONT_MONO};font-size:12px;'
        f'word-break:break-all;"><a class="e-accent" href="{escaped}" '
        f'style="color:{_ACCENT};text-decoration:none;">{escaped}</a></p>'
    )


def _ttl(text: str) -> str:
    return (
        f'<p class="e-rule e-mute" style="margin:24px 0 0;padding-top:14px;'
        f"border-top:1px solid {_RULE};font-family:{_FONT};font-size:13px;"
        f'color:{_INK_MUTE};">{html_lib.escape(text)}</p>'
    )


def _signature(locale: Locale) -> str:
    return f"--\n{t('email.signature', locale)}"


# Per-purpose templates


def invite(
    *,
    invited_by_email: str,
    setup_url: str,
    locale: Locale,
) -> tuple[str, str, str]:
    subject = t("email.invite.subject", locale)
    text = (
        f"{t('email.greeting', locale)}\n\n"
        f"{t('email.invite.intro', locale, inviter=invited_by_email)}\n\n"
        f"{t('email.invite.text_cta', locale)}\n{setup_url}\n\n"
        f"{t('email.expires.text_7d', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(subject)
        + _p(t_html("email.invite.intro", locale, inviter=strong(invited_by_email)))
        + _p(t_html("email.invite.cta_hint", locale), mute=True)
        + _cta(setup_url, t("email.cta.set_password", locale))
        + _fallback_link(setup_url, locale)
        + _ttl(t("email.expires.badge_7d", locale))
    )
    html = _shell(
        title=subject,
        preheader=t("email.invite.preheader", locale, inviter=invited_by_email),
        content=body,
        locale=locale,
    )
    return subject, text, html


def password_reset(
    *,
    reset_url: str,
    locale: Locale,
    requested_by_admin: bool = False,
    admin_email: str | None = None,
) -> tuple[str, str, str]:
    subject = t("email.reset.subject", locale)
    if requested_by_admin and admin_email:
        by_line_text = t("email.reset.by_admin", locale, admin=admin_email)
        by_line_html = _p(t_html("email.reset.by_admin", locale, admin=strong(admin_email)))
    else:
        by_line_text = t("email.reset.by_user", locale)
        by_line_html = _p(t_html("email.reset.by_user", locale))

    text = (
        f"{by_line_text}\n\n"
        f"{t('email.reset.text_cta', locale)}\n{reset_url}\n\n"
        f"{t('email.reset.text_ignore', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.reset.heading", locale))
        + by_line_html
        + _cta(reset_url, t("email.reset.cta", locale))
        + _fallback_link(reset_url, locale)
        + _p(t_html("email.reset.ignore", locale), mute=True)
        + _ttl(t("email.expires.badge_1h", locale))
    )
    html = _shell(
        title=subject,
        preheader=t("email.reset.preheader", locale),
        content=body,
        locale=locale,
    )
    return subject, text, html


def magic_link(
    *,
    owner_email: str,
    asset_title: str,
    share_url: str,
    locale: Locale,
) -> tuple[str, str, str]:
    subject = t("email.magic.subject", locale, title=asset_title)
    text = (
        f"{t('email.magic.intro_text', locale, owner=owner_email)}\n\n"
        f"  {asset_title}\n\n"
        f"{t('email.magic.text_open', locale)}\n{share_url}\n\n"
        f"{t('email.magic.text_note', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.magic.heading", locale, title=asset_title))
        + _p(t_html("email.magic.intro", locale, owner=strong(owner_email)))
        + _cta(share_url, t("email.magic.cta", locale))
        + _fallback_link(share_url, locale)
        + _p(t_html("email.magic.note", locale), mute=True)
        + _ttl(t("email.expires.badge_24h", locale))
    )
    html = _shell(
        title=subject,
        preheader=t("email.magic.preheader", locale, owner=owner_email, title=asset_title),
        content=body,
        locale=locale,
    )
    return subject, text, html


def verify_email(
    *,
    verify_url: str,
    locale: Locale,
) -> tuple[str, str, str]:
    subject = t("email.verify.subject", locale)
    text = (
        f"{t('email.verify.thanks_text', locale)}\n\n"
        f"{t('email.verify.text_cta', locale)}\n{verify_url}\n\n"
        f"{t('email.expires.text_24h', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.verify.heading", locale))
        + _p(t_html("email.verify.intro", locale))
        + _cta(verify_url, t("email.verify.cta", locale))
        + _fallback_link(verify_url, locale)
        + _ttl(t("email.expires.badge_24h", locale))
    )
    html = _shell(
        title=subject,
        preheader=t("email.verify.preheader", locale),
        content=body,
        locale=locale,
    )
    return subject, text, html


def project_invite(
    *,
    invited_by_email: str,
    project_name: str,
    role: str,
    accept_url: str,
    setup_url: str | None,
    locale: Locale,
) -> tuple[str, str, str]:
    """`setup_url` is set for an invitee without an account: they cannot sign
    in to accept until they set a password through it."""
    role_label = t(f"role.{role}", locale) if has_key(f"role.{role}") else role
    subject = t("email.project.subject", locale, project=project_name)
    setup_text = (
        f"{t('email.project.setup_hint_text', locale)}\n{setup_url}\n\n" if setup_url else ""
    )
    setup_html = (
        _p(t_html("email.project.setup_hint", locale), mute=True)
        + _cta(setup_url, t("email.cta.set_password", locale))
        + _fallback_link(setup_url, locale)
        if setup_url
        else ""
    )
    text = (
        f"{t('email.project.intro_text', locale, inviter=invited_by_email)}\n\n"
        f"  {project_name}\n\n"
        f"{t('email.project.role_text', locale, role=role_label)}\n\n"
        f"{setup_text}"
        f"{t('email.project.text_cta', locale)}\n{accept_url}\n\n"
        f"{t('email.expires.text_7d', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.project.heading", locale, project=project_name))
        + _p(
            t_html(
                "email.project.intro",
                locale,
                inviter=strong(invited_by_email),
                role=strong(role_label),
            )
        )
        + setup_html
        + _cta(accept_url, t("email.project.cta", locale))
        + _fallback_link(accept_url, locale)
        + _ttl(t("email.expires.badge_7d", locale))
    )
    html = _shell(
        title=subject,
        preheader=t(
            "email.project.preheader",
            locale,
            inviter=invited_by_email,
            project=project_name,
            role=role_label,
        ),
        content=body,
        locale=locale,
    )
    return subject, text, html


def reinvite(
    *,
    invited_by_email: str,
    setup_url: str,
    locale: Locale,
) -> tuple[str, str, str]:
    subject = t("email.reinvite.subject", locale)
    text = (
        f"{t('email.reinvite.intro', locale, inviter=invited_by_email)}\n\n"
        f"{t('email.invite.text_cta', locale)}\n{setup_url}\n\n"
        f"{t('email.expires.text_7d', locale)}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.reinvite.heading", locale))
        + _p(t_html("email.reinvite.intro", locale, inviter=strong(invited_by_email)))
        + _cta(setup_url, t("email.cta.set_password", locale))
        + _fallback_link(setup_url, locale)
        + _ttl(t("email.expires.badge_7d", locale))
    )
    html = _shell(
        title=subject,
        preheader=t("email.reinvite.preheader", locale, inviter=invited_by_email),
        content=body,
        locale=locale,
    )
    return subject, text, html


def token_created(
    *,
    token_name: str,
    token_prefix: str,
    expires_on: str,
    tokens_url: str,
    locale: Locale,
) -> tuple[str, str, str]:
    """Security notice to the owner: a new personal access token exists. It
    never carries the token itself, only the prefix shown in the UI."""
    subject = t("email.token.subject", locale)
    details = t(
        "email.token.details", locale, name=token_name, prefix=token_prefix, date=expires_on
    )
    text = (
        f"{t('email.token.intro', locale)}\n\n"
        f"{details}\n\n"
        f"{t('email.token.text_revoke', locale)}\n{tokens_url}\n\n"
        f"{_signature(locale)}"
    )
    body = (
        _h1(t("email.token.heading", locale))
        + _p(t_html("email.token.intro", locale))
        + _p(
            t_html(
                "email.token.details",
                locale,
                name=strong(token_name),
                prefix=strong(token_prefix),
                date=strong(expires_on),
            )
        )
        + _p(t_html("email.token.not_you", locale), mute=True)
        + _cta(tokens_url, t("email.token.cta", locale), danger=True)
        + _fallback_link(tokens_url, locale)
    )
    html = _shell(
        title=subject,
        preheader=t("email.token.preheader", locale, name=token_name),
        content=body,
        locale=locale,
    )
    return subject, text, html
