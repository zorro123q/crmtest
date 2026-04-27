"""
Bootstrap the default admin account.

Usage:
    python create_admin.py --username admin --password 123456
"""

from __future__ import annotations

import argparse
import asyncio

from fastapi import HTTPException

from app.db.session import AsyncSessionLocal
from app.services.auth_service import create_user_account


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the default admin user for SalesPilot CRM.")
    parser.add_argument("--username", default="admin", help="Admin username.")
    parser.add_argument("--password", default="123456", help="Admin password.")
    return parser.parse_args()


async def create_admin(username: str, password: str) -> int:
    async with AsyncSessionLocal() as session:
        try:
            user = await create_user_account(session, username, password)
        except HTTPException as exc:
            print(exc.detail)
            return 1

        print("Admin account created successfully.")
        print(f"Login username: {user.username}")
        return 0


async def main() -> int:
    args = parse_args()
    return await create_admin(args.username.strip(), args.password)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
