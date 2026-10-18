"""Password hashing (PBKDF2-SHA256, stdlib) and opaque session tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from .errors import ValidationFailed

_ALGO = "pbkdf2_sha256"


def hash_password(password: str, iterations: int) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join([_ALGO, str(iterations), base64.b64encode(salt).decode(), base64.b64encode(dk).decode()])


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def unusable_password() -> str:
    """A hash no password can match; used for accounts awaiting an initial password."""
    return "!" + secrets.token_hex(16)


def validate_password_strength(password: str) -> None:
    if len(password) < 8 or len(password) > 64:
        raise ValidationFailed("密码长度需为 8-64 位", code="WEAK_PASSWORD")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValidationFailed("密码需同时包含字母和数字", code="WEAK_PASSWORD")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return phone
    if len(phone) < 7:
        return "***"
    return phone[:3] + "****" + phone[-4:]


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    return (name[:1] + "***@" + domain) if name else "***@" + domain
