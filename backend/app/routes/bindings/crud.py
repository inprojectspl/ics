"""Binding CRUD and key rotation (owner or project owner only)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions, signing
from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.models import Asset, GitLabBinding, User
from app.services import notifications

from ._models import (
    BindingCreateOut,
    BindingOut,
    CreateBindingIn,
    PatchBindingIn,
    ProviderInfoOut,
)
from ._router import router


def _to_out(b: GitLabBinding) -> BindingOut:
    return BindingOut(
        id=str(b.id),
        asset_id=str(b.asset_id),
        gitlab_project_url=b.gitlab_project_url,
        webhook_url=b.webhook_url,
        provider=b.provider,
        public_key=b.public_key,
        last_sync_at=b.last_sync_at.isoformat() if b.last_sync_at else None,
        last_sync_commit_sha=b.last_sync_commit_sha,
        created_at=b.created_at.isoformat(),
    )


async def _binding_owner_asset(session: AsyncSession, asset_id: UUID, user: User) -> Asset:
    """The asset, if `user` may manage its bindings: the same owner or
    project owner rule as `permissions.get_owned_binding`."""
    asset, role = await permissions.get_asset_with_role(
        session, user=user, min_role="editor", asset_id=asset_id
    )
    if role not in ("owner_file", "project_owner"):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    return asset


def _key_tail(public_pem: str) -> str:
    """Last key characters of a PEM, for audit: enough to tell keys apart."""
    body = "".join(line for line in public_pem.splitlines() if not line.startswith("-----"))
    return body[-16:]


def _normalize_webhook_pair(
    provider: str | None,
    url: str | None,
) -> tuple[str | None, str | None]:
    """Treat an empty string as None (the UI sends "" after clearing the
    input). Returns the normalized pair after validation."""
    norm_url = url if url else None
    norm_provider = provider if provider else None
    if (norm_url is None) != (norm_provider is None):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "webhook_pair_incomplete",
            "provider and webhook_url must both be set or both be empty",
        )
    if norm_url is None or norm_provider is None:
        return None, None
    try:
        notifications.validate_provider_url(norm_provider, norm_url)
    except notifications.NotificationError as e:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_webhook", str(e)) from e
    return norm_provider, norm_url


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_binding(
    body: CreateBindingIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BindingCreateOut:
    asset = await _binding_owner_asset(session, body.asset_id, user)

    provider, webhook_url = _normalize_webhook_pair(body.provider, body.webhook_url)
    private_pem, public_pem = signing.generate_keypair()
    binding = GitLabBinding(
        asset_id=asset.id,
        gitlab_project_url=body.gitlab_project_url,
        webhook_url=webhook_url,
        provider=provider,
        public_key=public_pem,
        created_by=user.id,
    )
    session.add(binding)
    await session.flush()
    await audit.record(
        session,
        actor=user,
        action="binding_created",
        target=f"binding:{binding.id}",
        payload={
            "asset_id": str(asset.id),
            "has_gitlab_url": bool(body.gitlab_project_url),
            "has_webhook": bool(binding.webhook_url),
            "provider": binding.provider,
        },
    )
    await session.commit()
    out = _to_out(binding)
    return BindingCreateOut(**out.model_dump(), private_key=private_pem)


@router.get("/providers")
async def list_notification_providers(
    _user: CurrentUser,  # auth gate: providers are an implementation detail, not public.
) -> list[ProviderInfoOut]:
    """Provider list for the UI dropdown. Static (registered in
    `_providers/__init__.py`), so no I/O, only the membership gate."""
    return [
        ProviderInfoOut(
            id=str(info.id),
            display_name=info.display_name,
            url_hint=info.url_hint,
        )
        for info in notifications.list_provider_infos()
    ]


@router.get("/{binding_id}")
async def get_binding(
    binding_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BindingOut:
    binding = await permissions.get_owned_binding(session, binding_id, user)
    return _to_out(binding)


@router.get("")
async def list_bindings_for_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BindingOut]:
    asset = await _binding_owner_asset(session, asset_id, user)
    rows = (
        (
            await session.execute(
                select(GitLabBinding)
                .where(GitLabBinding.asset_id == asset.id)
                .order_by(GitLabBinding.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_to_out(b) for b in rows]


@router.patch("/{binding_id}")
async def patch_binding(
    binding_id: UUID,
    body: PatchBindingIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BindingOut:
    """Owner edits the GitLab project URL or the (provider, webhook_url) pair
    on an existing binding without rotating the key. webhook_url + provider
    must be patched together (both in the body or neither)."""
    binding = await permissions.get_owned_binding(session, binding_id, user)
    fields = body.model_fields_set
    changed: dict[str, bool] = {}
    if "gitlab_project_url" in fields:
        binding.gitlab_project_url = body.gitlab_project_url or None
        changed["gitlab_url"] = True
    webhook_in = "webhook_url" in fields
    provider_in = "provider" in fields
    if webhook_in or provider_in:
        if webhook_in != provider_in:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "webhook_pair_incomplete",
                "provider and webhook_url must be patched together",
            )
        provider, webhook_url = _normalize_webhook_pair(
            body.provider,
            body.webhook_url,
        )
        binding.provider = provider
        binding.webhook_url = webhook_url
        changed["webhook"] = True
    if changed:
        await audit.record(
            session,
            actor=user,
            action="binding_updated",
            target=f"binding:{binding.id}",
            payload=changed,
        )
        await session.commit()
        await session.refresh(binding)
    return _to_out(binding)


@router.post("/{binding_id}/rotate")
async def rotate_binding_key(
    binding_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BindingCreateOut:
    """Invalidates the old keypair and issues a new one. After rotation the
    GitLab CI's private key var must be updated; in-flight sync attempts
    signed by the old key are rejected immediately."""
    binding = await permissions.get_owned_binding(session, binding_id, user)
    private_pem, public_pem = signing.generate_keypair()
    old_tail = _key_tail(binding.public_key)
    binding.public_key = public_pem
    binding.last_sync_at = None
    binding.last_sync_commit_sha = None
    binding.last_sync_timestamp = None
    await audit.record(
        session,
        actor=user,
        action="binding_rotated",
        target=f"binding:{binding.id}",
        payload={"old_key_tail": old_tail, "new_key_tail": _key_tail(public_pem)},
    )
    await session.commit()
    out = _to_out(binding)
    return BindingCreateOut(**out.model_dump(), private_key=private_pem)


@router.delete("/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_binding(
    binding_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    binding = await permissions.get_owned_binding(session, binding_id, user)
    await audit.record(
        session,
        actor=user,
        action="binding_deleted",
        target=f"binding:{binding.id}",
        # The row is gone afterwards; the asset keeps the event readable.
        payload={"asset_id": str(binding.asset_id)},
    )
    await session.delete(binding)
    await session.commit()
