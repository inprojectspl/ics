"""OAuth consent page (GET /authorize), standalone and script-free so it works
under any CSP; palette copied from `frontend/src/styles/theme.css`.

`client_name` (from unauthenticated DCR) and `resource` (query string) are
attacker-controlled, so every dynamic value and catalogue text is escaped.
"""

from __future__ import annotations

import html

from app.i18n import Locale, has_key, strong, t, t_html

# The small-size ICS mark (frontend/public/favicon.svg), as the app shows it
# below 32 px, drawn in the brand colour.
_MARK = (
    '<svg width="28" height="28" viewBox="0 0 16 16" fill="none" aria-hidden="true"><g fill="#ff5500">'
    '<path d="m3 3 6 4 4-4M9 7 4 12M9 7l3 6" fill="none" stroke="#ff5500" stroke-width="1.25" '
    'stroke-linecap="round"/><circle cx="3" cy="3" r="1.75"/><circle cx="9" cy="7" r="2.25"/>'
    '<circle cx="13" cy="3" r="1.5"/><circle cx="4" cy="12" r="1.75"/><circle cx="12" cy="13" r="1.75"/>'
    "</g></svg>"
)

_CHECK = (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M20 6 9 17l-5-5"/></svg>'
)

_CSS = """
:root{--canvas:#f5f7fa;--surface:#fff;--subtle:#f0f3f7;--border:#dce3ec;--strong:#c6d0dc;
--ink:#182332;--soft:#4b5b70;--mute:#64748b;--accent:#1769d2;--accent-hover:#145cb8;
--on-accent:#fff;--success:#147d59;--hover:#e9eff6;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--canvas:#101419;--surface:#181f28;--subtle:#202a36;
--border:#323f51;--strong:#405269;--ink:#f4f7fb;--soft:#b7c3d2;--mute:#a8b5c4;--accent:#8abbff;
--accent-hover:#a6caff;--on-accent:#071929;--success:#5ad6a0;--hover:#263243}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;padding:48px 16px;background:var(--canvas);color:var(--ink);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif}
.brand{display:flex;align-items:center;gap:8px;margin-bottom:32px;font-weight:600;letter-spacing:.04em}
.card{width:100%;max-width:400px;background:var(--surface);border:1px solid var(--border);
border-radius:14px;padding:32px;box-shadow:0 1px 2px rgb(16 24 36/.06)}
h1{margin:0;font-size:20px;line-height:1.35;font-weight:600;text-align:center;overflow-wrap:anywhere}
.who{margin:6px 0 24px;text-align:center;color:var(--soft)}
.asks{margin:0 0 8px;font-weight:600}
ul{list-style:none;margin:0 0 20px;padding:0;border:1px solid var(--border);border-radius:10px}
li{display:flex;gap:10px;align-items:flex-start;padding:10px 12px}
li+li{border-top:1px solid var(--border)}
li svg{flex:none;margin-top:4px;color:var(--success)}
.resource{margin:0 0 24px;font-size:13px;color:var(--mute);overflow-wrap:anywhere}
code{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--soft)}
form{display:flex;flex-direction:column;gap:8px}
button{height:40px;border-radius:10px;font:inherit;font-weight:600;cursor:pointer}
.ok{border:0;background:var(--accent);color:var(--on-accent)}
.ok:hover{background:var(--accent-hover)}
.cancel{border:1px solid var(--strong);background:var(--surface);color:var(--ink)}
.cancel:hover{background:var(--hover)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.note{max-width:400px;margin:16px 0 0;text-align:center;font-size:13px;color:var(--mute)}
"""


def _scope_label(scope: str, locale: Locale) -> str:
    """Readable name of a scope; an unknown one shows its code."""
    key = f"consent.scope.{scope}"
    return t_html(key, locale) if has_key(key) else f"<code>{html.escape(scope)}</code>"


def render_consent(
    *,
    locale: Locale,
    client_name: str,
    user_email: str,
    scopes: list[str],
    resource: str,
    state_token: str,
) -> str:
    """The consent page in `locale`, every dynamic value escaped."""
    items = "".join(f"<li>{_CHECK}<span>{_scope_label(s, locale)}</span></li>" for s in scopes)
    return f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="robots" content="noindex">
<title>{t_html("consent.title", locale, client=client_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="brand">{_MARK}<span>ICS</span></div>
<main class="card">
  <h1>{t_html("consent.question", locale, client=strong(client_name))}</h1>
  <p class="who">{t_html("consent.signed_in_as", locale, email=strong(user_email))}</p>
  <p class="asks">{t_html("consent.asks", locale)}</p>
  <ul>{items}</ul>
  <p class="resource">{t_html("consent.resource", locale)} <code>{html.escape(resource)}</code></p>
  <form method="post" action="/api/auth/oauth/authorize">
    <input type="hidden" name="state_token" value="{html.escape(state_token)}">
    <button type="submit" name="decision" value="allow" class="ok">{t_html("consent.allow", locale)}</button>
    <button type="submit" name="decision" value="deny" class="cancel">{t_html("consent.deny", locale)}</button>
  </form>
</main>
<p class="note">{html.escape(t("consent.note", locale))}</p>
</body>
</html>"""
