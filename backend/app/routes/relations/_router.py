"""Shared router of the relations package; sub-modules register on it."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["relations"])
