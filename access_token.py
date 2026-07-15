"""Short, signed Telegram deep-link tokens bound to one user and course."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AccessGrant:
    user_id: int
    expires_at: int
    fingerprint: str


def _base36_encode(value: int) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    if value < 0:
        raise ValueError("value must be non-negative")
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = alphabet[remainder] + result
    return result


def _base36_decode(value: str) -> int:
    return int(value, 36)


def _signature(secret: str, course_code: str, body: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        f"v1:{course_code}:{body}".encode("utf-8"),
        hashlib.sha256,
    ).digest()[:12]
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _validate_secret(secret: str) -> None:
    if len(secret.encode("utf-8")) < 32:
        raise ValueError("ACCESS_TOKEN_SECRET must contain at least 32 bytes")


def create_access_token(
    user_id: int,
    course_code: str,
    secret: str,
    *,
    ttl_seconds: int = 7 * 24 * 60 * 60,
    now: int | None = None,
) -> str:
    _validate_secret(secret)
    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + ttl_seconds
    nonce = secrets.token_hex(3)
    body = "_".join(
        (_base36_encode(user_id), _base36_encode(expires_at), nonce)
    )
    token = f"{body}_{_signature(secret, course_code, body)}"
    if len(f"access_{token}") > 64:
        raise ValueError("generated token is too long for a Telegram deep link")
    return token


def validate_access_token(
    token: str,
    expected_user_id: int,
    course_code: str,
    secret: str,
    *,
    now: int | None = None,
) -> AccessGrant | None:
    try:
        _validate_secret(secret)
        user_raw, expires_raw, nonce, supplied_signature = token.split("_", 3)
        user_id = _base36_decode(user_raw)
        expires_at = _base36_decode(expires_raw)
        if not nonce or user_id != expected_user_id:
            return None
        body = f"{user_raw}_{expires_raw}_{nonce}"
        expected_signature = _signature(secret, course_code, body)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        current_time = int(time.time() if now is None else now)
        if expires_at < current_time:
            return None
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return AccessGrant(user_id=user_id, expires_at=expires_at, fingerprint=fingerprint)
    except (TypeError, ValueError):
        return None
