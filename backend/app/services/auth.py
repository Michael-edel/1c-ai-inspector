"""Minimal signed bearer tokens for local server-side identity enforcement."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass


class AuthError(ValueError):
    """Raised when a signed inspector token is invalid or expired."""


@dataclass(frozen=True)
class AuthContext:
    subject: str
    role: str
    expires_at: int


def issue_auth_token(subject: str, role: str, secret: str, ttl_seconds: int = 3600) -> str:
    if len(secret) < 32:
        raise AuthError("AUTH_SECRET_TOO_SHORT")
    if not subject or role not in {"reviewer", "maintainer", "owner"}:
        raise AuthError("AUTH_CLAIMS_INVALID")
    now = int(time.time())
    payload = {"sub": subject, "role": role, "iat": now, "exp": now + ttl_seconds}
    encoded = _encode(json.dumps(payload, separators=(",", ":")))
    return f"{encoded}.{_signature(encoded, secret)}"


def verify_auth_token(token: str, secret: str, now: int | None = None) -> AuthContext:
    if len(secret) < 32:
        raise AuthError("AUTH_SECRET_TOO_SHORT")
    parts = token.split(".")
    if len(parts) != 2 or not hmac.compare_digest(parts[1], _signature(parts[0], secret)):
        raise AuthError("AUTH_TOKEN_INVALID")
    try:
        payload = json.loads(_decode(parts[0]))
        subject = str(payload["sub"])
        role = str(payload["role"])
        expires_at = int(payload["exp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthError("AUTH_TOKEN_INVALID") from exc
    if not subject or role not in {"reviewer", "maintainer", "owner"}:
        raise AuthError("AUTH_CLAIMS_INVALID")
    if expires_at <= int(time.time() if now is None else now):
        raise AuthError("AUTH_TOKEN_EXPIRED")
    return AuthContext(subject=subject, role=role, expires_at=expires_at)


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(value: str) -> str:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")


def _signature(value: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("ascii"), hashlib.sha256).hexdigest()
