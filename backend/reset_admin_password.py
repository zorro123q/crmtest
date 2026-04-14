"""
重置 admin 用户密码为明文 123456。
用于从 bcrypt 哈希模式切换到明文模式后修复数据库中的密码。
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.models import User


async def reset_admin_password() -> int:
    async with AsyncSessionLocal() as session:
        # 查找用户名包含 admin 或 username 为 admin 的用户
        result = await session.execute(
            select(User).where(
                User.username.contains("admin")
            )
        )
        users = result.scalars().all()

        if not users:
            print("未找到包含 'admin' 的用户，尝试按 email 查找...")
            result = await session.execute(
                select(User).where(User.email.contains("admin"))
            )
            users = result.scalars().all()

        if not users:
            print("未找到任何 admin 相关用户。")
            print("请先运行: python create_admin.py --email admin@example.com --username admin --password 123456")
            return 1

        for user in users:
            old_hash = user.hashed_pwd[:30] + "..." if len(user.hashed_pwd) > 30 else user.hashed_pwd
            print(f"找到用户: username={user.username}, email={user.email}, role={user.role}")
            print(f"  旧密码(前30字符): {old_hash}")

            # 直接通过 SQL 更新为明文密码（绕过 hash_password）
            await session.execute(
                text("UPDATE users SET hashed_pwd = :pwd WHERE id = :uid"),
                {"pwd": "123456", "uid": user.id},
            )
            print(f"  [OK] 密码已重置为明文: 123456")

        await session.commit()
        print("\n所有 admin 用户密码已重置完成。")
        print("登录方式: 用户名 admin，密码 123456")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(reset_admin_password()))
