import time
from unittest.mock import patch

import pytest
from itsdangerous.timed import TimestampSigner

from app import tokens


def test_issue_and_verify_roundtrip():
    t = tokens.issue("invite", "user-id-123")
    assert tokens.verify("invite", t) == "user-id-123"


def test_purpose_mismatch_rejected():
    t = tokens.issue("invite", "user-id-123")
    with pytest.raises(tokens.TokenInvalid):
        tokens.verify("reset", t)


def test_tampered_token_rejected():
    t = tokens.issue("invite", "user-id-123")
    tampered = t[:-2] + ("AA" if t[-2:] != "AA" else "BB")
    with pytest.raises(tokens.TokenInvalid):
        tokens.verify("invite", tampered)


def test_unknown_purpose_raises():
    with pytest.raises(ValueError):
        tokens.issue("unknown", "x")


def test_expired_token_rejected():
    # Patch TTL=1s; simulate elapsed time by mocking `get_timestamp` on the
    # itsdangerous signer instead of waiting with `time.sleep(2)`.
    with patch.dict(tokens.TTL, {"reset": 1}):
        t = tokens.issue("reset", "user-id-123")
        future = int(time.time()) + 5
        with patch.object(TimestampSigner, "get_timestamp", return_value=future):
            with pytest.raises(tokens.TokenExpired):
                tokens.verify("reset", t)
