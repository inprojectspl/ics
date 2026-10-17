"""Origin check for state-changing requests that carry cookies."""

from urllib.parse import urlsplit

import structlog

from app.config import get_settings
from app.errors import error_response

log = structlog.get_logger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
# "same-site" is not enough: the HTML bundle viewer is a sibling subdomain
# that serves user-uploaded pages.
_TRUSTED_FETCH_SITES = frozenset({b"same-origin", b"none"})


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


def trusted_origins() -> frozenset[str]:
    settings = get_settings()
    return frozenset(_origin_of(o) for o in [settings.base_url, *settings.cors_origins_list] if o)


class CsrfOriginMiddleware:
    """Rejects cross-site POST/PUT/PATCH/DELETE made with the session cookie.

    SameSite=lax is not enough: forms are not JSON, and sibling subdomains count as
    same-site. Origin (else Sec-Fetch-Site) must be the app; cookieless, bearer and
    header-less non-browser requests pass.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        authorization = headers.get(b"authorization", b"")
        if b"cookie" not in headers or authorization[:7].lower() == b"bearer ":
            await self.app(scope, receive, send)
            return

        origin = headers.get(b"origin")
        if origin is not None:
            allowed = origin.decode("latin-1").lower() in trusted_origins()
        else:
            fetch_site = headers.get(b"sec-fetch-site")
            allowed = fetch_site is None or fetch_site in _TRUSTED_FETCH_SITES

        if not allowed:
            log.warning(
                "csrf_origin_rejected",
                path=scope.get("path"),
                origin=origin.decode("latin-1") if origin else None,
            )
            response = error_response(403, "csrf_origin_rejected", "cross-site request rejected")
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
