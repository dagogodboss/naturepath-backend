"""
Payment link provider abstraction.

Phase 2 default provider is Revel hosted payment links.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from core.config import Settings, get_settings
from infrastructure.external.revel_live_client import _auth_headers, _resources_base


@dataclass
class PaymentLink:
    link_id: str
    url: str
    status: str
    expires_at: Optional[str] = None
    provider_payload: Optional[Dict[str, Any]] = None


class PaymentLinkProvider(ABC):
    @abstractmethod
    async def create_link(
        self,
        order_ref: str,
        amount: float,
        currency: str,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentLink:
        raise NotImplementedError

    @abstractmethod
    async def get_link(self, link_id: str) -> Optional[PaymentLink]:
        raise NotImplementedError

    @abstractmethod
    async def cancel_link(self, link_id: str) -> bool:
        raise NotImplementedError


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RevelHostedPaymentProvider(PaymentLinkProvider):
    """
    Revel hosted link wrapper.

    Expected endpoint is configured via `settings.revel_hosted_payment_endpoint` and
    supports:
      POST {endpoint} with {order, amount, currency, metadata}
      GET {endpoint}/{link_id}/
      PATCH {endpoint}/{link_id}/ with {"status": "cancelled"}
    """

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._base = _resources_base(self._settings)
        endpoint = (self._settings.revel_hosted_payment_endpoint or "").strip().strip("/")
        self._endpoint = endpoint or "HostedPaymentLink"

    def _require_configured(self) -> None:
        if not self._settings.revel_enable_hosted_payments:
            raise RuntimeError("Revel hosted payments are disabled until endpoint contract is verified")
        if not self._base:
            raise RuntimeError("Revel REST base URL is not configured")
        if self._settings.revel_api_key in (None, "", "mock_revel_key"):
            raise RuntimeError("Revel API key is not configured")
        if self._settings.revel_api_secret in (None, "", "mock_revel_secret"):
            raise RuntimeError("Revel API credentials are not configured")

    def _endpoint_url(self) -> str:
        return f"{self._base}{self._endpoint}/"

    @staticmethod
    def _normalize_link(payload: Dict[str, Any]) -> PaymentLink:
        link_id = str(payload.get("id") or payload.get("link_id") or "")
        url = str(payload.get("url") or payload.get("hosted_url") or payload.get("payment_url") or "")
        status = str(payload.get("status") or "active").lower()
        expires_at = payload.get("expires_at") or payload.get("expiration") or payload.get("expires")
        return PaymentLink(
            link_id=link_id,
            url=url,
            status=status,
            expires_at=str(expires_at) if expires_at else None,
            provider_payload=payload,
        )

    async def create_link(
        self,
        order_ref: str,
        amount: float,
        currency: str,
        metadata: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> PaymentLink:
        self._require_configured()
        body: Dict[str, Any] = {
            "order": order_ref,
            "amount": f"{float(amount):.2f}",
            "currency": currency,
            "metadata": metadata or {},
            "requested_at": _now_iso(),
        }
        headers = dict(_auth_headers(self._settings))
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        async with httpx.AsyncClient(timeout=self._settings.revel_http_timeout_seconds) as client:
            resp = await client.post(self._endpoint_url(), json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("Unexpected Revel hosted payment response shape")
        out = self._normalize_link(data)
        if not out.link_id or not out.url:
            raise RuntimeError("Revel hosted payment response missing link id/url")
        return out

    async def get_link(self, link_id: str) -> Optional[PaymentLink]:
        self._require_configured()
        if not link_id:
            return None
        async with httpx.AsyncClient(timeout=self._settings.revel_http_timeout_seconds) as client:
            resp = await client.get(
                f"{self._endpoint_url()}{link_id}/",
                headers=_auth_headers(self._settings),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, dict):
            return None
        return self._normalize_link(data)

    async def cancel_link(self, link_id: str) -> bool:
        self._require_configured()
        if not link_id:
            return False
        async with httpx.AsyncClient(timeout=self._settings.revel_http_timeout_seconds) as client:
            resp = await client.patch(
                f"{self._endpoint_url()}{link_id}/",
                json={"status": "cancelled"},
                headers=_auth_headers(self._settings),
            )
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
        return True


_payment_link_provider: Optional[PaymentLinkProvider] = None


def get_payment_link_provider() -> PaymentLinkProvider:
    global _payment_link_provider
    if _payment_link_provider is None:
        _payment_link_provider = RevelHostedPaymentProvider()
    return _payment_link_provider
