"""Shared `APIRouter` + PKCE/base64 helpers for OAuth endpoints."""

from __future__ import annotations

import hashlib
import secrets
from base64 import urlsafe_b64encode

from fastapi import APIRouter, Request

from app import ratelimit
from app.config import Settings
from app.redis_client import get_redis
from app.util import ip_hash

router = APIRouter(prefix="/api/auth/oauth", tags=["oauth"])


def _issuer(settings: Settings) -> str:
    return (settings.oauth_issuer or settings.base_url).rstrip("/")


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """S256: BASE64URL-NOPAD(SHA256(verifier)) == challenge."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected = urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(expected, code_challenge)


async def _enforce_ip_limit(request: Request, rl: ratelimit.RateLimit) -> None:
    """Per-IP bucket for the anonymous authorization-server surface."""
    await ratelimit.enforce(get_redis(), rl, ip_hash(request))
