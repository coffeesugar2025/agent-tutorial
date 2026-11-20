from typing import Any, Generic, TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Permission, Role, User

ModelType = TypeVar("ModelType")


class CRUDBase(Generic[ModelType]):
    def __init__(
        self,
        model: type[ModelType],
        eager_options: list | None = None,
        delete_options: list | None = None,
    ) -> None:
        self.model = model
        # 异步会话里禁止依赖隐式 lazy load：凡是要读/写的关系都在这里预加载。
        # 注意 session.get() 不会应用 selectin 策略，所以 get()/delete() 一律走 select + options。
        self.eager_options = list(eager_options or [])
        # 删除父对象时 ORM 还要遍历反向关系清理关联表，单独配一份更全的加载项
        self.delete_options = list(delete_options or self.eager_options)

    async def get(self, db: AsyncSession, obj_id: int) -> ModelType | None:
        stmt = (
            select(self.model)
            .options(*self.eager_options)
            .where(self.model.id == obj_id)
        )
        result = await db.execute(stmt)
        return result.scalars().unique().one_or_none()

    async def list(
        self,
        db: AsyncSession,
        page: int = 1,
        size: int = 20,
        keyword: str = "",
        search_fields: list[str] | None = None,
        extra_where: list | None = None,
    ) -> tuple[list[ModelType], int]:
        stmt = select(self.model).options(*self.eager_options)
        count_stmt = select(func.count()).select_from(self.model)
        conditions = list(extra_where or [])
        if keyword and search_fields:
            conditions.append(
                or_(*[getattr(self.model, f).like(f"%{keyword}%") for f in search_fields])
            )
        if conditions:
            stmt = stmt.where(*conditions)
            count_stmt = count_stmt.where(*conditions)
        total = (await db.execute(count_stmt)).scalar_one()
        stmt = stmt.order_by(self.model.id.desc()).offset((page - 1) * size).limit(size)
        items = (await db.execute(stmt)).scalars().unique().all()
        return list(items), total

    async def create(self, db: AsyncSession, values: dict[str, Any]) -> ModelType:
        obj = self.model(**values)
        db.add(obj)
        await db.flush()
        return obj

    async def update(self, db: AsyncSession, obj: ModelType, values: dict[str, Any]) -> ModelType:
        for k, v in values.items():
            setattr(obj, k, v)
        await db.flush()
        return obj

    async def delete(self, db: AsyncSession, obj_id: int) -> bool:
        # 不能用 db.get()：独立会话里它返回的对象关系未加载，删除时 ORM 为清理
        # secondary 表会去 lazy load，在异步上下文里抛 MissingGreenlet。
        stmt = (
            select(self.model)
            .options(*self.delete_options)
            .where(self.model.id == obj_id)
        )
        result = await db.execute(stmt)
        obj = result.scalars().unique().one_or_none()
        if not obj:
            return False
        await db.delete(obj)
        await db.flush()
        return True


user_crud = CRUDBase(User, [selectinload(User.roles)])
role_crud = CRUDBase(
    Role,
    [selectinload(Role.permissions)],
    [selectinload(Role.permissions), selectinload(Role.users)],
)
permission_crud = CRUDBase(
    Permission,
    delete_options=[selectinload(Permission.roles)],
)


async def load_roles(db: AsyncSession, role_ids: list[int]) -> list[Role]:
    if not role_ids:
        return []
    result = await db.execute(select(Role).where(Role.id.in_(role_ids)))
    return list(result.scalars().unique().all())


async def load_permissions(db: AsyncSession, perm_ids: list[int]) -> list[Permission]:
    if not perm_ids:
        return []
    result = await db.execute(select(Permission).where(Permission.id.in_(perm_ids)))
    return list(result.scalars().unique().all())


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname,
        "email": user.email,
        "phone": user.phone,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "roles": [r.code for r in user.roles],
        "role_ids": [r.id for r in user.roles],
    }


def role_to_dict(role: Role) -> dict:
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "created_at": role.created_at,
        "permission_ids": [p.id for p in role.permissions],
    }
