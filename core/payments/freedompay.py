from __future__ import annotations
import os
from typing import Any, Dict, Optional, List, Tuple
import httpx
import hashlib
import uuid
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


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
        self.pg_enabled = str(os.environ.get("FREEDOM_PAY_USE_PG", "0")).lower() in ("1", "true", "yes")
        self.pg_merchant_id = os.environ.get("FREEDOM_PAY_MERCHANT_ID")
        self.pg_secret = os.environ.get("FREEDOM_PAY_SECRET_KEY")
        self.pg_sig_algo = (os.environ.get("FREEDOM_PAY_SIGNATURE_ALGO") or "md5").lower()
        if not self.charge_url and not self.api_base:
            # Leave explicit to force configuration
            raise FreedomPayError("Configure FREEDOM_PAY_CHARGE_URL or FREEDOM_PAY_API_BASE")
        # Token is only required for JSON/SDK-style backend. For PG mode we rely on merchant/secret.
        if not self.pg_enabled and not self.token:
            raise FreedomPayError("Missing FREEDOM_PAY_TOKEN")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        # JSON mode headers. Paybox mode posts urlencoded and doesn't use Bearer.
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

    # ---------- Paybox-style helpers (pg_*) ----------
    @staticmethod
    def _pg_collect_values(params: Any) -> List[str]:
        # Recursively collect values in alphabetical key order, per typical Paybox sig rules
        if isinstance(params, dict):
            items = []
            for k in sorted(params.keys()):
                if k == "pg_sig":
                    continue
                items.extend(FreedomPayClient._pg_collect_values(params[k]))
            return items
        if isinstance(params, (list, tuple)):
            items = []
            for v in params:
                items.extend(FreedomPayClient._pg_collect_values(v))
            return items
        return ["" if params is None else str(params)]

    def _pg_sign(self, method_name: str, params: Dict[str, Any]) -> str:
        values = self._pg_collect_values(params)
        base: List[str] = [method_name] + values + [self.pg_secret or ""]
        s = ";".join(base)
        if self.pg_sig_algo == "sha256":
            return hashlib.sha256(s.encode("utf-8")).hexdigest()
        # default md5
        return hashlib.md5(s.encode("utf-8")).hexdigest()  # nosec B303

    @staticmethod
    def _pg_method_from_url(url: str) -> str:
        path = urlparse(url).path
        return path.rsplit("/", 1)[-1] or path

    def _charge_by_token_pg(self, *, token: str, amount: int, currency: str, order_id: str, description: str = "", test: int = 0, auto_clearing: int = 0, user: Optional[Dict[str, Any]] = None, custom_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.pg_merchant_id or not self.pg_secret:
            raise FreedomPayError("Missing FREEDOM_PAY_MERCHANT_ID or FREEDOM_PAY_SECRET_KEY for PG mode")
        endpoint = self._charge_endpoint()
        method = self._pg_method_from_url(endpoint)

        params: Dict[str, Any] = {
            "pg_merchant_id": self.pg_merchant_id,
            "pg_order_id": str(order_id),
            "pg_amount": str(int(amount)),  # adjust formatting if provider expects decimal
            "pg_currency": currency,
            "pg_description": description or "",
            "pg_salt": uuid.uuid4().hex,
            # recurring by saved token
            "pg_token": token,
            # optional flags
            "pg_testing_mode": int(test),
            "pg_auto_clearing": int(auto_clearing),
        }
        if user:
            if user.get("email"):
                params["pg_user_email"] = user["email"]
            if user.get("phone"):
                params["pg_user_phone"] = user["phone"]
        # custom params are usually passed as pg_user_params[...] but depends on docs
        if custom_params:
            for k, v in custom_params.items():
                params[f"pg_user_param_{k}"] = v

        params["pg_sig"] = self._pg_sign(method, params)

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(endpoint, data=params, headers=headers)
            # Expect XML response with pg_status, pg_error_code, ...
            try:
                root = ET.fromstring(r.text)
                data = {child.tag: child.text for child in root}
            except Exception:
                data = {"status_code": r.status_code, "text": r.text}
            if r.status_code >= 400:
                raise FreedomPayError(f"Charge error: {data}")
            return data

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

        Two protocols supported:
        - JSON (SDK-compatible) using Bearer token (legacy in our code)
        - Paybox-style (pg_*) form with signature as per docs
        """
        if self.pg_enabled:
            return self._charge_by_token_pg(
                token=token,
                amount=amount,
                currency=currency,
                order_id=order_id,
                description=description,
                test=test,
                auto_clearing=auto_clearing,
                user=user,
                custom_params=custom_params,
            )

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
            "transaction": {"type": "bank_card_token", "options": {"token": token}},
        }
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(endpoint, json=payload, headers=self._headers())
            try:
                data = r.json()
            except Exception:
                data = {"status_code": r.status_code, "text": r.text}
            if r.status_code >= 400:
                raise FreedomPayError(f"Charge error: {data}")
            return data


def charge_recurring_by_user_token(
    *,
    user,
    amount: int,
    currency: str,
    order_id: str,
    description: str = "",
    fp_user: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
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
        user=fp_user,
        **kwargs,
    )
