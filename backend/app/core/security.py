"""
Authentication and authorization helpers.
包含 JWT 签名/验证、密码哈希（bcrypt）、当前用户鉴权及权限检查。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

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
    """使用 bcrypt 对密码进行哈希处理，返回哈希字符串。
    自动加盐，安全强度默认 rounds=12。
    """
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, stored: str) -> bool:
    """验证明文密码与存储的 bcrypt 哈希是否匹配。
    同时兼容旧版明文密码（迁移期间过渡支持）。
    """
    if not stored:
        return False
    # 如果是 bcrypt 哈希格式（以 $2b$ 或 $2a$ 开头），使用 bcrypt 校验
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
    # 兼容旧版明文密码（过渡期）
    return plain == stored


def is_admin_user(user) -> bool:
    return bool(user and (getattr(user, "is_admin", False) or getattr(user, "username", "") == "admin"))


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
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
            detail="Token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select

    from app.models import User

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token is missing the user id")

    try:
        normalized_user_id = str(UUID(str(user_id)))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Token contains an invalid user id") from exc

    result = await db.execute(select(User).where(User.id == normalized_user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def require_admin():
    async def checker(current_user=Depends(get_current_user)):
        if not is_admin_user(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the admin account can perform this action",
            )
        return current_user

    return checker


def require_role(*roles: str):
    if "admin" not in roles:
        return get_current_user
    return require_admin()


def require_min_role(_: str):
    return require_admin()


def apply_data_scope(query, model, current_user):
    if is_admin_user(current_user):
        return query

    owner_id_column = getattr(model, "owner_id", None)
    if owner_id_column is None:
        return query

    return query.where(owner_id_column == str(getattr(current_user, "id", "")))


def can_edit_owned_resource(current_user, owner_id) -> bool:
    if is_admin_user(current_user):
        return True
    return str(owner_id or "") == str(getattr(current_user, "id", ""))
