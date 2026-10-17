"""Ed25519 signing primitives: round-trip and tamper rejection.

These are the building blocks for GitLab binding signed-sync. A bug here
would let an attacker push arbitrary content into someone else's asset,
so the test matrix is intentionally thorough.
"""

import pytest

from app import signing


def test_keypair_pem_format():
    sk, pk = signing.generate_keypair()
    assert sk.startswith("-----BEGIN PRIVATE KEY-----")  # gitleaks:allow (PEM header only)
    assert sk.rstrip().endswith("-----END PRIVATE KEY-----")
    assert pk.startswith("-----BEGIN PUBLIC KEY-----")
    assert pk.rstrip().endswith("-----END PUBLIC KEY-----")


def test_keypair_is_fresh_per_call():
    sk1, _ = signing.generate_keypair()
    sk2, _ = signing.generate_keypair()
    assert sk1 != sk2


def test_sign_verify_roundtrip():
    sk, pk = signing.generate_keypair()
    sig = signing.sign(b"hello world", sk)
    assert signing.verify(b"hello world", sig, pk)


def test_signature_is_url_safe_base64():
    sk, _ = signing.generate_keypair()
    sig = signing.sign(b"x", sk)
    assert all(c.isalnum() or c in "-_" for c in sig)


def test_verify_rejects_tampered_message():
    sk, pk = signing.generate_keypair()
    sig = signing.sign(b"original message", sk)
    assert not signing.verify(b"tampered message", sig, pk)


def test_verify_rejects_tampered_signature():
    sk, pk = signing.generate_keypair()
    sig = signing.sign(b"msg", sk)
    tampered = sig[:-3] + ("AAA" if not sig.endswith("AAA") else "BBB")
    assert not signing.verify(b"msg", tampered, pk)


def test_verify_rejects_wrong_public_key():
    sk_a, _ = signing.generate_keypair()
    _, pk_b = signing.generate_keypair()
    sig = signing.sign(b"msg", sk_a)
    assert not signing.verify(b"msg", sig, pk_b)


def test_verify_rejects_garbage_signature():
    _, pk = signing.generate_keypair()
    assert not signing.verify(b"msg", "not-a-real-signature", pk)
    assert not signing.verify(b"msg", "", pk)


def test_verify_rejects_malformed_public_key():
    sk, _ = signing.generate_keypair()
    sig = signing.sign(b"msg", sk)
    assert not signing.verify(b"msg", sig, "not a real pem")


def test_sign_rejects_non_ed25519_key():
    """Defensive: if someone hands us an RSA key it shouldn't silently work."""
    rsa_pem = (
        # Truncated, not a usable key.
        "-----BEGIN PRIVATE KEY-----\n"  # gitleaks:allow
        "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ==\n"
        "-----END PRIVATE KEY-----\n"
    )
    with pytest.raises(Exception):  # noqa: B017 - cross-error catch is intentional
        signing.sign(b"msg", rsa_pem)


def test_verify_empty_message():
    sk, pk = signing.generate_keypair()
    sig = signing.sign(b"", sk)
    assert signing.verify(b"", sig, pk)
    assert not signing.verify(b"\x00", sig, pk)
