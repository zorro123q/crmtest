"""检查数据库中的用户"""
import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def check_users():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text('SELECT username FROM users LIMIT 5'))
        users = [(row[0],) for row in result]
        print("数据库中的用户:")
        for (username,) in users:
            print(f"  - {username}")

asyncio.run(check_users())
