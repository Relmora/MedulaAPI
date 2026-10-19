"""Password hashing only; account policy and login flows live in services."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

# Explicit Argon2id profile: 64 MiB memory, 3 iterations, 4 lanes.
# Benchmark concurrent logins on deployment hardware before release.
_hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
MAX_PASSWORD_BYTES = 1024


def _valid_size(password: str) -> bool:
    return 0 < len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES


def hash_password(password: str) -> str:
    """Hash exact input with a fresh library-generated salt; never trim it."""
    if not _valid_size(password):
        raise ValueError("Password must contain between 1 and 1024 UTF-8 bytes.")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Reject wrong passwords and malformed stored hashes without exposing them."""
    if not _valid_size(password):
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Call only after successful verification to detect outdated parameters."""
    return _hasher.check_needs_rehash(password_hash)
