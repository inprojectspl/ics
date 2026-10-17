"""Shared `APIRouter` for the MCP endpoints, with their per-user rate limit.
Kept apart so submodules can import it without cycles."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_mcp_rate_limit

router = APIRouter(
    prefix="/api/assets",
    tags=["assets-mcp"],
    dependencies=[Depends(require_mcp_rate_limit)],
)
