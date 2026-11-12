"""BROWSER helper for the ICS-MCP stdio OAuth login in the local profile.

Python's `webbrowser` waits for the command, while ICS-MCP's loopback
callback runs in the same event loop, so the helper detaches at once and
completes the flow in a headless Chromium: real password login on the
local ICS, real consent, redirect to the 127.0.0.1 callback.
"""

from __future__ import annotations

import os
import sys
import time


def main(url: str) -> None:
    from playwright.sync_api import sync_playwright

    email = os.environ["ICS_LOCAL_LOGIN_EMAIL"]
    password = os.environ["ICS_LOCAL_LOGIN_PASSWORD"]
    spki = os.environ["ICS_LOCAL_SPKI"]
    log = open(os.path.join(os.environ.get("TMPDIR", "/tmp"), "ics-local-login.log"), "a")  # noqa: SIM115
    with sync_playwright() as p:
        browser = p.chromium.launch(args=[f"--ignore-certificate-errors-spki-list={spki}"])
        page = browser.new_page()
        page.goto(url)
        deadline = time.time() + 60
        while time.time() < deadline:
            if page.url.startswith("http://127.0.0.1:"):
                break
            if page.locator('input[type="password"]').count():
                page.fill('input[type="email"]', email)
                page.fill('input[type="password"]', password)
                page.locator('button[type="submit"]').first.click()
                page.wait_for_timeout(1500)
                continue
            allow = page.locator('button[name="decision"][value="allow"]')
            if allow.count():
                allow.click()
                page.wait_for_timeout(1500)
                continue
            page.wait_for_timeout(300)
        log.write(f"{time.ctime()} login flow for {email} ended at {page.url.split('?')[0]}\n")
        browser.close()


if __name__ == "__main__":
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    main(sys.argv[1])
