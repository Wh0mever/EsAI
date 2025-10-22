from __future__ import annotations
import os
from typing import Any, Dict, Optional
import httpx


class FreedomPayError(Exception):
    pass


def _env(key: str, default: Optional[str] = None) -> str:
    v = os.environ.get(key, default)
    if v is None:
        raise FreedomPayError(f"Missing env: {key}")
    return v


class FreedomPayClient:
    """Minimal client for recurring (безакцептные) charges by saved token.

    Note:
    - API base/endpoint can differ; configure one of:
      - FREEDOM_PAY_CHARGE_URL: full URL for charge-by-token endpoint
      - FREEDOM_PAY_API_BASE: base URL; we will POST to `${base}/payments/charge` (adjust as per docs)
    - FREEDOM_PAY_TOKEN: Bearer/API token per FreedomPay docs.
    """

    def __init__(self, *, charge_url: Optional[str] = None, api_base: Optional[str] = None, token: Optional[str] = None, timeout: float = 15.0):
        self.charge_url = charge_url or os.environ.get("FREEDOM_PAY_CHARGE_URL")
        self.api_base = api_base or os.environ.get("FREEDOM_PAY_API_BASE")
        self.token = (token or os.environ.get("FREEDOM_PAY_TOKEN") or "").strip()
        if not self.charge_url and not self.api_base:
            # Leave explicit to force configuration
            raise FreedomPayError("Configure FREEDOM_PAY_CHARGE_URL or FREEDOM_PAY_API_BASE")
        if not self.token:
            raise FreedomPayError("Missing FREEDOM_PAY_TOKEN")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        # Adjust if provider expects different header key
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _charge_endpoint(self) -> str:
        if self.charge_url:
            return self.charge_url
        # Fallback pattern — update to the exact path from docs if needed
        base = self.api_base.rstrip("/")
        return f"{base}/payments/charge"

    def charge_by_token(
        self,
        *,
        token: str,
        amount: int,
        currency: str,
        order_id: str,
        description: str = "",
        auto_clearing: int = 0,
        test: int = 0,
        user: Optional[Dict[str, Any]] = None,
        custom_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Merchant-initiated payment using previously saved token (безакцептный).

        amount is in minor units used by FP SDK (for KGS it is integer som units).
        """
        endpoint = self._charge_endpoint()

        payload = {
            "order_id": str(order_id),
            "auto_clearing": auto_clearing,
            "amount": int(amount),
            "currency": currency,
            "description": description or "",
            "test": int(test),
            "options": {
                "custom_params": custom_params or {},
                "user": user or {},
            },
            # Transaction entity: pay by saved token (no CVV, no 3DS expected)
            "transaction": {
                "type": "bank_card_token",
                "options": {"token": token},
            },
        }

        # Some APIs expect transaction object separately; if docs require, adjust here.
        # We send as a single JSON body typical for FreedomPay JS signature.

        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(endpoint, json=payload, headers=self._headers())
            try:
                data = r.json()
            except Exception:
                data = {"status_code": r.status_code, "text": r.text}
            if r.status_code >= 400:
                raise FreedomPayError(f"Charge error: {data}")
            return data


def charge_recurring_by_user_token(*, user, amount: int, currency: str, order_id: str, description: str = "", **kwargs) -> Dict[str, Any]:
    token = (getattr(user, "pay_token", None) or "").strip()
    if not token:
        raise FreedomPayError("User has no saved pay_token")
    client = FreedomPayClient()
    return client.charge_by_token(
        token=token,
        amount=amount,
        currency=currency,
        order_id=order_id,
        description=description,
        **kwargs,
    )

