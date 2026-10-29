"""OAuth client lookup + validation. Bootstraps the two MCP-specific
clients (stdio loopback and HTTP) at app startup if missing."""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import OAuthClient

# Stable client_id strings for the two MCP transport profiles. These are
# documented in the user-facing MCP setup guide.
STDIO_CLIENT_ID = "ics-mcp-stdio"
HTTP_CLIENT_ID = "ics-mcp-http"


async def get_active_client(session: AsyncSession, client_id: str) -> OAuthClient | None:
    return await session.scalar(
        select(OAuthClient).where(
            OAuthClient.client_id == client_id,
            OAuthClient.revoked_at.is_(None),
        )
    )


# Built-in loopback pattern: the stdio client listens on a free port each time.
_LOOPBACK_ANY_PORT = "http://127.0.0.1:*"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# Schemes the browser handles itself: a redirect there would run or show the
# code instead of handing it to an app.
_BROWSER_SCHEMES = frozenset({"about", "blob", "data", "file", "javascript", "vbscript"})


def _unsafe_chars(uri: str) -> bool:
    # urlsplit silently drops tabs and newlines, and browsers read a backslash
    # as a slash, so either would let the checked URL differ from the visited one.
    return "\\" in uri or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in uri)


def validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    """Exact match, as required by OAuth 2.1. A built-in client's
    `http://127.0.0.1:*/<path>` pattern also matches that path on any loopback
    port (RFC 8252, section 7.3); the port is the only part allowed to vary."""
    if redirect_uri in client.redirect_uris:
        return True
    if client.is_dynamic or _unsafe_chars(redirect_uri):
        return False
    try:
        parts = urlsplit(redirect_uri)
        port = parts.port
    except ValueError:
        return False
    # Compare the parsed parts, not the text: `http://127.0.0.1:1@evil/callback`
    # starts like a loopback address but sends the browser to `evil`.
    if (
        parts.scheme != "http"
        or not port
        or parts.netloc != f"127.0.0.1:{port}"
        or parts.query
        or parts.fragment
    ):
        return False
    return f"{_LOOPBACK_ANY_PORT}{parts.path}" in client.redirect_uris


def registrable_redirect_uri(uri: object) -> bool:
    """A redirect URI a dynamic client may register: HTTPS, HTTP on a loopback
    host or a native app's private-use scheme such as `cursor://` (RFC 8252,
    sections 7.1 and 7.3), with no credentials, fragment or wildcard."""
    if not isinstance(uri, str) or "*" in uri or _unsafe_chars(uri):
        return False
    try:
        parts = urlsplit(uri)
        _ = parts.port  # raises on a malformed port
    except ValueError:
        return False
    if not parts.scheme or parts.fragment or parts.username is not None:
        return False
    if parts.scheme in ("http", "https"):
        return bool(parts.hostname) and (
            parts.scheme == "https" or parts.hostname in _LOOPBACK_HOSTS
        )
    return parts.scheme not in _BROWSER_SCHEMES


def redirect_origin(redirect_uri: str) -> str:
    """Scheme and host the browser goes to after consent, shown to the user."""
    parts = urlsplit(redirect_uri)
    return f"{parts.scheme}://{parts.netloc}"


def validate_audience(client: OAuthClient, resource: str) -> bool:
    return resource in client.allowed_audiences


async def ensure_builtin_clients(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Idempotent seeder for the two MCP clients. No-op if rows already exist."""
    if not settings.mcp_resource_uri:
        return
    async with session_factory() as session:
        for client_id_str, name, redirect_uris, client_type in [
            (
                STDIO_CLIENT_ID,
                "MCP stdio (Claude Desktop / Claude Code)",
                ["http://127.0.0.1:*/callback"],
                "public",
            ),
            (
                HTTP_CLIENT_ID,
                "MCP HTTP transport (claude.ai et al.)",
                [
                    "https://claude.ai/api/mcp/oauth/callback",
                    "https://claude.com/oauth/callback",
                ],
                "public",
            ),
        ]:
            # Every uvicorn worker seeds on startup at the same moment, so a
            # check-then-insert races; the unique index settles it instead.
            await session.execute(
                insert(OAuthClient)
                .values(
                    client_id=client_id_str,
                    client_secret_hash=None,
                    name=name,
                    client_type=client_type,
                    redirect_uris=redirect_uris,
                    allowed_scopes=["ics"],
                    allowed_audiences=[settings.mcp_resource_uri],
                    is_dynamic=False,
                )
                .on_conflict_do_nothing(index_elements=["client_id"])
            )
        await session.commit()
