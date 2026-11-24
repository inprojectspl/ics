"""Google OAuth and the Sheets API, over plain HTTP.

Every call has a deadline and maps Google's answer to a `GoogleError` code
the API can show. `sent` tells whether a mutation may have reached Google:
a write that failed with `sent=True` has an unknown outcome and is never
repeated blindly (ADR-0031).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from app.config import Settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SCOPES = f"openid email {SHEETS_SCOPE}"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)

# Tests replace it with an `httpx.MockTransport`.
transport: httpx.AsyncBaseTransport | None = None


class GoogleError(Exception):
    def __init__(self, code: str, detail: str, *, status: int = 0, sent: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status
        self.sent = sent

    @property
    def retryable(self) -> bool:
        return self.code in ("google_rate_limited", "google_unavailable")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=transport)


def redirect_uri(settings: Settings) -> str:
    return (
        settings.google_sheets_redirect_uri
        or f"{settings.base_url.rstrip('/')}/api/integrations/google/callback"
    )


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


def authorize_url(settings: Settings, *, state: str, challenge: str, login_hint: str) -> str:
    params = {
        "client_id": settings.google_sheets_client_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # A refresh token on every consent, so a reconnect replaces a revoked one.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
        "login_hint": login_hint,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _error(resp: httpx.Response, *, sent: bool) -> GoogleError:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    err = body.get("error")
    message = (err.get("message") if isinstance(err, dict) else body.get("error_description")) or ""
    status = resp.status_code
    if status == 401 or err == "invalid_grant":
        return GoogleError(
            "google_grant_invalid", "the Google grant was revoked or expired", status=status
        )
    if status == 403:
        return GoogleError(
            "google_no_access", "the Google account has no access to the spreadsheet", status=status
        )
    if status == 404:
        return GoogleError("google_not_found", "the spreadsheet does not exist", status=status)
    if status == 429:
        return GoogleError("google_rate_limited", "Google rate limit", status=status)
    if status == 400 and "Office file" in message:
        # An .xlsx kept on Drive: the Sheets API reads only native spreadsheets.
        return GoogleError(
            "google_office_file",
            "the file is an Office (Excel) file, not a Google spreadsheet",
            status=status,
        )
    if status >= 500:
        # A 5xx after a mutation was sent leaves its outcome unknown.
        return GoogleError("google_unavailable", "Google is unavailable", status=status, sent=sent)
    return GoogleError(
        "google_rejected", message[:200] or "Google rejected the request", status=status
    )


async def _request(
    method: str,
    url: str,
    *,
    mutation: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    try:
        async with _client() as client:
            resp = await client.request(method, url, **kwargs)
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        # Nothing reached Google.
        raise GoogleError("google_unavailable", "Google is unreachable") from e
    except httpx.HTTPError as e:
        raise GoogleError("google_unavailable", "no answer from Google", sent=mutation) from e
    if resp.status_code >= 400:
        raise _error(resp, sent=mutation)
    if not resp.content:
        return {}
    result: dict[str, Any] = resp.json()
    return result


async def exchange_code(settings: Settings, code: str, verifier: str) -> dict[str, Any]:
    return await _request(
        "POST",
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_sheets_client_id,
            "client_secret": settings.google_sheets_client_secret,
            "redirect_uri": redirect_uri(settings),
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )


async def refresh(settings: Settings, refresh_token: str) -> dict[str, Any]:
    return await _request(
        "POST",
        TOKEN_URL,
        data={
            "client_id": settings.google_sheets_client_id,
            "client_secret": settings.google_sheets_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )


async def revoke(token: str) -> None:
    await _request("POST", REVOKE_URL, data={"token": token})


async def userinfo(access_token: str) -> dict[str, Any]:
    return await _request("GET", USERINFO_URL, headers=_auth(access_token))


def _auth(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def spreadsheet_meta(access_token: str, spreadsheet_id: str) -> dict[str, Any]:
    """Title, time zone and every tab with its id and grid size."""
    return await _request(
        "GET",
        f"{SHEETS_URL}/{quote(spreadsheet_id, safe='')}",
        headers=_auth(access_token),
        params={
            "fields": "properties(title,timeZone),sheets(properties(sheetId,title,gridProperties))"
        },
    )


def a1_tab(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


async def batch_update(
    access_token: str, spreadsheet_id: str, requests: list[dict[str, Any]]
) -> dict[str, Any]:
    """One `spreadsheets.batchUpdate`: Google applies all requests or none."""
    return await _request(
        "POST",
        f"{SHEETS_URL}/{quote(spreadsheet_id, safe='')}:batchUpdate",
        headers=_auth(access_token),
        json={"requests": requests},
        mutation=True,
    )


async def _batch_get(
    access_token: str, spreadsheet_id: str, ranges: list[str], major: str
) -> list[list[Any]]:
    """The first row (ROWS) or column (COLUMNS) of each A1 range, raw:
    numbers as numbers, dates as serial numbers, no formatting, so what is
    compared does not depend on the sheet's locale. One call for all."""
    body = await _request(
        "GET",
        f"{SHEETS_URL}/{quote(spreadsheet_id, safe='')}/values:batchGet",
        headers=_auth(access_token),
        params=[
            ("valueRenderOption", "UNFORMATTED_VALUE"),
            ("dateTimeRenderOption", "SERIAL_NUMBER"),
            ("majorDimension", major),
            *(("ranges", r) for r in ranges),
        ],
    )
    return [(vr.get("values") or [[]])[0] for vr in body.get("valueRanges", [])]


async def read_columns(
    access_token: str, spreadsheet_id: str, ranges: list[str]
) -> list[list[Any]]:
    """Each A1 range (one column) as a list of values, top to bottom."""
    return await _batch_get(access_token, spreadsheet_id, ranges, "COLUMNS")


async def read_header_rows(
    access_token: str, spreadsheet_id: str, ranges: list[str]
) -> list[list[Any]]:
    """The first row of each A1 range."""
    return await _batch_get(access_token, spreadsheet_id, ranges, "ROWS")


async def grid(access_token: str, spreadsheet_id: str, range_a1: str) -> dict[str, Any]:
    """The cells of a range with their typed value and number format, so the
    kind of a column (date, number, text) can be told without the locale."""
    return await _request(
        "GET",
        f"{SHEETS_URL}/{quote(spreadsheet_id, safe='')}",
        headers=_auth(access_token),
        params={
            "ranges": range_a1,
            "includeGridData": "true",
            "fields": "properties(title,timeZone),"
            "sheets(properties(title),data(rowData(values(effectiveValue,"
            "effectiveFormat/numberFormat/type,formattedValue,userEnteredValue/formulaValue))))",
        },
    )
