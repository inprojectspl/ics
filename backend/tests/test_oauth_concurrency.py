"""One-time OAuth credentials stay one-time when two requests race: each runs in
its own database session, as two server workers would."""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.errors import ApiError
from app.models import OAuthRefreshToken
from app.oauth.server.token import _grant_authorization_code, _grant_refresh
from tests.conftest import (
    do_authorize_get_code,
    full_oauth_flow,
    make_pkce,
    resource_uri,
    signed_in_oauth_client,
)


async def _race(grant, form):
    """Run `grant` twice at once in separate sessions; return both outcomes."""
    engine = create_async_engine(get_settings().database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt():
        async with factory() as session:
            return await grant(form, get_settings(), session)

    try:
        return await asyncio.gather(attempt(), attempt(), return_exceptions=True)
    finally:
        await engine.dispose()


def _outcomes(results):
    granted = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, ApiError)]
    return granted, refused


@pytest.mark.asyncio
async def test_concurrent_refresh_leaves_no_two_live_successors(client, session):
    dcr = await signed_in_oauth_client(client, session)
    body = await full_oauth_flow(client, dcr["client_id"])

    results = await _race(
        _grant_refresh,
        {
            "grant_type": "refresh_token",
            "refresh_token": body["refresh_token"],
            "client_id": dcr["client_id"],
        },
    )

    granted, refused = _outcomes(results)
    assert len(granted) == 1 and len(refused) == 1, results
    # The loser looks like reuse, so the whole family is revoked: no token of
    # this grant can be refreshed any more.
    live = await session.scalar(
        select(func.count())
        .select_from(OAuthRefreshToken)
        .where(OAuthRefreshToken.revoked_at.is_(None))
    )
    assert live == 0


@pytest.mark.asyncio
async def test_concurrent_code_exchange_issues_tokens_once(client, session):
    dcr = await signed_in_oauth_client(client, session)
    verifier, challenge = make_pkce()
    code = await do_authorize_get_code(client, dcr["client_id"], challenge)

    results = await _race(
        _grant_authorization_code,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9000/callback",
            "code_verifier": verifier,
            "client_id": dcr["client_id"],
            "resource": resource_uri(),
        },
    )

    granted, refused = _outcomes(results)
    assert len(granted) == 1 and len(refused) == 1, results
    assert refused[0].code == "invalid_grant"
