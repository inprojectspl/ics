"""Shared `APIRouter` for admin user-management endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])
