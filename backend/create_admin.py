"""
Bootstrap the first admin account for the local SalesPilot CRM environment.

Usage:
    python create_admin.py --email admin@example.com --username 系统管理员 --password StrongPass123
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import or_, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models import User


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first admin user for SalesPilot CRM.")
    parser.add_argument("--email", required=True, help="Admin login email.")
    parser.add_argument("--username", required=True, help="Admin display name or username.")
    parser.add_argument("--password", required=True, help="Admin login password.")
    return parser.parse_args()


async def create_admin(email: str, username: str, password: str) -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(or_(User.email == email, User.username == username))
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(
                "Account already exists:",
                f"email={existing_user.email}",
                f"username={existing_user.username}",
                f"role={existing_user.role}",
            )
            return 1

        user = User(
            email=email,
            username=username,
            hashed_pwd=hash_password(password),
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()

        print("Admin account created successfully.")
        print(f"Login email: {email}")
        print(f"Display name: {username}")
        return 0


async def main() -> int:
    args = parse_args()
    return await create_admin(args.email.strip(), args.username.strip(), args.password)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
