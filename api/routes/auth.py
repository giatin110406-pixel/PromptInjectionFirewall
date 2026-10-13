from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies.auth import DEMO_USERS, create_token_for_user, get_current_user
from api.schemas import AuthLoginRequest, AuthTokenResponse, AuthUser

router = APIRouter()


@router.post("/login", response_model=AuthTokenResponse)
def login(payload: AuthLoginRequest):
    user = DEMO_USERS.get(payload.username)
    if user is None or user["password"] != payload.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_token_for_user(payload.username)
    return AuthTokenResponse(
        access_token=token,
        token_type="bearer",
        user=AuthUser(
            user_id=user["user_id"],
            username=payload.username,
            roles=user["roles"],
            permissions=user["permissions"],
        ),
    )


@router.get("/me", response_model=AuthUser)
def get_me(current_user: AuthUser = Depends(get_current_user)):
    return current_user
