"""Google OIDC via Authlib.

The registry is built lazily so test fixtures and env overrides apply first.
Endpoints gate on `require_google_oidc`, so missing credentials give a 503
instead of `AttributeError: 'OAuth' has no 'google'`.
"""

from functools import lru_cache

from authlib.integrations.starlette_client import OAuth

from app.config import get_settings


@lru_cache
def get_oauth() -> OAuth:
    settings = get_settings()
    oauth = OAuth()
    if settings.google_oidc_client_id:
        oauth.register(
            name="google",
            client_id=settings.google_oidc_client_id,
            client_secret=settings.google_oidc_client_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth
