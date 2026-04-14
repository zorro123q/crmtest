"""
Authentication and authorization helpers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
# 明文密码存储，不使用加密
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

ROLE_WEIGHT = {"sales": 1, "manager": 2, "admin": 3}
SUPPORTED_HMAC_ALGORITHMS = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}


class TokenValidationError(Exception):
    """Raised when a JWT cannot be decoded or validated."""


def _get_hmac_digest(algorithm: str):
    digest = SUPPORTED_HMAC_ALGORITHMS.get(algorithm.upper())
    if digest is None:
        raise RuntimeError(f"Unsupported JWT algorithm: {algorithm}")
    return digest


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(signing_input: bytes, secret_key: str, algorithm: str) -> bytes:
    digest = _get_hmac_digest(algorithm)
    return hmac.new(secret_key.encode("utf-8"), signing_input, digest).digest()


def _encode_jwt(payload: dict[str, Any], secret_key: str, algorithm: str) -> str:
    header = {"alg": algorithm, "typ": "JWT"}
    header_segment = _b64url_encode(
        json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    payload_segment = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature_segment = _b64url_encode(_sign(signing_input, secret_key, algorithm))
    return f"{header_segment}.{payload_segment}.{signature_segment}"


def _decode_jwt(token: str, secret_key: str, algorithm: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenValidationError("Token format is invalid")

    header_segment, payload_segment, signature_segment = parts
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")

    try:
        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
        signature = _b64url_decode(signature_segment)
    except (ValueError, json.JSONDecodeError) as exc:
        raise TokenValidationError("Token contains invalid data") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenValidationError("Token payload is invalid")

    if header.get("alg") != algorithm:
        raise TokenValidationError("Token algorithm does not match server settings")

    expected_signature = _sign(signing_input, secret_key, algorithm)
    if not hmac.compare_digest(signature, expected_signature):
        raise TokenValidationError("Token signature is invalid")

    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_timestamp = int(float(exp))
        except (TypeError, ValueError) as exc:
            raise TokenValidationError("Token expiration is invalid") from exc

        now_timestamp = int(datetime.now(timezone.utc).timestamp())
        if now_timestamp >= exp_timestamp:
            raise TokenValidationError("Token has expired")

    return payload


def hash_password(plain: str) -> str:
    """明文存储密码（测试环境使用）"""
    return plain


def verify_password(plain: str, stored: str) -> bool:
    """明文密码比较"""
    if not stored:
        return False
    return plain == stored


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = int(expire.timestamp())
    return _encode_jwt(to_encode, settings.SECRET_KEY, settings.ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return _decode_jwt(token, settings.SECRET_KEY, settings.ALGORITHM)
    except TokenValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Parse the bearer token and return the current user."""
    from sqlalchemy import select

    from app.models import User

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token payload 缺少 sub 字段")

    try:
        normalized_user_id = str(UUID(str(user_id)))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Token 中的用户 ID 非法") from exc

    result = await db.execute(select(User).where(User.id == normalized_user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return user


def require_role(*roles: str):
    """Require the current user to have one of the specified roles."""

    async def checker(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"当前角色 [{current_user.role}] 无权执行此操作，需要角色: {list(roles)}",
            )
        return current_user

    return checker


def require_min_role(min_role: str):
    """Require the current user to meet the minimum role weight."""

    async def checker(current_user=Depends(get_current_user)):
        if ROLE_WEIGHT.get(current_user.role, 0) < ROLE_WEIGHT.get(min_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 [{min_role}] 或更高权限",
            )
        return current_user

    return checker


def apply_data_scope(query, model, current_user):
    """All authenticated users can view shared business data."""
    return query


def can_edit_owned_resource(current_user, owner_id) -> bool:
    """Sales users may only edit their own records; higher roles can edit all."""
    if current_user.role == "sales":
        return str(owner_id) == str(current_user.id)
    return True
