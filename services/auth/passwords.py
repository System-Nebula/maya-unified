"""Argon2 password hashing for operator accounts."""

from __future__ import annotations

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _hasher = PasswordHasher()

    def hash_password(password: str) -> str:
        return _hasher.hash(password)

    def verify_password(password_hash: str, password: str) -> bool:
        try:
            return _hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False

except ImportError:  # fallback — should not happen in production
    import hashlib
    import hmac
    import os as _os

    def hash_password(password: str) -> str:  # type: ignore[misc]
        salt = _os.urandom(16).hex()
        digest = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
        return f"sha256:{salt}:{digest}"

    def verify_password(password_hash: str, password: str) -> bool:  # type: ignore[misc]
        if not password_hash.startswith("sha256:"):
            return False
        _, salt, stored = password_hash.split(":", 2)
        digest = hmac.new(salt.encode(), password.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, stored)
