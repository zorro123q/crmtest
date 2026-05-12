"""
Authentication routes.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, get_current_user, hash_password, is_admin_user, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas import ChangePasswordRequest, MessageResponse, LoginRequest, TokenResponse, UserOut
from app.services.auth_service import INVALID_CREDENTIALS_MESSAGE, authenticate_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def serialize_user(user: User) -> UserOut:
    return UserOut.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "is_admin": is_admin_user(user),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }
    )


@router.post("/login", response_model=TokenResponse, summary="Username and password login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await authenticate_user(db, payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_MESSAGE)

    token = create_access_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(access_token=token, user=serialize_user(user))


@router.get("/me", response_model=UserOut, summary="Current user session")
async def get_me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)


@router.post("/change-password", response_model=MessageResponse, summary="Change current user password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password = hash_password(payload.new_password)
    await db.commit()
    await db.refresh(current_user)
    return MessageResponse(message="Password updated successfully")
