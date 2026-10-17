"""magic_email share mode: token payload binds share+email, leaked URL
can only unlock that specific recipient's seat."""

import time
from unittest.mock import patch
from uuid import uuid4

import pytest
from itsdangerous.timed import TimestampSigner

from app import tokens
from app.routes.shares import _magic_payload, _parse_magic_payload


def test_magic_payload_roundtrip():
    sid = uuid4()
    payload = _magic_payload(sid, "alice@example.com")
    parsed_sid, parsed_email = _parse_magic_payload(payload)
    assert parsed_sid == sid
    assert parsed_email == "alice@example.com"


def test_magic_payload_lowercases_email():
    sid = uuid4()
    payload = _magic_payload(sid, "ALICE@Example.COM")
    _, email = _parse_magic_payload(payload)
    assert email == "alice@example.com"


def test_magic_token_signed_with_magic_link_purpose():
    sid = uuid4()
    t = tokens.issue("magic_link", _magic_payload(sid, "a@b.com"))
    parsed = tokens.verify("magic_link", t)
    parsed_sid, parsed_email = _parse_magic_payload(parsed)
    assert parsed_sid == sid
    assert parsed_email == "a@b.com"


def test_magic_token_cannot_be_used_as_invite():
    """Same itsdangerous secret but different purpose salt, so it must be rejected."""
    t = tokens.issue("magic_link", _magic_payload(uuid4(), "a@b.com"))
    with pytest.raises(tokens.TokenInvalid):
        tokens.verify("invite", t)


def test_magic_token_expires():
    with patch.dict(tokens.TTL, {"magic_link": 1}):
        t = tokens.issue("magic_link", _magic_payload(uuid4(), "a@b.com"))
        future = int(time.time()) + 5
        with patch.object(TimestampSigner, "get_timestamp", return_value=future):
            with pytest.raises(tokens.TokenExpired):
                tokens.verify("magic_link", t)


def test_payload_email_with_special_chars():
    """Email shouldn't contain '|' (our payload separator), but just in
    case parse should still split on first '|' only."""
    sid = uuid4()
    payload = f"{sid}|user+tag@example.com"
    parsed_sid, parsed_email = _parse_magic_payload(payload)
    assert parsed_sid == sid
    assert parsed_email == "user+tag@example.com"
