"""API errors shaped `{"detail": ..., "code": "..."}`.

Clients branch on and translate by `code`, never `detail` (English, for humans and
logs). Catalogue: `docs/api-errors.md`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain_errors import (
    AccessDeniedError,
    ConflictError,
    DomainError,
    InvalidInputError,
    LimitExceededError,
    NotFoundError,
)

VALIDATION_ERROR = "validation_error"

# Fallback for exceptions raised without a code: Starlette's own 404/405
# for unknown routes and HTTPExceptions from third-party dependencies.
_STATUS_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: VALIDATION_ERROR,
    429: "rate_limited",
    500: "server_error",
    503: "service_unavailable",
}

_NO_BODY_STATUSES = frozenset({204, 205, 304})


class ApiError(HTTPException):
    """HTTPException carrying a stable `code`. Raise this, not HTTPException."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: Any,
        headers: Mapping[str, str] | None = None,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code, detail, dict(headers) if headers else None)
        self.code = code
        # Additional top-level keys of the error body.
        self.extra = dict(extra) if extra else None


# Status code per domain error category; a subclass (e.g. QuotaExceededError)
# gets its category's status.
_DOMAIN_STATUS: dict[type[DomainError], int] = {
    InvalidInputError: 400,
    AccessDeniedError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    LimitExceededError: 413,
}


def domain_status(exc: DomainError) -> int:
    return next((s for cls, s in _DOMAIN_STATUS.items() if isinstance(exc, cls)), 400)


def error_code(exc: StarletteHTTPException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    default = "server_error" if exc.status_code >= 500 else "http_error"
    return _STATUS_CODES.get(exc.status_code, default)


def _no_store(response: Response) -> Response:
    # Browsers heuristically cache some error statuses (404, 410). A cached
    # 410 would keep masking a security bypass granted by an admin after it,
    # so no error response may be cached.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


def error_response(
    status_code: int,
    code: str,
    detail: Any,
    headers: Mapping[str, str] | None = None,
    *,
    field: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Response:
    """The error body every handler and middleware sends. `extra` adds keys
    but never replaces `detail`, `code` or `field`."""
    body: dict[str, Any] = {"detail": detail, "code": code}
    if field is not None:
        body["field"] = field
    for key, value in (extra or {}).items():
        body.setdefault(key, value)
    return _no_store(JSONResponse(body, status_code=status_code, headers=headers))


async def http_error_handler(_request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    headers = getattr(exc, "headers", None)
    if exc.status_code in _NO_BODY_STATUSES:
        return Response(status_code=exc.status_code, headers=headers)
    extra = getattr(exc, "extra", None)
    return error_response(exc.status_code, error_code(exc), exc.detail, headers, extra=extra)


async def domain_error_handler(_request: Request, exc: Exception) -> Response:
    assert isinstance(exc, DomainError)
    return error_response(
        domain_status(exc), exc.code, exc.detail, field=exc.field, extra=exc.extra
    )


async def validation_error_handler(_request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, VALIDATION_ERROR, jsonable_encoder(exc.errors()))
