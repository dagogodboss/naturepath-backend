"""
In-memory Revel substitute for unit/integration tests only.

Production code uses RevelLiveClient via RevelService (no mock fallback).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RevelOrder(BaseModel):
    order_id: str
    establishment_id: int
    customer_id: Optional[str] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    subtotal: float
    tax: float
    total: float
    status: str = "open"
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class RevelPayment(BaseModel):
    transaction_id: str
    order_id: str
    amount: float
    payment_method: str
    status: str = "pending"
    created_at: datetime

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class RevelProduct(BaseModel):
    product_id: str
    name: str
    price: float
    category: str
    is_active: bool = True


class RevelFakeBackend:
    """Deterministic in-memory Revel for tests (inject via dependency override)."""

    def __init__(self) -> None:
        self._orders: Dict[str, RevelOrder] = {}
        self._payments: Dict[str, RevelPayment] = {}
        self._products: Dict[str, RevelProduct] = {}
        self._initialize_products()

    def _initialize_products(self) -> None:
        mock_products = [
            {"product_id": "revel_svc_001", "name": "Swedish Massage", "price": 120.00, "category": "massage"},
            {"product_id": "revel_svc_002", "name": "Deep Tissue Massage", "price": 150.00, "category": "massage"},
        ]
        for p in mock_products:
            self._products[p["product_id"]] = RevelProduct(**p)

    async def validate_service(self, revel_product_id: str) -> Optional[Dict[str, Any]]:
        await asyncio.sleep(0)
        product = self._products.get(revel_product_id)
        if product and product.is_active:
            return product.model_dump()
        return None

    async def get_all_products(self) -> List[Dict[str, Any]]:
        await asyncio.sleep(0)
        return [p.model_dump() for p in self._products.values() if p.is_active]

    async def create_order(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        establishment_id: int,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        await asyncio.sleep(0)
        order_id = f"REVEL_ORD_{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)
        subtotal = sum(float(item.get("price", 0)) * int(item.get("quantity", 1)) for item in items)
        tax = round(subtotal * 0.0925, 2)
        total = round(subtotal + tax, 2)
        order = RevelOrder(
            order_id=order_id,
            establishment_id=establishment_id,
            customer_id=customer_id,
            items=items,
            subtotal=subtotal,
            tax=tax,
            total=total,
            status="open",
            created_at=now,
            updated_at=now,
        )
        self._orders[order_id] = order
        return order.model_dump(mode="json")

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        await asyncio.sleep(0)
        order = self._orders.get(order_id)
        return order.model_dump(mode="json") if order else None

    async def update_order_status(self, order_id: str, status: str) -> Optional[Dict[str, Any]]:
        await asyncio.sleep(0)
        if order_id in self._orders:
            self._orders[order_id].status = status
            self._orders[order_id].updated_at = datetime.now(timezone.utc)
            return self._orders[order_id].model_dump(mode="json")
        return None

    async def process_payment(
        self,
        order_id: str,
        amount: float,
        payment_method: str = "card",
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        await asyncio.sleep(0)
        transaction_id = str(100000 + len(self._payments))  # numeric for tests
        now = datetime.now(timezone.utc)
        payment = RevelPayment(
            transaction_id=transaction_id,
            order_id=order_id,
            amount=amount,
            payment_method=payment_method,
            status="completed",
            created_at=now,
        )
        self._payments[transaction_id] = payment
        await self.update_order_status(order_id, "paid")
        return {
            "success": True,
            "transaction_id": transaction_id,
            "order_id": order_id,
            "amount": amount,
            "status": "completed",
            "message": "Payment successful",
        }

    async def confirm_payment(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        await asyncio.sleep(0)
        payment = self._payments.get(transaction_id)
        return payment.model_dump(mode="json") if payment else None

    async def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        await asyncio.sleep(0)
        original_payment = self._payments.get(transaction_id)
        if not original_payment:
            return {"success": False, "message": "Original transaction not found"}
        refund_amount = amount if amount else original_payment.amount
        refund_id = f"REVEL_REF_{uuid.uuid4().hex[:12].upper()}"
        return {
            "success": True,
            "refund_id": refund_id,
            "original_transaction_id": transaction_id,
            "amount": refund_amount,
            "status": "refunded",
        }

    async def sync_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0)
        revel_customer_id = f"REVEL_CUST_{uuid.uuid4().hex[:8].upper()}"
        return {
            "revel_customer_id": revel_customer_id,
            "synced": True,
            "email": customer_data.get("email"),
            "name": customer_data.get("name"),
        }

    async def create_order_and_pay(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        payment_method: str = "card",
        establishment_id: int = 1,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        order = await self.create_order(
            customer_id,
            items,
            establishment_id,
            idempotency_key=idempotency_key,
        )
        payment = await self.process_payment(
            order_id=order["order_id"],
            amount=float(order["total"]),
            payment_method=payment_method,
            idempotency_key=f"{idempotency_key}:pay" if idempotency_key else None,
        )
        return {"order": order, "payment": payment}
