"""Production safety: refuse to instantiate Settings with the public
default secret_key unless `debug=True`.

The guard prevents the most expensive deployment mistake: forgetting to
override `ICS_SECRET_KEY`. Tokens signed with the public default would
be forgeable by anyone with read access to this repo.
"""

import pytest

from app.config import Settings


def test_default_secret_in_dev_mode_passes(monkeypatch):
    """debug=True (the dev compose default) keeps the built-in default, so
    tests can instantiate Settings without a custom secret in their env."""
    monkeypatch.delenv("ICS_SECRET_KEY", raising=False)
    s = Settings(debug=True)
    assert s.secret_key == "dev-secret-change-me"


def test_default_secret_in_prod_mode_refuses(monkeypatch):
    monkeypatch.delenv("ICS_SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="ICS_SECRET_KEY"):
        Settings(debug=False)


def test_custom_secret_in_prod_mode_passes():
    s = Settings(debug=False, secret_key="some-random-hex-value-from-openssl")
    assert s.secret_key == "some-random-hex-value-from-openssl"


def test_cors_origins_csv_parsed():
    s = Settings(debug=True, cors_origins="https://a.test, https://b.test")
    assert s.cors_origins_list == ["https://a.test", "https://b.test"]


def test_dev_stub_sso_in_prod_mode_refuses():
    with pytest.raises(ValueError, match="ICS_DEV_STUB_SSO"):
        Settings(debug=False, secret_key="some-random-hex-value", dev_stub_sso=True)


def test_dev_stub_sso_in_dev_mode_passes():
    s = Settings(debug=True, dev_stub_sso=True)
    assert s.dev_stub_sso is True
