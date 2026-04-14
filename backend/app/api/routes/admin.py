"""
管理员用户管理接口。

GET    /api/admin/users          -> 获取用户列表（admin 专属）
POST   /api/admin/users          -> 创建新用户
PUT    /api/admin/users/{id}     -> 更新用户信息/权限
POST   /api/admin/users/{id}/reset-password -> 重置密码
PATCH  /api/admin/users/{id}/toggle         -> 启用/禁用用户
GET    /api/admin/permissions/modules       -> 获取所有可配置的权限模块列表
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user, hash_password, require_role
from app.db.session import get_db
from app.models import User
from app.schemas import UserOut, UserCreateRequest, UserUpdateRequest, UserPasswordReset

router = APIRouter(prefix="/api/admin", tags=["管理员"])

# 所有可配置的权限模块（与前端菜单对应）
PERMISSION_MODULES = [
    {"key": "dashboard", "name": "销售仪表盘", "icon": "📊", "page": "page-dashboard.html"},
    {"key": "funnel", "name": "商机漏斗", "icon": "🔻", "page": "page-funnel.html"},
    {"key": "kanban", "name": "商机看板", "icon": "🗂️", "page": "page-kanban.html"},
    {"key": "leads", "name": "线索管理", "icon": "👥", "page": "page-leads.html"},
    {"key": "opportunities", "name": "商机列表", "icon": "💼", "page": "page-opportunities.html"},
    {"key": "report", "name": "商机通报", "icon": "📋", "page": "page-report.html"},
    {"key": "ai_input", "name": "AI 智能录入", "icon": "🤖", "page": "ai-input.html"},
    {"key": "card_input", "name": "价值评估", "icon": "🎯", "page": "card-input.html"},
    {"key": "user_management", "name": "用户管理", "icon": "⚙️", "page": "admin-users.html"},
]

# 角色默认权限
ROLE_DEFAULT_PERMISSIONS = {
    "admin": {m["key"]: True for m in PERMISSION_MODULES},
    "manager": {m["key"]: True for m in PERMISSION_MODULES if m["key"] != "user_management"},
    "sales": {
        "dashboard": True,
        "funnel": True,
        "kanban": True,
        "leads": True,
        "opportunities": True,
        "report": False,
        "ai_input": True,
        "card_input": False,
        "user_management": False,
    },
}


def get_effective_permissions(user: User) -> dict:
    """获取用户的有效权限（自定义权限优先，否则使用角色默认权限）"""
    if user.permissions:
        return user.permissions
    return ROLE_DEFAULT_PERMISSIONS.get(user.role, ROLE_DEFAULT_PERMISSIONS["sales"])


@router.get("/permissions/modules")
async def get_permission_modules(
    _: User = Depends(require_role("admin")),
):
    """返回所有可配置的权限模块列表"""
    return {"modules": PERMISSION_MODULES}


@router.get("/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """获取所有用户列表（含权限信息）"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    result_list = []
    for user in users:
        out = UserOut.model_validate(user)
        out.permissions = get_effective_permissions(user)
        result_list.append(out)
    return result_list


@router.post("/users", response_model=UserOut)
async def create_user(
    data: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """创建新用户（admin 专属）"""
    # 验证用户名不重复
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 验证邮箱不重复
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已被使用")

    # 验证角色合法
    if data.role not in ("admin", "manager", "sales"):
        raise HTTPException(status_code=400, detail="无效的角色")

    user = User(
        username=data.username,
        email=data.email,
        hashed_pwd=hash_password(data.password),
        role=data.role,
        permissions=data.permissions,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    out = UserOut.model_validate(user)
    out.permissions = get_effective_permissions(user)
    return out


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    data: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """更新用户信息（角色、权限、启用状态）"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if data.email is not None:
        existing = await db.execute(select(User).where(User.email == data.email, User.id != user_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="邮箱已被使用")
        user.email = data.email

    if data.role is not None:
        if data.role not in ("admin", "manager", "sales"):
            raise HTTPException(status_code=400, detail="无效的角色")
        user.role = data.role

    if data.permissions is not None:
        user.permissions = data.permissions

    if data.is_active is not None:
        user.is_active = data.is_active

    await db.flush()
    out = UserOut.model_validate(user)
    out.permissions = get_effective_permissions(user)
    return out


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    data: UserPasswordReset,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """重置用户密码"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.hashed_pwd = hash_password(data.new_password)
    await db.flush()
    return {"message": f"用户 {user.username} 的密码已重置"}


@router.patch("/users/{user_id}/toggle")
async def toggle_user_active(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """启用/禁用用户（不能禁用自己）"""
    if str(current_user.id) == str(user_id):
        raise HTTPException(status_code=400, detail="不能禁用自己")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = not user.is_active
    await db.flush()
    return {"message": f"用户 {user.username} 已{'启用' if user.is_active else '禁用'}", "is_active": user.is_active}
