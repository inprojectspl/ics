"""Pydantic DTOs for auth endpoints."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app import passwords
from app.constants import ROLE_REGEX
from app.i18n import Locale


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str
    new_password: str = Field(min_length=passwords.MIN_LENGTH, max_length=512)


class SetupFromTokenIn(BaseModel):
    token: str
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=512)
    display_name: str | None = Field(default=None, max_length=255)


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(default="user", pattern=ROLE_REGEX)
    display_name: str | None = Field(default=None, max_length=255)


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=passwords.MIN_LENGTH, max_length=512)
    display_name: str | None = Field(default=None, max_length=255)


class MePatchIn(BaseModel):
    # Required: the only field today, and an empty body is more likely a
    # client bug than a request to change nothing.
    locale: Locale | None
