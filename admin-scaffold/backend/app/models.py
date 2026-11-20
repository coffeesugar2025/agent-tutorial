from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mysql import Base

user_roles = Table(
    "sys_user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("sys_user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "sys_role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("sys_role.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("sys_permission.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="登录名")
    hashed_password: Mapped[str] = mapped_column(String(128))
    nickname: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )


class Role(Base):
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, comment="角色编码")
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list[User]] = relationship(
        secondary=user_roles, back_populates="roles", lazy="selectin"
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )


class Permission(Base):
    __tablename__ = "sys_permission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(96), unique=True, index=True, comment="如 user:create")
    name: Mapped[str] = mapped_column(String(64))
    module: Mapped[str] = mapped_column(String(64), default="system", comment="模块分组")
    kind: Mapped[str] = mapped_column(String(16), default="api", comment="menu/api/button")
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    roles: Mapped[list[Role]] = relationship(
        secondary=role_permissions, back_populates="permissions", lazy="selectin"
    )
