"""
Authentication routes.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.admin import get_effective_permissions
from app.core.security import (
    create_access_token,
    get_current_user,
    hash_password,
    require_role,
    verify_password,
)
from app.db.session import get_db
from app.models import User
from app.schemas import TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse, summary="用户名登录")
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.hashed_pwd):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    user_out = UserOut.model_validate(user)
    user_out.permissions = get_effective_permissions(user)
    return TokenResponse(access_token=token, user=user_out)


@router.get("/me", response_model=UserOut, summary="获取当前用户")
async def get_me(current_user: User = Depends(get_current_user)):
    user_out = UserOut.model_validate(current_user)
    user_out.permissions = get_effective_permissions(current_user)
    return user_out


@router.post("/users", response_model=UserOut, summary="创建用户（admin）")
async def create_user(
    email: str,
    username: str,
    password: str,
    role: str = "sales",
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    existing_email = await db.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已被使用")

    existing_username = await db.execute(select(User).where(User.username == username))
    if existing_username.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        email=email,
        username=username,
        hashed_pwd=hash_password(password),
        role=role,
    )
    db.add(user)
    await db.flush()
    return UserOut.model_validate(user)
