"""检查数据库中的用户"""
from app.db.session import engine
from sqlalchemy import text

with engine.connect() as conn:
    result = conn.execute(text('SELECT username, is_admin FROM users LIMIT 5'))
    users = [(row[0], row[1]) for row in result]
    print("数据库中的用户:")
    for username, is_admin in users:
        print(f"  - {username} (管理员: {is_admin})")
