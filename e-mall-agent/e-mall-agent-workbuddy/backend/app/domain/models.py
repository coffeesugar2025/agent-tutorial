"""Domain entities shared by tools, agents and API."""
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Product(BaseModel):
    id: str
    name: str
    category: str
    price: float
    stock: int
    tags: list[str] = Field(default_factory=list)
    description: str = ""


class OrderItem(BaseModel):
    product_id: str
    quantity: int
    unit_price: float


class Order(BaseModel):
    id: str
    customer_id: str
    items: list[OrderItem]
    total: float
    status: str = "created"
    created_at: str = Field(default_factory=utcnow)
    address: str = ""


class User(BaseModel):
    id: str
    name: str = ""
    role: str = "guest"
    password: str = Field(default="", exclude=True)


class PublicUser(BaseModel):
    id: str
    name: str
    role: str
    permissions: list[str]
