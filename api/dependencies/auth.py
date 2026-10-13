import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.schemas import AuthUser

JWT_SECRET = os.getenv("JWT_SECRET", "demo-secret-key-32-bytes-for-jwt-demo")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ISSUER = os.getenv("JWT_ISSUER", "ai-firewall-demo")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "ai-firewall-api")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "60"))

security = HTTPBearer(auto_error=False)

DEMO_USERS = {
    "support_agent": {
        "user_id": "u_support_001",
        "password": "support_agent_123",
        "roles": ["support_agent"],
        "permissions": ["chat:read", "refund:request"],
    },
    "finance_lead": {
        "user_id": "u_finance_001",
        "password": "finance_lead_123",
        "roles": ["finance_lead"],
        "permissions": ["chat:read", "refund:request", "refund:approve", "refund:approve_over_200"],
    },
    "security_admin": {
        "user_id": "u_security_001",
        "password": "security_admin_123",
        "roles": ["security_admin"],
        "permissions": ["chat:read", "data_access:system_prompt", "data_access:credentials"],
    },
}


def create_token_for_user(username: str) -> str:
    user = DEMO_USERS.get(username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": user["user_id"],
        "user_id": user["user_id"],
        "username": username,
        "roles": user["roles"],
        "permissions": user["permissions"],
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_EXPIRES_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    return jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
    )


def to_auth_user(payload: Dict[str, Any]) -> "AuthUser":
    roles = payload.get("roles", [])
    permissions = payload.get("permissions", [])
    return AuthUser(
        user_id=str(payload.get("user_id") or payload.get("sub") or "unknown"),
        username=str(payload.get("username") or "unknown"),
        roles=[str(role) for role in roles],
        permissions=[str(permission) for permission in permissions],
    )


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> "AuthUser":
    if credentials is None or credentials.scheme.lower() != "bearer":
        return AuthUser(
            user_id="anonymous",
            username="anonymous",
            roles=["guest"],
            permissions=["chat:read"],
        )

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return to_auth_user(payload)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> "AuthUser":
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return get_optional_user(credentials)


def require_roles(*required_roles: str):
    def dependency(current_user: "AuthUser" = Depends(get_current_user)) -> "AuthUser":
        if not required_roles:
            return current_user
        user_roles = {role.lower() for role in current_user.roles}
        allowed = {role.lower() for role in required_roles}
        if not user_roles.intersection(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {required_roles}",
            )
        return current_user

    return dependency
