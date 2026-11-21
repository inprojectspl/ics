"""Browser check of copyable asset addresses (`ics_share`) on the local
profile, in Chromium and WebKit: a sender browses an HTML bundle and a
micro-application opened through a share link and copies the address bar; an
independent recipient (fresh browser context, no cookies) opens that address,
passes the link's gate and lands on the same page, query and fragment.

Needs `scripts/microapps-local.sh up` and `seed` (the `requests` app owned by
alice). Run:

    uv run --project ../ics-mcp --with playwright==1.65.1 \\
        python local/microapps/acceptance/share_context.py

Results go to the console and .microapps-local/share-context-report.json; a
failed check fails the run.
"""

from __future__ import annotations

import json
import sys
import traceback
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import localenv as L  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

HTML_BASE = "https://html.ics.localhost:8443"
APPS = json.loads((L.STATE / "apps.json").read_text())
PASSWORD = "Long-enough-pass-42"
RESULTS: list[dict[str, Any]] = []

INDEX = b"""<!doctype html><html><head><meta charset="utf-8"><title>Report</title>
<script src="app.js"></script></head><body>
<h1 id="top">Report</h1>
<a id="sub" href="sub/page.html?tab=wyniki#koszty">Costs</a>
<a id="local" href="#top">Top</a>
<a id="ext" href="https://example.com/">External</a>
<a id="author" href="sub/page.html?ics_share=AUTHORAUTHORAUTHORAUTHOR">Author link</a>
<a id="file" href="app.js">Script</a>
<button id="push" type="button">Push</button>
</body></html>"""
APP_JS = b"""document.addEventListener("DOMContentLoaded", function () {
  setTimeout(function () {
    var a = document.createElement("a");
    a.id = "dynamic"; a.href = "sub/page.html?from=dynamic"; a.textContent = "Dynamic";
    document.body.appendChild(a);
  }, 30);
  document.getElementById("push").addEventListener("click", function () {
    history.pushState({ app: 1 }, "", "?view=2");
  });
});"""
SUB = (
    b'<!doctype html><html><head><meta charset="utf-8"><title>Sub</title></head><body>'
    b'<div style="height:3000px">filler</div><h2 id="koszty">Costs</h2>'
    b'<div style="height:3000px">filler</div></body></html>'
)


def check(name: str, ok: bool, detail: Any = None) -> None:
    RESULTS.append({"check": name, "ok": bool(ok), "detail": None if ok else detail})
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  [{detail}]"))


# ---------- ICS API as alice ----------


class Api:
    def __init__(self, user: str) -> None:
        self.ctx = L.ssl_context()
        self.cookie = ""
        r = self._send("POST", "/api/auth/login", json.dumps({"email": L.email(user), "password": L.password(user)}).encode(), "application/json")
        self.cookie = "; ".join(c.split(";", 1)[0] for c in r.headers.get_all("set-cookie") or [])

    def _send(self, method: str, path: str, body: bytes | None, ctype: str | None) -> Any:
        req = urllib.request.Request(f"{L.BASE_URL}{path}", data=body, method=method)
        req.add_header("Origin", L.BASE_URL)
        if ctype:
            req.add_header("Content-Type", ctype)
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        return urllib.request.urlopen(req, context=self.ctx)

    def json(self, method: str, path: str, payload: Any = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        with self._send(method, path, body, "application/json" if body else None) as r:
            return json.loads(r.read() or b"null")

    def upload_bundle(self, files: dict[str, bytes]) -> dict[str, Any]:
        boundary = uuid.uuid4().hex
        parts: list[bytes] = []
        for path, content in files.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.rsplit("/", 1)[-1]}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n")
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="paths"\r\n\r\n{path}\r\n'.encode())
        body = b"".join(parts) + f"--{boundary}--\r\n".encode()
        with self._send("POST", "/api/assets/html", body, f"multipart/form-data; boundary={boundary}") as r:
            return json.loads(r.read())

    def share(self, asset_id: str, **body: Any) -> dict[str, Any]:
        return self.json("POST", f"/api/assets/{asset_id}/shares", {"mode": "public", **body})


# ---------- browsers ----------


def new_context(browser: Any, logged_in: Api | None = None) -> Any:
    context = browser.new_context(ignore_https_errors=browser.browser_type.name != "chromium", locale="en-US")
    if logged_in:
        for pair in logged_in.cookie.split("; "):
            name, _, value = pair.partition("=")
            context.add_cookies([{"name": name, "value": value, "url": L.BASE_URL}])
    return context


