import pytest
from argon2 import PasswordHasher

from backend.auth.passwords import (
    hash_password,
    password_needs_rehash,
    verify_password,
)


def test_salted_hashes_verify_without_storing_plaintext():
    password = "a long example password"
    first = hash_password(password)
    second = hash_password(password)
    assert first.startswith("$argon2id$")
    assert first != second
    assert password not in first
    assert verify_password(password, first)
    assert verify_password(password, second)
    assert not verify_password("wrong password", first)
    assert not password_needs_rehash(first)


def test_whitespace_and_unicode_are_preserved():
    password = "  café 密碼  "
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password(password.strip(), hashed)
    assert not verify_password("  cafe 密碼  ", hashed)


@pytest.mark.parametrize("stored_hash", ["", "not-a-hash", "$argon2id$broken"])
def test_malformed_stored_hash_is_rejected(stored_hash):
    assert not verify_password("password", stored_hash)


@pytest.mark.parametrize("password", ["", "a" * 1025, "é" * 513])
def test_invalid_size_is_rejected_without_truncation(password):
    with pytest.raises(ValueError):
        hash_password(password)
    assert not verify_password(password, "not-a-hash")


def test_maximum_utf8_length_is_accepted():
    password = "é" * 512
    assert verify_password(password, hash_password(password))


def test_older_parameters_can_be_verified_and_flagged_for_rehash():
    old_hash = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(
        "example password"
    )
    assert verify_password("example password", old_hash)
    assert password_needs_rehash(old_hash)
