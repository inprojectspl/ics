from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Length is the only rule, no composition rules (ADR-0007).
MIN_LENGTH = 8

_hasher = PasswordHasher(memory_cost=64 * 1024, time_cost=3, parallelism=1)


class WeakPasswordError(ValueError):
    pass


def validate_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_LENGTH} characters long")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False


def needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)
