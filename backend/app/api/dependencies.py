from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth import AuthContext, AuthError, verify_auth_token

bearer_scheme = HTTPBearer(auto_error=False)


def require_identity(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthContext:
    secret = request.app.state.settings.inspector_auth_secret
    if not secret:
        raise HTTPException(status_code=503, detail="AUTH_NOT_CONFIGURED")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_REQUIRED",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verify_auth_token(credentials.credentials, secret)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AUTH_INVALID",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
