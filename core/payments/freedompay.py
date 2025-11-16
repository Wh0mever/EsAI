from __future__ import annotations
import logging
from typing import Optional, Dict, Any

from django.conf import settings

from .models import PaymentLog
from users.models import User
from .freedompay_old import FreedomPayClient, FreedomPayError as OldFreedomPayError


logger = logging.getLogger("payments.freedompay")


def _mask_sensitive(obj: Any) -> Any:
    """Recursively mask tokens and auth values in dicts/lists/strings."""
    SENSITIVE_KEYS = {"token", "pg_token", "authorization", "Authorization"}
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if k in SENSITIVE_KEYS:
                # Keep type stable: mask strings, for others just replace with placeholder
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


class FreedomPayError(Exception):
    """Domain error for FreedomPay operations.

    Attributes:
    - message: human-readable error message
    - code: optional short machine code (e.g., "no_pay_token", "provider_error")
    - status_code: optional HTTP status from provider (if available)
    - details: optional dict payload with provider error/response
    """

    def __init__(self, message: str, code: str | None = None, status_code: int | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message

class FreedomPay:
    """FreedomPay recurring charge service.

    Uses:
    - Access token from env (handled by FreedomPayClient)
    - Saved user token from `User.pay_token`

    Always writes an audit row to `PaymentLog` with the provider response.
    Writes to payments.log; the full provider response is included only when DEBUG=True.
    """

    def __init__(self, user: User):
        self.user = user

    def charge(
        self,
        *,
        amount: int,
        currency: str,
        order_id: str,
        description: str = "",
        auto_clearing: int = 0,
        test: int = 0,
        custom_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Charge by saved user token (безакцептный платеж).

        - `amount` should be an integer in the smallest currency unit if required by the provider.
        - `currency` like "KGS", "RUB", etc.
        - `order_id` any unique ID for this charge.
        """

        token = (getattr(self.user, "pay_token", "") or "").strip()
        if not token:
            # Persist failed attempt and log
            try:
                # minimal request payload without token
                masked_request = {
                    "order_id": str(order_id),
                    "auto_clearing": auto_clearing,
                    "amount": int(amount),
                    "currency": currency,
                    "description": description or "",
                    "test": int(test),
                    "options": {
                        "custom_params": custom_params or {},
                        "user": {
                            "email": getattr(self.user, "email", None) or "",
                            "phone": getattr(self.user, "tel", None) or "",
                        },
                    },
                    "transaction": {"type": "bank_card_token", "options": {"token": "***"}},
                }
                PaymentLog.objects.create(
                    user=self.user,
                    provider="freedompay",
                    amount=int(amount),
                    currency=currency,
                    order_id=str(order_id),
                    description=description or "",
                    is_test=bool(test),
                    success=False,
                    request=masked_request,
                    response={},
                    error="User has no saved pay_token",
                )
            except Exception:
                # Avoid breaking flow if DB write fails
                pass
            logger.error(
                "charge_error user=%s order_id=%s error=%s",
                getattr(self.user, "id", None),
                order_id,
                "no_pay_token",
            )
            raise FreedomPayError("User has no saved pay_token", code="no_pay_token")

        # Construct request payload we are about to send (JSON mode schema)
        request_payload: Dict[str, Any] = {
            "order_id": str(order_id),
            "auto_clearing": auto_clearing,
            "amount": int(amount),
            "currency": currency,
            "description": description or "",
            "test": int(test),
            "options": {
                "custom_params": custom_params or {},
                "user": {
                    "email": getattr(self.user, "email", None) or "",
                    "phone": getattr(self.user, "tel", None) or "",
                },
            },
            "transaction": {"type": "bank_card_token", "options": {"token": token}},
        }
        masked_request = _mask_sensitive(request_payload)
        # Initialize client (may raise if env not configured)
        try:
            client = FreedomPayClient()
        except OldFreedomPayError as e:
            try:
                PaymentLog.objects.create(
                    user=self.user,
                    provider="freedompay",
                    amount=int(amount),
                    currency=currency,
                    order_id=str(order_id),
                    description=description or "",
                    is_test=bool(test),
                    success=False,
                    request=masked_request,
                    response={},
                    error=str(e),
                )
            except Exception:
                pass
            logger.error(
                "charge_error user=%s order_id=%s error=%s",
                getattr(self.user, "id", None),
                order_id,
                str(e),
            )
            raise FreedomPayError(str(e), code="config")
        try:
            data = client.charge_by_token(
                token=token,
                amount=int(amount),
                currency=currency,
                order_id=str(order_id),
                description=description,
                auto_clearing=auto_clearing,
                test=test,
                user={
                    "email": getattr(self.user, "email", None) or "",
                    "phone": getattr(self.user, "tel", None) or "",
                },
                custom_params=custom_params or {},
            )
        except OldFreedomPayError as e:
            # Business error from provider or config; persist and log
            try:
                PaymentLog.objects.create(
                    user=self.user,
                    provider="freedompay",
                    amount=int(amount),
                    currency=currency,
                    order_id=str(order_id),
                    description=description or "",
                    is_test=bool(test),
                    success=False,
                    request=masked_request,
                    response={},
                    error=str(e),
                )
            except Exception:
                pass
            logger.error(
                "charge_error user=%s order_id=%s error=%s",
                getattr(self.user, "id", None),
                order_id,
                str(e),
            )
            raise FreedomPayError(str(e), code="provider_error")
        except Exception as e:
            # Unexpected error; persist and log with stacktrace
            try:
                PaymentLog.objects.create(
                    user=self.user,
                    provider="freedompay",
                    amount=int(amount),
                    currency=currency,
                    order_id=str(order_id),
                    description=description or "",
                    is_test=bool(test),
                    success=False,
                    request=masked_request,
                    response={},
                    error=str(e),
                )
            except Exception:
                pass
            logger.exception(
                "charge_exception user=%s order_id=%s",
                getattr(self.user, "id", None),
                order_id,
            )
            raise

        # Success path: persist provider response ALWAYS
        try:
            PaymentLog.objects.create(
                user=self.user,
                provider="freedompay",
                amount=int(amount),
                currency=currency,
                order_id=str(order_id),
                description=description or "",
                is_test=bool(test),
                success=True,
                request=masked_request,
                response=data if isinstance(data, dict) else {"data": data},
                error=None,
            )
        except Exception:
            pass

        # Log to file. Include full response only in DEBUG.
        if settings.DEBUG:
            logger.info(
                "charge_success user=%s order_id=%s amount=%s %s data=%s",
                getattr(self.user, "id", None),
                order_id,
                amount,
                currency,
                data,
            )
        else:
            logger.info(
                "charge_success user=%s order_id=%s amount=%s %s",
                getattr(self.user, "id", None),
                order_id,
                amount,
                currency,
            )

        return data
