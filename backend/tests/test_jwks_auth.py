import asyncio
import base64

import httpx
import pytest

from app.services.jwks_auth import JwksProvider, JwksAuthError, verify_jwks_token


def _base64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_jwks_token_validates_issuer_audience_and_roles() -> None:
    jwt = pytest.importorskip("jwt")
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "test-key",
        "alg": "RS256",
        "n": _base64url(public_numbers.n),
        "e": _base64url(public_numbers.e),
    }
    token = jwt.encode(
        {"sub": "idp-user", "roles": ["maintainer"], "iss": "https://issuer.test", "aud": "inspector", "exp": 4_000_000_000},
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )

    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": [jwk]}))
        async with httpx.AsyncClient(transport=transport) as client:
            provider = JwksProvider("https://issuer.test/.well-known/jwks.json", 300, client)
            identity = await verify_jwks_token(
                token,
                provider,
                issuer="https://issuer.test",
                audience="inspector",
                roles_claim="roles",
                subject_claim="sub",
            )
            assert identity.subject == "idp-user"
            assert identity.role == "maintainer"
            assert identity.auth_source == "jwks"

    asyncio.run(scenario())


def test_jwks_token_rejects_unknown_key() -> None:
    jwt = pytest.importorskip("jwt")
    rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    token = jwt.encode(
        {"sub": "idp-user", "roles": ["reviewer"], "exp": 4_000_000_000},
        private_key,
        algorithm="RS256",
        headers={"kid": "missing-key"},
    )

    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"keys": []}))
        async with httpx.AsyncClient(transport=transport) as client:
            provider = JwksProvider("https://issuer.test/jwks", 300, client)
            with pytest.raises(JwksAuthError, match="AUTH_JWKS_EMPTY"):
                await verify_jwks_token(
                    token,
                    provider,
                    issuer=None,
                    audience=None,
                    roles_claim="roles",
                    subject_claim="sub",
                )

    asyncio.run(scenario())
