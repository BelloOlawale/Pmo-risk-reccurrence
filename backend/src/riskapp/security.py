"""Password hashing for local (non-Entra) accounts.

Uses ``hashlib.scrypt`` from the standard library — no third-party crypto
dependency — with a per-password random salt. Stored format:

    scrypt$<n>$<r>$<p>$<base64 salt>$<base64 hash>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N = 2**14  # CPU/memory cost
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return a salted scrypt hash for ``password``."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN
    )
    return "scrypt${}${}${}${}${}".format(
        _N,
        _R,
        _P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check of ``password`` against a stored hash."""
    if not stored or not password:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n_s),
            r=int(r_s),
            p=int(p_s),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
