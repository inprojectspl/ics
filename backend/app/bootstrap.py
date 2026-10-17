"""Startup bootstrap helpers.

`ensure_bootstrap_admin()` is idempotent: when both env variables are set, it
creates or syncs that admin account. Safe to call on every startup.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import passwords
from app.config import Settings
from app.models import User

logger = logging.getLogger(__name__)


async def ensure_bootstrap_admin(session_factory: async_sessionmaker, settings: Settings) -> None:
    email = settings.bootstrap_admin_email.strip().lower()
    pwd = settings.bootstrap_admin_password
    if not email or not pwd:
        return

    try:
        passwords.validate_password(pwd)
    except passwords.WeakPasswordError as e:
        logger.warning("bootstrap_admin_password is too weak: %s, skipping bootstrap", e)
        return

    # Sync even when other admins exist, so a dev setup can always log in with the env password.
    async with session_factory() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if existing is not None:
            changed = False
            if existing.role != "admin":
                existing.role = "admin"
                changed = True
            if existing.auth_method != "password":
                existing.auth_method = "password"
                changed = True
            if existing.email_verified_at is None:
                existing.email_verified_at = now
                changed = True
            if not existing.password_hash or not passwords.verify_password(
                pwd, existing.password_hash
            ):
                existing.password_hash = passwords.hash_password(pwd)
                existing.locked_until = None
                changed = True
            if changed:
                await session.commit()
                logger.info("Bootstrap admin: synced %s", email)
        else:
            session.add(
                User(
                    email=email,
                    display_name=email.split("@")[0],
                    role="admin",
                    auth_method="password",
                    password_hash=passwords.hash_password(pwd),
                    email_verified_at=now,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # The other uvicorn worker created it a moment earlier.
                await session.rollback()
                return
            logger.info("Bootstrap admin: created %s", email)
