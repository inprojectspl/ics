"""Symmetric encryption of small secrets at rest (OCR API keys, webhook URLs).

Each purpose gets its own key derived from `ICS_SECRET_KEY`, so a token
encrypted for one purpose never decrypts under another.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


def fernet(settings: Settings, purpose: str) -> Fernet:
    digest = hashlib.sha256(purpose.encode() + b"\x00" + settings.secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(settings: Settings, purpose: str, value: str) -> str:
    return fernet(settings, purpose).encrypt(value.encode()).decode()


def decrypt(settings: Settings, purpose: str, token: str) -> str | None:
    """None when the token is damaged or was made with another secret key."""
    try:
        return fernet(settings, purpose).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
