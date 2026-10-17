"""Operational CLI: bootstrap admin, list outbox, etc.

Usage (inside container):
    python -m app.cli seed-admin --email admin@example.com --password 'StrongPass123!'
    python -m app.cli outbox-tail
    python -m app.cli relations-rescan [--kind html_bundle]
"""

import argparse
import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app import passwords
from app.db import SessionLocal
from app.models import EmailOutbox, User


async def seed_admin(email: str, password: str, display_name: str | None) -> None:
    passwords.validate_password(password)
    async with SessionLocal() as s:
        existing = (
            await s.execute(select(User).where(User.email == email.lower()))
        ).scalar_one_or_none()
        if existing is not None:
            existing.role = "admin"
            existing.auth_method = "password"
            existing.password_hash = passwords.hash_password(password)
            existing.email_verified_at = datetime.now(UTC)
            print(f"updated existing user -> admin: {email}")
        else:
            s.add(
                User(
                    email=email.lower(),
                    display_name=display_name or email.split("@")[0],
                    role="admin",
                    auth_method="password",
                    password_hash=passwords.hash_password(password),
                    email_verified_at=datetime.now(UTC),
                )
            )
            print(f"created admin: {email}")
        await s.commit()


async def outbox_tail(limit: int) -> None:
    async with SessionLocal() as s:
        rows = (
            (
                await s.execute(
                    select(EmailOutbox).order_by(EmailOutbox.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            print(f"[{r.created_at.isoformat()}] {r.purpose} -> {r.to_email}")
            print(f"  subject: {r.subject}")
            print(f"  body: {r.body}")
            print()


async def relations_rescan(kinds: list[str] | None) -> None:
    from app.config import get_settings
    from app.services.relation_extraction import rescan_all

    async with SessionLocal() as s:
        t = await rescan_all(s, get_settings(), kinds=kinds)
    print(
        f"rescanned {t.assets} assets ({t.failed} failed): "
        f"{t.added} relations added, {t.removed} removed"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s_admin = sub.add_parser("seed-admin")
    s_admin.add_argument("--email", required=True)
    s_admin.add_argument("--password", required=True)
    s_admin.add_argument("--display-name", default=None)

    s_outbox = sub.add_parser("outbox-tail")
    s_outbox.add_argument("--limit", type=int, default=20)

    s_rescan = sub.add_parser(
        "relations-rescan", help="extract relations from current content again (ADR-0016)"
    )
    s_rescan.add_argument("--kind", action="append", default=None)

    sub.add_parser("vapid-keygen", help="print a VAPID key pair for Web Push (ADR-0023)")

    args = parser.parse_args()
    if args.cmd == "seed-admin":
        asyncio.run(seed_admin(args.email, args.password, args.display_name))
    elif args.cmd == "outbox-tail":
        asyncio.run(outbox_tail(args.limit))
    elif args.cmd == "relations-rescan":
        asyncio.run(relations_rescan(args.kind))
    elif args.cmd == "vapid-keygen":
        from app.services.notifications.channels import vapid

        private, public = vapid.generate()
        print(f"ICS_VAPID_PRIVATE_KEY={private}")
        print("ICS_VAPID_SUBJECT=mailto:ops@example.com")
        print(f"# public key (served to browsers): {public}")


if __name__ == "__main__":
    main()
