"""Passwords, session tokens and the password policy.

Passwords are hashed with argon2id. Session and CSRF tokens are 32 random bytes;
only the SHA-256 of a session token is stored, so a copy of the database cannot
be used to sign in.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256  # hashing very long inputs is a cheap denial of service
MIN_DISTINCT_CHARACTERS = 5

COMMON_PASSWORDS_FILE = Path(__file__).resolve().parent / "common_passwords.txt"

_hasher = PasswordHasher(type=Type.ID)
_TRAILING_DECORATION = re.compile(r"[\d\W_]{1,4}$")


def hash_password(pw: str) -> str:
    return _hasher.hash(pw)


def verify_password(hash: str, pw: str) -> bool:  # noqa: A002 - name fixed by the plan
    """True when ``pw`` matches ``hash``; False for a mismatch or an unreadable hash."""
    if not hash:
        return False
    try:
        return _hasher.verify(hash, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hash: str) -> bool:  # noqa: A002
    """True when ``hash`` was made with weaker parameters than today's."""
    try:
        return _hasher.check_needs_rehash(hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    with COMMON_PASSWORDS_FILE.open(encoding="utf-8") as fh:
        return frozenset(line.strip().lower() for line in fh if line.strip() and not line.startswith("#"))


def check_password_policy(pw: str) -> list[str]:
    """Problems with ``pw`` as a new password; an empty list means it is acceptable."""
    problems: list[str] = []
    if len(pw) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(pw) > MAX_PASSWORD_LENGTH:
        problems.append(f"Use at most {MAX_PASSWORD_LENGTH} characters.")
    lowered = pw.lower()
    common = common_passwords()
    base = _TRAILING_DECORATION.sub("", lowered)
    if lowered in common or (len(base) >= 4 and base in common):
        problems.append("This password is too common. Choose one that is hard to guess.")
    elif len(set(lowered)) < MIN_DISTINCT_CHARACTERS:
        problems.append(f"Use at least {MIN_DISTINCT_CHARACTERS} different characters.")
    return problems


def new_token() -> str:
    """32 random bytes, URL-safe base64."""
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    """SHA-256 hex of a token: what the database stores instead of the token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str | None, b: str | None) -> bool:
    """Constant-time comparison; False when either is missing."""
    if not a or not b:
        return False
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
