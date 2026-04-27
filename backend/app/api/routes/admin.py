"""
Admin user management routes.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, hash_password, is_admin_user, require_admin
from app.db.session import get_db
from app.models import Account, Activity, Contact, Lead, Opportunity, User
from app.schemas import MessageResponse, UserCreateRequest, UserOut, UserUpdateRequest
from app.services.auth_service import create_user_account, get_user_by_username, validate_password, validate_username

router = APIRouter(prefix="/api/admin", tags=["管理员"])


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


@router.get("/users", response_model=list[UserOut], summary="用户列表")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin()),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [serialize_user(user) for user in users]


@router.post("/users", response_model=UserOut, status_code=201, summary="新增用户")
async def create_user(
    data: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin()),
):
    user = await create_user_account(db, data.username, data.password)
    return serialize_user(user)


@router.put("/users/{user_id}", response_model=UserOut, summary="编辑用户")
async def update_user(
    user_id: str,
    data: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin()),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.username is not None:
        username = validate_username(data.username)
        existing_user = await get_user_by_username(db, username)
        if existing_user and str(existing_user.id) != str(user_id):
            raise HTTPException(status_code=400, detail="用户名已存在")
        if user.username == "admin" and username != "admin":
            raise HTTPException(status_code=400, detail="默认 admin 账号名称不可修改")
        user.username = username

    if data.password is not None:
        user.password = hash_password(validate_password(data.password))

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户更新失败，请检查用户名是否重复") from exc

    await db.refresh(user)
    return serialize_user(user)


@router.delete("/users/{user_id}", response_model=MessageResponse, summary="删除用户")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin()),
):
    if str(current_user.id) == str(user_id):
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if user.username == "admin":
        raise HTTPException(status_code=400, detail="默认 admin 账号不可删除")

    for model in (Account, Contact, Lead, Opportunity, Activity):
        await db.execute(update(model).where(model.owner_id == user_id).values(owner_id=None))

    await db.delete(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="无法删除该用户，请先解除相关数据关联") from exc
    return MessageResponse(message="用户删除成功")


@router.get("/session", response_model=UserOut, summary="当前管理员信息")
async def get_admin_session(current_user: User = Depends(get_current_user)):
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="仅 admin 账号可访问")
    return serialize_user(current_user)
