"""Shared domain schemas for demo microservices."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


# --- Enums ---

class OrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"


class PaymentStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class InventoryStatus(str, Enum):
    RESERVED = "RESERVED"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    FAILED = "FAILED"


# --- Order Models ---

class OrderItem(BaseModel):
    sku: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., gt=0.0)


class OrderCreateRequest(BaseModel):
    customer_id: str = Field(default="cust-1001")
    items: List[OrderItem] = Field(..., min_length=1)
    payment_method: str = Field(default="credit_card")


class OrderResponse(BaseModel):
    order_id: str
    customer_id: str
    items: List[OrderItem]
    total_amount: float
    status: OrderStatus
    payment_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None


# --- Payment Models ---

class PaymentRequest(BaseModel):
    order_id: str
    customer_id: str
    amount: float = Field(..., gt=0.0)
    payment_method: str = Field(default="credit_card")


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    amount: float
    status: PaymentStatus
    processed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: Optional[str] = None


# --- Inventory Models ---

class InventoryReserveRequest(BaseModel):
    order_id: str
    items: List[OrderItem]


class InventoryItem(BaseModel):
    sku: str
    name: str
    available_stock: int
    price: float


class InventoryResponse(BaseModel):
    order_id: str
    status: InventoryStatus
    reserved_items: List[OrderItem] = Field(default_factory=list)
    error_message: Optional[str] = None


# --- Fault Injection Models (For Controlled Scenarios) ---

class FaultInjectionType(str, Enum):
    NONE = "none"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    UNAVAILABLE = "unavailable"


class FaultConfig(BaseModel):
    """Runtime fault injection parameters for simulating realistic failures."""
    fault_type: FaultInjectionType = FaultInjectionType.NONE
    latency_delay_ms: float = 0.0
    error_rate_pct: float = 0.0  # 0.0 to 100.0 percent
    error_status_code: int = 500
    error_message: str = "Simulated downstream failure"

