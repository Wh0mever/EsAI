import logging
import uuid
import hashlib
from typing import Optional, Dict, Any

import requests
from django.conf import settings
from django.db import DatabaseError, connection

from .models import Payment
from users.models import User


logger = logging.getLogger("payments.freedompay")


def make_signature(method: str, params: dict, secret_key: str) -> str:

    params = {k: v for k, v in params.items() if k != "pg_sig"}

    values = [method]

    for key in sorted(params.keys()):
        values.append(str(params[key]))

    values.append(secret_key)

    raw = ";".join(values)

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mask_sensitive(obj: Any) -> Any:
    """Recursively mask tokens and auth values in dicts/lists/strings."""
    sensitive_keys = {"token", "pg_token", "authorization", "Authorization"}
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if k in sensitive_keys:
                if isinstance(v, str):
                    if v.lower().startswith("bearer "):
                        masked[k] = "Bearer ***"
                    else:
                        masked[k] = "***"
                else:
                    masked[k] = "***"
            else:
                masked[k] = _mask_sensitive(v)
        return masked
    if isinstance(obj, list):
        return [_mask_sensitive(v) for v in obj]
    return obj


class FreedomPay:
    def __init__(self, user: User):
        self.user = user
        self.salt = uuid.uuid4().hex
        self.payment: Optional[Payment] = None
        self.request_data: Dict[str, Any] = {}

    def _build_request_data(
        self,
        *,
        amount: int,
        currency: str,
        order_id: str,
        description: str = "",
        test: int = 0,
        custom_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build API request payload and create a Payment log row.

        DB errors here are allowed to propagate to the caller; views with
        ATOMIC_REQUESTS should handle rollback as needed.
        """
        is_test = bool(test or settings.DEBUG)
        self.payment = Payment.objects.create(
            user=self.user,
            amount=int(amount),
            currency=currency,
            order_id=order_id,
            description=description,
            is_test=is_test,
        )

        data: Dict[str, Any] = {
            "pg_merchant_id": settings.FREEDOM_PAY_MERCHANT_ID,
            "pg_amount": str(amount),
            "pg_currency": currency,
            "pg_order_id": order_id or str(self.payment.id),
            "pg_user_id": str(self.user.id),
            "pg_card_token": self.user.pay_token,
            "pg_description": description or f"Payment for user {self.user.id}",
            "pg_salt": self.salt,
        }

        data["pg_sig"] = make_signature(
            method="create",
            params=data,
            secret_key=settings.FREEDOM_PAY_TOKEN
        )

        self.request_data = data
        return data

    def charge(
        self,
        *,
        amount: int,
        currency: str,
        order_id: str,
        description: str = "",
        test: int = 0,
        custom_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Charge the user's saved payment method and log the result."""

        try:
            request_data = self._build_request_data(
                amount=amount,
                currency=currency,
                order_id=order_id,
                description=description,
                custom_params=custom_params,
            )
        except DatabaseError:
            logger.exception("FreedomPay failed to create Payment")
            raise

        logger.debug("FreedomPay charge request data: %s", _mask_sensitive(request_data))

        try:
            response = requests.post(
                f"{settings.FREEDOM_PAY_API_BASE}/merchant/{settings.FREEDOM_PAY_MERCHANT_ID}/card/init",
                data=request_data,
                timeout=30,
            )
            try:
                response_data = response.json()
            except Exception:
                response_data = {"raw": response.text}

            logger.debug("FreedomPay charge response data: %s", _mask_sensitive(response_data))
        except Exception as e:
            logger.exception("FreedomPay HTTP request failed")
            # Network-level failure: best-effort log into Payment and return error dict.
            try:
                if self.payment is not None:
                    self.payment.request = self.request_data
                    self.payment.success = False
                    self.payment.error = str(e)
                    self.payment.save(update_fields=["request", "success", "error"])
            except DatabaseError:
                # Reset broken transaction if ATOMIC_REQUESTS is on.
                try:
                    connection.rollback()
                except Exception:
                    pass
            return {"error": str(e)}

        # Persist provider response; let DB errors bubble up.
        if self.payment is not None:
            self.payment.request = self.request_data
            self.payment.response = response_data
            if response.status_code == 200 and response_data.get("pg_status") == "success":
                self.payment.success = True
                self.payment.error = ""
            else:
                self.payment.success = False
                self.payment.error = response_data.get("pg_error_message", "Unknown error")
            self.payment.save(update_fields=["request", "response", "success", "error"])

        return response_data
