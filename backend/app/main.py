from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.auth import enforce_token_scope
from app.body_limit import BodySizeLimitMiddleware
from app.bootstrap import ensure_bootstrap_admin
from app.config import get_settings
from app.csrf import CsrfOriginMiddleware
from app.db import SessionLocal
from app.domain_errors import DomainError
from app.errors import domain_error_handler, http_error_handler, validation_error_handler
from app.json_response import ORJSONResponse
from app.oauth.clients import ensure_builtin_clients
from app.oauth.server import discovery_router as oauth_discovery_router
from app.oauth.server import router as oauth_router
from app.routes import (
    admin,
    admin_users,
    assets,
    auth,
    bindings,
    doc_types,
    health,
    html_viewer,
    mcp_assets,
    notifications,
    projects,
    relations,
    shared,
    shares,
)


class SecurityHeadersMiddleware:
    """Global security headers; headers a router already set (the bundle viewer's CSP/XFO) win.

    No CSP here: the SPA build inlines init JS, so only `'unsafe-inline'` would work.
    HSTS only outside debug. Plain ASGI rather than `BaseHTTPMiddleware`, whose
    per-request task group and stream add up over a bundle's many file requests."""

    def __init__(self, app, *, hsts_enabled: bool) -> None:
        self.app = app
        self._headers: list[tuple[bytes, bytes]] = [
            (b"x-frame-options", b"SAMEORIGIN"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
        ]
        if hsts_enabled:
            self._headers.append(
                (b"strict-transport-security", b"max-age=31536000; includeSubDomains")
            )

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {name.lower() for name, _ in headers}
                headers.extend(
                    (name, value) for name, value in self._headers if name not in present
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await ensure_bootstrap_admin(SessionLocal, settings)
    await ensure_builtin_clients(SessionLocal, settings)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ICS - Internal Content Sharing",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
        # Read-only tokens must not reach a writing route (ADR-0020).
        dependencies=[Depends(enforce_token_scope)],
    )

    # Innermost, so its 413 still passes through CORS and security headers.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(CsrfOriginMiddleware)
    # Not "strict": the cross-site Google OIDC callback would arrive without the cookie.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        https_only=not settings.debug,
        same_site="lax",
    )
    if len(settings.cors_origins_list) != len(
        [o for o in settings.cors_origins.split(",") if o.strip()]
    ):
        log.warning("cors_html_viewer_origin_ignored", origin=settings.html_viewer_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added last, so outermost (Starlette stacks LIFO) and sees the final response.
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts_enabled=not settings.debug,
    )

    # Every error body carries `code` (see app/errors.py) and is sent with
    # `no-store`, so a cached 410 can't outlive the admin action that fixes it.
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    # Services raise domain errors; this is the single place that turns
    # them into the same `{detail, code}` body with the category's status.
    app.add_exception_handler(DomainError, domain_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(oauth_discovery_router)
    app.include_router(oauth_router)
    # Order matters: first match wins, and static /api/assets paths (mcp_assets,
    # relations, view) must precede crud's `/{asset_id}`, which would 422 on them.
    app.include_router(mcp_assets.router)
    app.include_router(relations.router)
    app.include_router(assets.view_router)
    app.include_router(assets.crud_router)
    app.include_router(assets.versions_router)
    app.include_router(assets.content_router)
    app.include_router(assets.shares_router)
    app.include_router(shares.router)
    app.include_router(admin.router)
    app.include_router(admin_users.router)
    app.include_router(doc_types.router)
    app.include_router(doc_types.admin_router)
    app.include_router(bindings.router)
    app.include_router(projects.router)
    app.include_router(notifications.router)
    app.include_router(notifications.watches_router)
    app.include_router(shared.router)
    app.include_router(html_viewer.router)
    return app


app = create_app()
