"""Shared `APIRouter` for binding endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/bindings", tags=["bindings"])
