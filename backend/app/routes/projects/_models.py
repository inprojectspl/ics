"""Pydantic request DTOs for project endpoints."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field


def _strip_nonblank(v: str) -> str:
    """Trim a name and reject whitespace-only input with a 422, which
    `Field(min_length=1)` alone lets through."""
    v = v.strip()
    if not v:
        raise ValueError("name must not be blank")
    return v


# Single source of the project-name rule, shared by create + patch DTOs.
ProjectName = Annotated[str, Field(max_length=255), AfterValidator(_strip_nonblank)]


class CreateProjectIn(BaseModel):
    name: ProjectName
    description: str | None = Field(default=None, max_length=4000)


class PatchProjectIn(BaseModel):
    name: ProjectName | None = None
    description: str | None = Field(default=None, max_length=4000)


class InviteMemberIn(BaseModel):
    email: EmailStr
    role: Literal["editor", "viewer"]


class PatchMemberIn(BaseModel):
    role: Literal["editor", "viewer"]


class TransferOwnerIn(BaseModel):
    user_id: UUID


class AcceptInviteIn(BaseModel):
    token: str
