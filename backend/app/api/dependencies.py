from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth import AuthContext, AuthError, verify_auth_token_with_rotation
from app.services.jwks_auth import JwksAuthError, JwksUnavailableError, verify_jwks_token

bearer_scheme = HTTPBearer(auto_error=False)


async def require_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        settings = request.app.state.settings
        if settings.inspector_auth_mode == "signed":
            if not settings.inspector_auth_secret:
                raise HTTPException(status_code=503, detail="AUTH_NOT_CONFIGURED")
            return verify_auth_token_with_rotation(
                credentials.credentials,
                settings.inspector_auth_secret,
                settings.inspector_auth_secret_previous,
                settings.inspector_auth_secret_previous_until,
            )
        if not settings.auth_jwks_url:
            raise HTTPException(status_code=503, detail="AUTH_JWKS_NOT_CONFIGURED")
        return await verify_jwks_token(
            credentials.credentials,
            request.app.state.jwks_provider,
            issuer=settings.auth_issuer,
            audience=settings.auth_audience,
            roles_claim=settings.auth_roles_claim,
            subject_claim=settings.auth_subject_claim,
        )
    except JwksUnavailableError as exc:
        raise HTTPException(status_code=503, detail="AUTH_JWKS_UNAVAILABLE") from exc
    except (AuthError, JwksAuthError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_INVALID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
