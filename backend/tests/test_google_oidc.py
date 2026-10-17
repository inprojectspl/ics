"""Google OIDC: structural tests.

Full e2e requires real Google credentials and an external redirect, so
these focus on what we control:
- Authlib register shape still works (catches version drift)
- get_oauth() skips Google registration when creds aren't set
"""

from app.config import get_settings


def test_authlib_in_deps():
    """If the import shape changes between Authlib versions we want to
    catch it at test time, not at first real login."""
    from authlib.integrations.starlette_client import OAuth

    o = OAuth()
    o.register(
        name="dummy",
        client_id="x",
        client_secret="y",
        server_metadata_url="https://example.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email"},
    )
    assert o.dummy is not None


def test_get_oauth_skips_register_without_creds():
    """Without creds set, get_oauth() returns an OAuth() with no 'google'
    client, so endpoints gated by require_google_oidc surface 503 instead
    of crashing on AttributeError."""
    from app import oauth as oauth_module

    oauth_module.get_oauth.cache_clear()
    if not get_settings().google_oidc_client_id:
        oauth = oauth_module.get_oauth()
        assert "google" not in oauth._registry


def test_get_oauth_registers_google_when_creds_set(monkeypatch):
    """`get_oauth()` should register the google client when creds are set."""
    from app import oauth as oauth_module
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "google_oidc_client_id", "test-id.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_oidc_client_secret", "test-secret")
    oauth_module.get_oauth.cache_clear()

    o = oauth_module.get_oauth()
    assert "google" in o._registry

    # Cleanup: clear the cache so other tests are not polluted.
    oauth_module.get_oauth.cache_clear()
