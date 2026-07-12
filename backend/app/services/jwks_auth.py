"""JWT validation against an external issuer's JSON Web Key Set."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.auth import AuthContext, AuthError


class JwksAuthError(AuthError):
    """Raised when an external JWT cannot be accepted."""


class JwksUnavailableError(JwksAuthError):
    """Raised when the configured issuer keys cannot be loaded."""


@dataclass
class JwksProvider:
    url: str
    ttl_seconds: int
    client: httpx.AsyncClient | None = None

    def __post_init__(self) -> None:
        self._keys: dict[str, dict[str, Any]] = {}
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_keys(self, force_refresh: bool = False) -> dict[str, dict[str, Any]]:
        if not force_refresh and self._keys and self._expires_at > time.monotonic():
            return self._keys
        async with self._lock:
            if not force_refresh and self._keys and self._expires_at > time.monotonic():
                return self._keys
            try:
                if self.client is not None:
                    response = await self.client.get(self.url)
                    response.raise_for_status()
                    body = response.json()
                else:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.get(self.url)
                        response.raise_for_status()
                        body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise JwksUnavailableError("AUTH_JWKS_UNAVAILABLE") from exc
            if not isinstance(body, dict):
                raise JwksUnavailableError("AUTH_JWKS_INVALID")
            keys = {
                str(key["kid"]): key
                for key in body.get("keys", [])
                if isinstance(key, dict) and key.get("kid")
            }
            if not keys:
                raise JwksUnavailableError("AUTH_JWKS_EMPTY")
            self._keys = keys
            self._expires_at = time.monotonic() + self.ttl_seconds
            return keys


async def verify_jwks_token(
    token: str,
    provider: JwksProvider,
    *,
    issuer: str | None,
    audience: str | None,
    roles_claim: str,
    subject_claim: str,
) -> AuthContext:
    try:
        import jwt

        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        algorithm = header.get("alg")
        if not key_id or algorithm not in {"RS256", "RS384", "RS512"}:
            raise JwksAuthError("AUTH_TOKEN_INVALID")
        keys = await provider.get_keys()
        jwk = keys.get(str(key_id))
        if jwk is None:
            jwk = (await provider.get_keys(force_refresh=True)).get(str(key_id))
        if jwk is None or jwk.get("kty") != "RSA":
            raise JwksAuthError("AUTH_TOKEN_INVALID")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        decode_kwargs: dict[str, Any] = {
            "algorithms": [algorithm],
            "options": {"require": ["exp", subject_claim]},
        }
        if issuer:
            decode_kwargs["issuer"] = issuer
        if audience:
            decode_kwargs["audience"] = audience
        elif "aud" in jwt.decode(token, options={"verify_signature": False}):
            decode_kwargs["options"]["verify_aud"] = False
        payload = jwt.decode(token, public_key, **decode_kwargs)
    except JwksAuthError:
        raise
    except (jwt.exceptions.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise JwksAuthError("AUTH_TOKEN_INVALID") from exc

    subject = str(payload.get(subject_claim, ""))
    roles = _read_claim(payload, roles_claim)
    if isinstance(roles, str):
        accepted_roles = {roles}
    elif isinstance(roles, list):
        accepted_roles = {str(role) for role in roles}
    else:
        accepted_roles = set()
    role = next((candidate for candidate in ("owner", "maintainer", "reviewer") if candidate in accepted_roles), None)
    if not subject or role is None:
        raise JwksAuthError("AUTH_CLAIMS_INVALID")
    return AuthContext(
        subject=subject,
        role=role,
        expires_at=int(payload["exp"]),
        auth_source="jwks",
    )


def _read_claim(payload: dict[str, Any], claim: str) -> Any:
    value: Any = payload
    for part in claim.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
