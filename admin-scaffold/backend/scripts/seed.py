"""启动时幂等初始化：权限 -> 超级管理员角色 -> 管理员账号。"""
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import hash_password
from app.db.mysql import AsyncSessionLocal
from app.models import Permission, Role, User

PERMISSIONS = [
    ("dashboard:view", "查看工作台", "dashboard", "menu", 1),
    ("user:list", "用户列表", "user", "api", 10),
    ("user:create", "新增用户", "user", "button", 11),
    ("user:update", "编辑用户", "user", "button", 12),
    ("user:delete", "删除用户", "user", "button", 13),
    ("role:list", "角色列表", "role", "api", 20),
    ("role:create", "新增角色", "role", "button", 21),
    ("role:update", "编辑角色", "role", "button", 22),
    ("role:delete", "删除角色", "role", "button", 23),
    ("permission:list", "权限列表", "permission", "api", 30),
    ("permission:create", "新增权限", "permission", "button", 31),
    ("permission:update", "编辑权限", "permission", "button", 32),
    ("permission:delete", "删除权限", "permission", "button", 33),
    ("audit:list", "审计日志", "audit", "api", 40),
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        existing = {
            p.code: p
            for p in (await db.execute(select(Permission))).scalars().all()
        }
        for code, name, module, kind, sort in PERMISSIONS:
            if code not in existing:
                db.add(
                    Permission(code=code, name=name, module=module, kind=kind, sort=sort)
                )
        await db.flush()

        all_perms = (await db.execute(select(Permission))).scalars().all()
        role = (
            await db.execute(
                select(Role)
                .options(selectinload(Role.permissions))
                .where(Role.code == "super_admin")
            )
        ).scalar_one_or_none()
        if not role:
            # 关键：集合在构造函数里传入。若等 flush 之后再 role.permissions = ...，
            # SQLAlchemy 为计算差集会去 lazy load 旧集合，在异步会话里触发隐式 IO
            # → MissingGreenlet: greenlet_spawn has not been called。
            role = Role(
                code="super_admin",
                name="超级管理员",
                description="内置角色，拥有全部权限",
                is_active=True,
                permissions=list(all_perms),
            )
            db.add(role)
            await db.flush()
        else:
            # role 已由 selectinload 预加载，此时赋值会走内存 diff，不再查库
            role.permissions = list(all_perms)

        admin = (
            await db.execute(
                select(User)
                .options(selectinload(User.roles))
                .where(User.username == settings.INIT_ADMIN_USERNAME)
            )
        ).scalar_one_or_none()
        if not admin:
            admin = User(
                username=settings.INIT_ADMIN_USERNAME,
                hashed_password=hash_password(settings.INIT_ADMIN_PASSWORD),
                nickname="系统管理员",
                email="admin@example.com",
                is_active=True,
                is_superuser=True,
                roles=[role],
            )
            db.add(admin)
            await db.flush()
            logger.info(
                f"[seed] admin created: {settings.INIT_ADMIN_USERNAME} / "
                f"{settings.INIT_ADMIN_PASSWORD} (请登录后立即修改)"
            )
        elif not admin.roles:
            # admin 已由 selectinload 预加载，赋值安全
            admin.roles = [role]
        await db.commit()


if __name__ == "__main__":
    import asyncio

    from app.db.mysql import init_tables

    async def _main():
        await init_tables()
        await seed()

    asyncio.run(_main())
