"""
Helpers for resolving business owner display names to login accounts.

Imported CRM sheets use Chinese display names, while login accounts use short
usernames. Keep that compatibility mapping in one place so import ownership and
permission fallback stay consistent.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


OWNER_NAME_TO_USERNAME = {
    "王保三": "bswang",
    "臧春梅": "cmzang",
    "李鑫健": "xjli",
    "余浩然": "hryv",
    "陈棋": "cq",
    "陈祺": "cq",
    "杨序东": "xdyang",
    "杨序冬": "xdyang",
    "杨俊波": "jbyang",
}

_OWNER_KEY_TO_USERNAME = {
    "".join(name.split()).lower(): username
    for name, username in OWNER_NAME_TO_USERNAME.items()
}


def normalize_owner_key(value: str | None) -> str:
    return "".join(str(value or "").split()).lower()


def owner_username_candidates(owner_name: str | None) -> list[str]:
    text = str(owner_name or "").strip()
    if not text:
        return []

    candidates: list[str] = []
    mapped_username = _OWNER_KEY_TO_USERNAME.get(normalize_owner_key(text))
    if mapped_username:
        candidates.append(mapped_username)
    candidates.append(text)

    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = normalize_owner_key(candidate)
        if key and key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def owner_name_matches_user(user: User | None, owner_name: str | None) -> bool:
    username_key = normalize_owner_key(getattr(user, "username", None))
    if not username_key:
        return False
    return any(
        normalize_owner_key(candidate) == username_key
        for candidate in owner_username_candidates(owner_name)
    )


async def resolve_owner_id_by_name(db: AsyncSession, owner_name: str | None) -> str | None:
    for username in owner_username_candidates(owner_name):
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user:
            return str(user.id)
    return None
