"""
Shared authentication helpers.
用户认证、用户名/密码校验、用户账号创建等共用逻辑。
"""

from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import User


INVALID_CREDENTIALS_MESSAGE = "用户名或密码错误"

# 用户名合法字符：字母、数字、下划线、连字符，长度 2-50
_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5]{2,50}$")


def normalize_username(username: str) -> str:
    """去除首尾空格。"""
    return (username or "").strip()


def validate_username(username: str) -> str:
    """校验用户名格式：非空、符合字符规则。"""
    normalized = normalize_username(username)
    if not normalized:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not _USERNAME_PATTERN.match(normalized):
        raise HTTPException(
            status_code=400,
            detail="用户名只能包含字母、数字、下划线、连字符或中文，长度 2-50 个字符",
        )
    return normalized


def validate_password(password: str) -> str:
    """
    校验密码强度：
    - 长度不少于 settings.PASSWORD_MIN_LENGTH（默认 8）
    - 至少包含一个字母和一个数字
    """
    raw = password or ""
    min_len = getattr(settings, "PASSWORD_MIN_LENGTH", 8)
    if len(raw) < min_len:
        raise HTTPException(status_code=400, detail=f"密码长度不能少于 {min_len} 个字符")
    if not re.search(r"[A-Za-z]", raw):
        raise HTTPException(status_code=400, detail="密码必须包含至少一个字母")
    if not re.search(r"[0-9]", raw):
        raise HTTPException(status_code=400, detail="密码必须包含至少一个数字")
    return raw


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """按用户名查找用户（大小写敏感）。"""
    normalized = normalize_username(username)
    if not normalized:
        return None
    result = await db.execute(select(User).where(User.username == normalized))
    return result.scalar_one_or_none()


async def authenticate_user(db: AsyncSession, username: str, password: str) -> User | None:
    """校验用户名和密码，返回用户对象或 None。"""
    user = await get_user_by_username(db, username)
    if not user or not verify_password(password, user.password):
        return None
    return user


async def create_user_account(db: AsyncSession, username: str, password: str, is_admin: bool = False) -> User:
    """创建新用户账号，自动对密码做 bcrypt 哈希后存储。"""
    normalized_username = validate_username(username)
    raw_password = validate_password(password)

    existing_user = await get_user_by_username(db, normalized_username)
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(
        username=normalized_username,
        password=hash_password(raw_password),
        is_admin=is_admin or normalized_username == "admin",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="用户创建失败，请检查用户名是否重复") from exc

    await db.refresh(user)
    return user
