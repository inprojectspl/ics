import secrets

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/1/l/i/o for readability


def generate_slug(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def generate_token(byte_len: int = 32) -> str:
    return secrets.token_urlsafe(byte_len)
