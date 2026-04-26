"""
Revel POS integration — live REST only.

Configure REVEL_SUBDOMAIN (or REVEL_REST_BASE_URL) and non-placeholder
REVEL_API_KEY / REVEL_API_SECRET. Unconfigured or failed calls raise RevelLiveError.

Tests inject a fake via dependency overrides; see backend/tests/fakes/revel_fake.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.config import Settings, get_settings
from infrastructure.external.revel_live_client import RevelLiveClient, RevelLiveError

logger = logging.getLogger(__name__)


class RevelService:
    """Thin facade over RevelLiveClient (no mock fallback in production)."""

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._live = RevelLiveClient(self._settings)

    def _require_configured(self) -> None:
        if not self._live.is_configured():
            raise RevelLiveError(
                "Revel is not configured: set REVEL_SUBDOMAIN or REVEL_REST_BASE_URL "
                "and real REVEL_API_KEY / REVEL_API_SECRET (not placeholder values)."
            )

    def _establishment_id(self) -> int:
        return int(self._settings.revel_establishment_id)

    async def validate_service(self, revel_product_id: str) -> Optional[Dict[str, Any]]:
        self._require_configured()
        return await self._live.validate_service(revel_product_id)

    async def get_all_products(self) -> List[Dict[str, Any]]:
        self._require_configured()
        return await self._live.get_all_products()

    async def create_order(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        establishment_id: int | None = None,
        hold: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_configured()
        if hold and not self._settings.revel_enable_hold_orders:
            raise RevelLiveError("Revel hold orders are disabled until sandbox contract verification completes")
        est = establishment_id if establishment_id is not None else self._establishment_id()
        return await self._live.create_order(
            customer_id,
            items,
            est,
            hold=hold,
            idempotency_key=idempotency_key,
        )

    async def create_order_and_pay(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        payment_method: str = "card",
        establishment_id: int | None = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Revel order and capture payment in one request path."""
        self._require_configured()
        est = establishment_id if establishment_id is not None else self._establishment_id()
        order = await self._live.create_order(
            customer_id,
            items,
            est,
            idempotency_key=idempotency_key,
        )
        pay_idempotency_key = f"{idempotency_key}:pay" if idempotency_key else None
        payment = await self._live.process_payment(
            order_id=order["order_id"],
            amount=float(order["total"]),
            payment_method=payment_method,
            idempotency_key=pay_idempotency_key,
        )
        if not payment.get("success"):
            logger.error(
                "Revel payment declined after order create (order_id=%s)",
                order.get("order_id"),
            )
            raise RevelLiveError(payment.get("message") or "Payment declined after order create")
        return {"order": order, "payment": payment}

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        self._require_configured()
        if not (order_id and order_id.isdigit()):
            return None
        return await self._live.fetch_order(order_id)

    async def update_order_status(self, order_id: str, status: str) -> Optional[Dict[str, Any]]:
        self._require_configured()
        if not order_id.isdigit():
            return None
        return await self._live.patch_order_status(order_id, status)

    async def process_payment(
        self,
        order_id: str,
        amount: float,
        payment_method: str = "card",
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_configured()
        return await self._live.process_payment(
            order_id,
            amount,
            payment_method,
            idempotency_key=idempotency_key,
        )

    async def confirm_payment(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        self._require_configured()
        return await self._live.fetch_payment(transaction_id)

    async def refund_payment(
        self,
        transaction_id: str,
        amount: Optional[float] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._require_configured()
        return await self._live.refund_payment(
            transaction_id,
            amount,
            idempotency_key=idempotency_key,
        )

    async def sync_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        self._require_configured()
        return await self._live.sync_customer_http(customer_data)


_revel_service: Optional[RevelService] = None


def get_revel_service() -> RevelService:
    global _revel_service
    if _revel_service is None:
        _revel_service = RevelService()
    return _revel_service
