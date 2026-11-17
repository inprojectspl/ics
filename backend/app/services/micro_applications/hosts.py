"""Public origins of micro-applications.

Every app environment is served on `<name>.<app host suffix>`, where `name`
is a random 8-character label reserved for good in `microapp_host_names`.
The long `a-<asset hex>-<env>` host of the first PoC releases and the
configured public aliases keep serving the same app. A host only says which
app a request is for; sessions, launch codes and permissions decide the rest.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import NotFoundError
from app.models import MicroAppEnvironment, MicroAppHostName
from app.services.micro_applications.common import ENVIRONMENT
from app.slug import _ALPHABET, generate_slug

HOST_NAME_LENGTH = 8
# 31 characters to the power of 8 is about 8.5e11 names: a retry is rare and
# a run of them means something else is wrong.
MAX_ATTEMPTS = 16
_SHORT_RE = re.compile(f"[{_ALPHABET}]{{{HOST_NAME_LENGTH}}}")
_LEGACY_RE = re.compile(r"a-([0-9a-f]{32})-([a-z]+)")


def app_host(settings: Settings, env: MicroAppEnvironment) -> str:
    return f"{env.host_name}.{settings.microapps_app_host_suffix}"


def app_url(settings: Settings, env: MicroAppEnvironment) -> str:
    """Where people open the app: a configured public alias (a tunnel to the
    local profile) when there is one, otherwise the short host."""
    if env.environment == ENVIRONMENT:
        for alias, hex_ in settings.microapps_alias_map.items():
            if hex_ == env.asset_hex:
                return f"https://{alias}/"
    return f"{settings.microapps_app_scheme}://{app_host(settings, env)}/"


def _alias_labels(settings: Settings) -> set[str]:
    suffix = f".{settings.microapps_app_host_suffix}"
    return {h.removesuffix(suffix) for h in settings.microapps_alias_map if h.endswith(suffix)}


async def _reserved_name(session: AsyncSession, asset_id: Any, environment: str) -> str | None:
    return await session.scalar(
        select(MicroAppHostName.name).where(
            MicroAppHostName.asset_id == asset_id, MicroAppHostName.environment == environment
        )
    )


async def allocate_host_name(
    session: AsyncSession, settings: Settings, asset_id: Any, environment: str = ENVIRONMENT
) -> str:
    """The app environment's name: the one it already holds, or a new random
    one. Unique by the primary key, so two parallel creations never get the
    same name; `ON CONFLICT DO NOTHING` keeps the caller's transaction usable
    and a taken name is simply drawn again."""
    held = await _reserved_name(session, asset_id, environment)
    if held is not None:
        return held
    aliases = _alias_labels(settings)
    for _ in range(MAX_ATTEMPTS):
        name = generate_slug(HOST_NAME_LENGTH)
        if name in aliases:
            continue
        got = await session.scalar(
            insert(MicroAppHostName)
            .values(name=name, asset_id=asset_id, environment=environment)
            .on_conflict_do_nothing()
            .returning(MicroAppHostName.name)
        )
        if got is not None:
            return got
        # Either the name is taken or a parallel request reserved one for
        # this same environment first; that one is then the answer.
        held = await _reserved_name(session, asset_id, environment)
        if held is not None:
            return held
    raise RuntimeError("no free micro-application host name")


async def env_for_host(session: AsyncSession, settings: Settings, host: str) -> MicroAppEnvironment:
    """The environment served on exactly this host, or `not_found`.
    Accepts a configured alias, `<name>.<suffix>` and `a-<hex>-prod.<suffix>`."""
    host = host.lower()
    alias_hex = settings.microapps_alias_map.get(host)
    if alias_hex is not None:
        stmt = select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_hex == alias_hex,
            MicroAppEnvironment.environment == ENVIRONMENT,
        )
    else:
        label = host.removesuffix(f".{settings.microapps_app_host_suffix}")
        legacy = _LEGACY_RE.fullmatch(label)
        if label == host:
            raise NotFoundError("not_found", "unknown application")
        if _SHORT_RE.fullmatch(label):
            stmt = select(MicroAppEnvironment).where(MicroAppEnvironment.host_name == label)
        elif legacy and legacy.group(2) == ENVIRONMENT:
            stmt = select(MicroAppEnvironment).where(
                MicroAppEnvironment.asset_hex == legacy.group(1),
                MicroAppEnvironment.environment == ENVIRONMENT,
            )
        else:
            raise NotFoundError("not_found", "unknown application")
    env = await session.scalar(stmt)
    if env is None:
        raise NotFoundError("not_found", "unknown application")
    return env
