"""
Create or promote an administrator account.

Usage:
    python create_admin.py --username cazang --password cmzang123
    python create_admin.py --username zangsan --password zangsan123
"""

from __future__ import annotations

import argparse
import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import User
from app.services.auth_service import create_user_account, validate_password, validate_username
from app.services.schema_service import ensure_runtime_schema


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or promote a SalesPilot CRM admin user.")
    parser.add_argument("--username", required=True, help="Admin username.")
    parser.add_argument("--password", help="Password for a new admin, or a password reset for an existing user.")
    return parser.parse_args()


async def create_or_promote_admin(username: str, password: str | None) -> int:
    await ensure_runtime_schema()
    try:
        username = validate_username(username)
        if password:
            password = validate_password(password)
    except HTTPException as exc:
        print(exc.detail)
        return 1

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

        if user:
            user.is_admin = True
            if password:
                user.password = hash_password(password)
            await session.commit()
            print("Admin account updated successfully.")
            print(f"Login username: {user.username}")
            return 0

        if not password:
            print("Password is required when creating a new admin account.")
            return 1

        try:
            user = await create_user_account(session, username, password, is_admin=True)
        except HTTPException as exc:
            print(exc.detail)
            return 1

        print("Admin account created successfully.")
        print(f"Login username: {user.username}")
        return 0


async def main() -> int:
    args = parse_args()
    return await create_or_promote_admin(args.username.strip(), args.password)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