def query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def html_bundle_scenarios(browser: Any, api: Api, tag: str) -> None:
    asset = api.upload_bundle({"index.html": INDEX, "app.js": APP_JS, "sub/page.html": SUB})
    slug = asset["slug"]
    link = api.share(asset["id"])
    other = api.share(asset["id"])
    gated = api.share(asset["id"], mode="password", password=PASSWORD)
    T = link["token"]

    # Sender: the owner opens the share link, then the bundle full screen.
    sender = new_context(browser, api)
    page = sender.new_page()
    page.goto(f"{L.BASE_URL}/s/{T}")
    page.get_by_role("button", name="Open full screen").click()
    page.wait_for_url(f"{HTML_BASE}/{slug}/**")
    check(f"{tag} A03 owner's address keeps the opened link", query(page.url).get("ics_share") == [T], page.url)
    page.wait_for_selector("#dynamic")
    href = lambda sel: page.get_attribute(sel, "href")  # noqa: E731
    check(f"{tag} A04/A11 subpage link carries the link before the fragment", href("#sub") == f"sub/page.html?tab=wyniki&ics_share={T}#koszty", href("#sub"))
    check(f"{tag} A11 local anchor untouched", href("#local") == "#top", href("#local"))
    check(f"{tag} A17 external link and file untouched", href("#ext") == "https://example.com/" and href("#file") == "app.js", (href("#ext"), href("#file")))
    check(f"{tag} A07 author's own token untouched", href("#author") == "sub/page.html?ics_share=AUTHORAUTHORAUTHORAUTHOR", href("#author"))
    check(f"{tag} A06 dynamic link decorated", href("#dynamic") == f"sub/page.html?from=dynamic&ics_share={T}", href("#dynamic"))
    entries = page.evaluate("history.length")
    page.click("#push")
    check(f"{tag} A08 pushState keeps the link and the app's state", query(page.url) == {"view": ["2"], "ics_share": [T]} and page.evaluate("history.state && history.state.app") == 1, page.url)
    check(f"{tag} A08 one history entry per push", page.evaluate("history.length") == entries + 1)
    check(f"{tag} script adds no element to the page", page.evaluate("document.querySelectorAll('body *:not(a):not(h1):not(button):not(script)').length") == 0)

    page.click("#sub")
    page.wait_for_url(f"**/{slug}/sub/page.html**")
    check(f"{tag} A04 subpage opened with the link", query(page.url).get("ics_share") == [T] and page.url.endswith("#koszty"), page.url)
    # Same tab, an address without the token (location.href): restored.
    page.evaluate("location.href = 'page.html?x=1'")
    page.wait_for_url(f"**/{slug}/sub/page.html?x=1**")
    page.wait_for_function(f"location.search.includes('ics_share={T}')", timeout=5000)
    check(f"{tag} A14 location.href without the token gets it back", query(page.url) == {"x": ["1"], "ics_share": [T]}, page.url)
    page.go_back()
    page.wait_for_url("**#koszty")
    check(f"{tag} A10 back restores the entry with its link", query(page.url).get("tab") == ["wyniki"] and query(page.url).get("ics_share") == [T], page.url)
    copied = page.url

    # A19: a new tab opened from here with an explicit other link keeps it.
    with sender.expect_page() as popup_info:
        page.evaluate(f"window.open('/{slug}/index.html?ics_share={other['token']}')")
    popup = popup_info.value
    popup.wait_for_load_state()
    popup.wait_for_selector("#sub")
    check(f"{tag} A19 explicit link of a new tab wins over the copied context", f"ics_share={other['token']}" in (popup.get_attribute("#sub", "href") or ""), popup.get_attribute("#sub", "href"))
    check(f"{tag} A18 first tab keeps its own link", query(page.url).get("ics_share") == [T], page.url)
    popup.close()

    # Recipient: another browser context, no cookies, the copied address.
    recipient = new_context(browser)
    rpage = recipient.new_page()
    rpage.goto(copied)
    rpage.wait_for_url(f"{HTML_BASE}/{slug}/sub/page.html**#koszty", timeout=20000)
    check(f"{tag} A01 recipient lands on the page, query and fragment", rpage.url == copied, (rpage.url, copied))
    recipient.close()

    # A13: a password link; the fragment survives the gate on ICS.
    P = gated["token"]
    target = f"{HTML_BASE}/{slug}/sub/page.html?tab=1&ics_share={P}#koszty"
    recipient = new_context(browser)
    rpage = recipient.new_page()
    rpage.goto(target)
    rpage.wait_for_url(f"{L.BASE_URL}/s/{P}**")
    rpage.get_by_label("Password").fill(PASSWORD)
    rpage.get_by_role("button", name="Open").click()
    rpage.wait_for_url(f"{HTML_BASE}/{slug}/sub/page.html**", timeout=20000)
    rpage.wait_for_function("location.hash === '#koszty'", timeout=5000)
    check(f"{tag} A13 password gate keeps page, query and fragment", rpage.url == target, rpage.url)
    recipient.close()

    # A15: the session is gone and an address lost the token: the entry page
    # resumes through the tab's link, once, without the reader's content.
    sender.clear_cookies()
    page.evaluate(f"location.href = '/{slug}/index.html?from=redirect'")
    page.wait_for_url(f"{HTML_BASE}/{slug}/index.html?from=redirect&ics_share={T}", timeout=20000)
    check(f"{tag} A15 expired session resumes through the tab's link", query(page.url) == {"from": ["redirect"], "ics_share": [T]}, page.url)
    for c in api.cookie.split("; "):
        name, _, value = c.partition("=")
        sender.add_cookies([{"name": name, "value": value, "url": L.BASE_URL}])

    # A24: storage throws; explicit addresses and links still work.
    nostore = new_context(browser)
    # Only on the bundle's origin: the ICS panel keeps its own storage.
    nostore.add_init_script("if (location.hostname.startsWith('html.')) Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('blocked'); } })")
    spage = nostore.new_page()
    spage.goto(f"{HTML_BASE}/{slug}/index.html?ics_share={T}")
    spage.wait_for_url(f"{HTML_BASE}/{slug}/index.html?ics_share={T}", timeout=20000)
    spage.wait_for_selector("#dynamic")
    check(f"{tag} A24 without sessionStorage links still carry the link", spage.get_attribute("#sub", "href") == f"sub/page.html?tab=wyniki&ics_share={T}#koszty", spage.get_attribute("#sub", "href"))
    nostore.close()

    # A21: an invalid token is refused without falling back to the tab's link.
    rpage = sender.new_page()
    rpage.goto(f"{HTML_BASE}/{slug}/index.html?ics_share={T}&ics_share={T}")
    check(f"{tag} A21 repeated parameter refused, no content", "Report" not in rpage.content() and rpage.url.startswith(HTML_BASE), rpage.url)
    rpage.close()

    # A20: a fresh open from the panel in the same tab drops the link context.
    page.goto(f"{L.BASE_URL}/v/{slug}")
    page.get_by_role("button", name="Open full screen").click()
    page.wait_for_url(f"{HTML_BASE}/{slug}/index.html")
    page.wait_for_selector("#dynamic")
    check(f"{tag} A20 direct open has no link in the address or links", "ics_share" not in page.url and page.get_attribute("#sub", "href") == "sub/page.html?tab=wyniki#koszty", (page.url, page.get_attribute("#sub", "href")))
    page.click("#sub")
    page.wait_for_url("**#koszty")
    check(f"{tag} A20 next page of the direct visit stays without a link", "ics_share" not in page.url, page.url)
    # Back past the direct entry and the ICS reader to the copied link entry.
    for _ in range(3):
        page.go_back()
    page.wait_for_url(f"**ics_share={T}**")
    check(f"{tag} A10 back to the earlier link entry restores its link", query(page.url).get("ics_share") == [T], page.url)
    sender.close()


