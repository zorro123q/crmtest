"""
Reset the default admin password to 123456.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models import User


async def reset_admin_password() -> int:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        user = result.scalar_one_or_none()

        if not user:
            print("未找到 admin 账号。")
            print("请先运行: python create_admin.py --username admin --password 123456")
            return 1

        # The users table now stores passwords in plain text by requirement.
        user.password = "123456"
        await session.commit()
        print("admin 密码已重置为 123456")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(reset_admin_password()))
