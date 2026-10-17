"""OAuth client lookup + validation. Bootstraps the two MCP-specific
clients (stdio loopback and HTTP) at app startup if missing."""

from __future__ import annotations

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


def validate_redirect_uri(client: OAuthClient, redirect_uri: str) -> bool:
    """Exact match, as required by OAuth 2.1. Loopback IPs treated as a single
    pattern: `http://127.0.0.1:*/callback` matches any port (stdio uses a
    random port each time)."""
    if redirect_uri in client.redirect_uris:
        return True
    # Loopback wildcard: only stdio client gets this leniency.
    for pattern in client.redirect_uris:
        if pattern.startswith("http://127.0.0.1:*/") and redirect_uri.startswith(
            "http://127.0.0.1:"
        ):
            path_suffix = pattern.removeprefix("http://127.0.0.1:*")
            host_end = redirect_uri.find("/", len("http://127.0.0.1:"))
            if host_end > 0 and redirect_uri[host_end:] == path_suffix:
                return True
    return False


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
