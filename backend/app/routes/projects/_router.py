"""Shared `APIRouter` for project endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/projects", tags=["projects"])
