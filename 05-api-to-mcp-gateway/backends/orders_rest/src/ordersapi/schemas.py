"""Request and response models; FastAPI turns them into the OpenAPI document."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class OrderStatus(StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class OrderItem(BaseModel):
    sku: str = Field(description="Stock-keeping unit, e.g. SKU-001")
    quantity: int = Field(ge=1, description="Number of units")


class Order(BaseModel):
    id: int
    status: OrderStatus
    customer_email: str
    customer_phone: str
    items: list[OrderItem]
    total_cents: int = Field(description="Order total in cents")
    created_at: datetime


class CreateOrderRequest(BaseModel):
    customer_email: str
    customer_phone: str
    items: list[OrderItem] = Field(min_length=1)


class CallerInfo(BaseModel):
    """Headers the backend received, to check what the gateway passes through."""

    authorization: str | None = None
    traceparent: str | None = None


class ErrorDetail(BaseModel):
    detail: str
