"""Helpers shared by the relation endpoints."""

from __future__ import annotations

from typing import TypedDict

from fastapi import Request

from app import audit


class AuditContext(TypedDict):
    transport: str | None
    client_id_external: str | None


def transport_of(request: Request) -> AuditContext:
    """Audit context of the call: transport decides the edge origin."""
    return {
        "transport": audit.request_transport(request),
        "client_id_external": getattr(request.state, "oauth_client_id_external", None),
    }
