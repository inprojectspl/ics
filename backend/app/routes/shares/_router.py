"""Shared `APIRouter` for share endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["shares"])

SESSION_VERIFIED_KEY = "verified_shares"
