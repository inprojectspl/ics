"""Domain exceptions for code outside the HTTP layer, usable without FastAPI.

Each carries the API's stable `code` and English `detail`; `app.errors` maps the
category to a status code (see `docs/api-errors.md`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DomainError(Exception):
    """Base class: a business rule refused the operation."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        field: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        # Input field the error is about; sent as `field` in the error body.
        self.field = field
        # Additional top-level keys of the error body (e.g. the valid choices),
        # so a client can recover without another request.
        self.extra = dict(extra) if extra else None


class InvalidInputError(DomainError):
    """The input breaks a rule of the domain (bad path, wrong asset kind)."""


class AccessDeniedError(DomainError):
    """The caller is known to have access but lacks the required role."""


class NotFoundError(DomainError):
    """The object does not exist or the caller may not learn that it does."""


class ConflictError(DomainError):
    """The operation clashes with the current state (e.g. file exists)."""


class LimitExceededError(DomainError):
    """A size, count or quota limit would be exceeded."""
