from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_role_name, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.schemas.auth import ChangePasswordRequest, LoginRequest, TokenResponse, UserProfile
from app.services import auth_service
from app.services.auth_service import authenticate

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.JWT_REFRESH_EXPIRE_DAYS * 24 * 3600,
        path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    _, _, access_token, refresh_token = await authenticate(
        db, payload.identifier, payload.password, request=request
    )
    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token, expires_in=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    access_token = await auth_service.refresh_access_token(db, refresh_token, request=request)
    return TokenResponse(access_token=access_token, expires_in=settings.JWT_ACCESS_EXPIRE_MINUTES * 60)


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    await auth_service.logout(db, refresh_token, request=request)
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return {"detail": "logged out"}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Changes the CALLER'S OWN password.

    There is deliberately no `user_id` parameter: this endpoint can never
    be pointed at somebody else's account, whatever role the caller holds.
    An Administrator resetting another user's password is a different
    operation with a different audit trail (PATCH /users/{id}), and one
    that marks the result temporary.
    """
    await auth_service.change_password(
        db,
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        request=request,
    )
    return {"detail": "password changed"}


@router.get("/me", response_model=UserProfile)
async def me(
    request: Request,
    user=Depends(get_current_user),
    role_name: str = Depends(get_current_role_name),
):
    return UserProfile(
        id=str(user.id),
        employee_code=user.employee_code,
        full_name=user.full_name,
        email=user.email,
        role=role_name,
        permissions={},
        must_change_password=user.must_change_password,
    )
