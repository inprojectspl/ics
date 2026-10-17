"""Audit logging: single entry point for writing rows into `audit_log`.

Callers pass a resolved actor, so it works from background tasks and the CLI. It
never commits: audit rows roll back with the action they describe. Keep payloads
small.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, OAuthClient, User

AGENT_TRANSPORTS: frozenset[str] = frozenset({"bearer"})


def request_transport(request: Any) -> str | None:
    """Transport the auth dependency recorded on the request: `cookie`,
    `bearer` (OAuth, MCP), `pat` (ADR-0020) or `dev_stub`."""
    return getattr(request.state, "oauth_transport", None)


def is_agent_transport(transport: str | None) -> bool:
    """A write through an MCP bearer token is an agent's. PAT requests are
    read only (ADR-0020, `ics:read`), so they never reach a write path."""
    return transport in AGENT_TRANSPORTS


def actor_label(actor: User | str | None) -> str:
    if actor is None:
        return "anonymous"
    if isinstance(actor, str):
        return actor
    return f"user:{actor.email}"


async def _resolve_client_uuid(
    session: AsyncSession, client_id_external: str | None
) -> UUID | None:
    if not client_id_external:
        return None
    return await session.scalar(
        select(OAuthClient.id).where(OAuthClient.client_id == client_id_external)
    )


async def record(
    session: AsyncSession,
    *,
    actor: User | str | None,
    action: str,
    target: str | None = None,
    payload: dict[str, Any] | None = None,
    ip_hash: str | None = None,
    client_id_external: str | None = None,
    transport: str | None = None,
) -> None:
    client_uuid = await _resolve_client_uuid(session, client_id_external)
    session.add(
        AuditLog(
            actor=actor_label(actor),
            action=action,
            target=target,
            payload=payload,
            ip_hash=ip_hash,
            client_id=client_uuid,
            transport=transport,
        )
    )


async def record_from_request(
    session: AsyncSession,
    request,  # fastapi.Request, typed as Any to keep this import-light
    *,
    actor: User | str | None,
    action: str,
    target: str | None = None,
    payload: dict[str, Any] | None = None,
    ip_hash: str | None = None,
) -> None:
    """Convenience wrapper that pulls oauth_* markers off request.state."""
    client_id_external = getattr(request.state, "oauth_client_id_external", None)
    transport = request_transport(request)
    await record(
        session,
        actor=actor,
        action=action,
        target=target,
        payload=payload,
        ip_hash=ip_hash,
        client_id_external=client_id_external,
        transport=transport,
    )
