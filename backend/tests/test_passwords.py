import pytest

from app import passwords


def test_validate_rejects_shorter_than_minimum():
    with pytest.raises(passwords.WeakPasswordError):
        passwords.validate_password("short")


def test_validate_accepts_exactly_the_minimum():
    passwords.validate_password("a" * passwords.MIN_LENGTH)


def test_validate_accepts_simple_password_of_one_class():
    """The policy is lenient: strength depends on length, not composition.

    A "3 of 4 categories" rule pushes people into short substitutions like
    "Password2026!" and rejects long passphrases, which are harder to guess.
    The strength meter in the UI informs but does not block."""
    passwords.validate_password("lowercase")
    passwords.validate_password("alllowercaseletters")


def test_validate_accepts_passphrase():
    passwords.validate_password("cup of tea on the windowsill")


def test_hash_and_verify_roundtrip():
    h = passwords.hash_password("CorrectHorse9!Battery")
    assert passwords.verify_password("CorrectHorse9!Battery", h)
    assert not passwords.verify_password("wrong-password-here-1A", h)


def test_hash_is_not_plaintext():
    h = passwords.hash_password("CorrectHorse9!Battery")
    assert "CorrectHorse" not in h
    assert h.startswith("$argon2")