def micro_app_scenario(browser: Any, api: Api, tag: str) -> None:
    app = APPS["requests"]
    gated = api.share(app["asset_id"], mode="password", password=PASSWORD, app_permissions=["requests.read"])
    P = gated["token"]
    base = app["app_url"].rstrip("/")
    target = f"{base}/index.html?tab=2&ics_share={P}#mine"
    recipient = new_context(browser)
    page = recipient.new_page()
    page.goto(target)
    page.wait_for_url(f"{L.BASE_URL}/s/{P}**", timeout=20000)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Open").click()
    page.wait_for_url(f"{base}/index.html**", timeout=20000)
    page.wait_for_function("window.ics !== undefined", timeout=10000)
    page.wait_for_function("location.hash === '#mine'", timeout=5000)
    check(f"{tag} A02/A13 app recipient passes the gate and lands on page, query and fragment", page.url == target, page.url)
    me = page.evaluate("window.ics.session().then(s => s.user.guest)")
    check(f"{tag} A02 recipient is a guest of exactly that link", me is True, me)
    # A member opening the same address keeps their own session.
    member = new_context(browser, api)
    mpage = member.new_page()
    mpage.goto(target)
    mpage.wait_for_url(f"{base}/index.html?tab=2&ics_share={P}**", timeout=20000)
    mpage.wait_for_function("window.ics !== undefined", timeout=10000)
    guest = mpage.evaluate("window.ics.session().then(s => s.user.guest)")
    check(f"{tag} A03 member keeps their own session and the link in the address", guest is False and query(mpage.url).get("ics_share") == [P], (guest, mpage.url))
    member.close()
    recipient.close()


def main() -> int:
    L.assert_local_target()
    api = Api("alice")
    with sync_playwright() as p:
        engines = [
            ("chromium", p.chromium.launch(args=[f"--ignore-certificate-errors-spki-list={L.chain_spki()}"])),
            ("webkit", p.webkit.launch()),
        ]
        for name, browser in engines:
            print(f"\n== {name}")
            for scenario in (html_bundle_scenarios, micro_app_scenario):
                try:
                    scenario(browser, api, name)
                except Exception as exc:  # a broken step fails the scenario, not the run
                    traceback.print_exc()
                    check(f"{name} {scenario.__name__} ran to the end", False, repr(exc))
            browser.close()
    (L.STATE / "share-context-report.json").write_text(json.dumps(RESULTS, indent=2))
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
