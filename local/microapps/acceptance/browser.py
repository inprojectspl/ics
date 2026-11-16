"""Real-browser helpers: ICS password login, then the app's own sign-in
(app origin -> ICS launch -> one-time code -> host-bound app cookie)."""

from __future__ import annotations

from typing import Any

import localenv as L


def launch(p: Any) -> Any:
    # Trusts exactly the local CA chain (SPKI pins), not every certificate.
    return p.chromium.launch(args=[f"--ignore-certificate-errors-spki-list={L.chain_spki()}"])


def login(browser: Any, user: str) -> Any:
    context = browser.new_context()
    page = context.new_page()
    page.goto(f"{L.BASE_URL}/#login")
    page.fill('input[type="email"]', L.email(user))
    page.fill('input[type="password"]', L.password(user))
    with page.expect_response(lambda r: r.url.endswith("/api/auth/login")) as resp:
        page.locator('button[type="submit"]').first.click()
    if not resp.value.ok:
        raise RuntimeError(f"ICS login of {user} failed: {resp.value.status}")
    page.wait_for_timeout(500)
    return context


def open_app(context: Any, app_url: str) -> Any:
    page = context.new_page()
    page.goto(app_url)
    page.wait_for_url(f"{app_url}**", timeout=20000)
    page.wait_for_function("() => window.ics !== undefined", timeout=10000)
    return page
