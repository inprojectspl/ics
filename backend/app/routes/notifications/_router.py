"""Shared routers for notification endpoints (ADR-0023)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/notifications", tags=["notifications"])
watches_router = APIRouter(prefix="/api/watches", tags=["notifications"])
