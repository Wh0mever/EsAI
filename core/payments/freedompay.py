import logging
import uuid
import hashlib
from typing import Optional, Dict, Any
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import DatabaseError, connection

from .models import Payment
from users.models import User


logger = logging.getLogger("payments.freedompay")


def extract_script_name(url: str) -> str:
    """Return script name from URL or path."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    path = parsed.path or raw.split("?", 1)[0]
    path = path.rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


def make_signature(script_name: str, params: dict, secret_key: str) -> str:
    filtered = {k: v for k, v in (params or {}).items() if k != "pg_sig"}
    script = extract_script_name(script_name) or (script_name or "").strip()
    pieces = [script]
    for key in sorted(filtered.keys()):
        value = filtered[key]
        pieces.append("" if value is None else str(value))
    pieces.append(secret_key or "")
    raw = ";".join(pieces)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


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


class FreedomPayError(Exception):
    """FreedomPay request failed."""


class FreedomPayHPPClient:
    """FreedomPay Hosted Payment Page client."""

    def __init__(self):
        self.merchant_id = (settings.FP_MERCHANT_ID or "").strip()
        self.secret = (settings.FP_SECRET or "").strip()
        self.base_url = (settings.FP_API_BASE or settings.FREEDOM_PAY_API_BASE or "").rstrip("/")
        self.last_request: Dict[str, Any] = {}
        self.last_response: Dict[str, Any] = {}
        self.last_endpoint: str = ""

        missing = [
            name for name, value in (
                ("FP_MERCHANT_ID", self.merchant_id),
                ("FP_SECRET", self.secret),
                ("FP_API_BASE", self.base_url),
            )
            if not value
        ]
        if missing:
            raise FreedomPayError(f"FreedomPay config missing: {', '.join(missing)}")

    def sign(self, params: Dict[str, Any], script: str) -> str:
        allowed_keys = ("pg_user_id", "pg_order_id", "pg_salt", "pg_post_link", "pg_back_link")
        subset = {key: params.get(key) for key in allowed_keys if key in params}
        return make_signature(script, subset, self.secret)

    def request(self, script: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/merchant/{self.merchant_id}/{script}".replace("//merchant", "/merchant")
        self.last_endpoint = url
        self.last_response = {}
        if settings.DEBUG:
            logger.info("FreedomPay bind request url=%s payload=%s", url, _mask_sensitive(params))
        try:
            response = requests.post(url, data=params, timeout=30)
        except requests.RequestException as exc:
            logger.exception("FreedomPay HPP HTTP error")
            raise FreedomPayError("FreedomPay request failed") from exc
        try:
            data = response.json()
        except ValueError:
            try:
                text = (response.text or "").strip()
                root = ET.fromstring(text)
                if list(root):
                    data = {child.tag: (child.text or "").strip() for child in root}
                else:
                    data = {root.tag: (root.text or "").strip()}
            except ET.ParseError as exc:
                logger.exception("FreedomPay HPP invalid response: %s", response.text[:200])
                self.last_response = {"raw": response.text[:200]}
                raise FreedomPayError("FreedomPay response parsing failed") from exc
        except Exception as exc:
            logger.exception("FreedomPay HPP response decode error: %s", response.text[:200])
            self.last_response = {"raw": response.text[:200]}
            raise FreedomPayError("FreedomPay response parsing failed") from exc

        self.last_response = _mask_sensitive(data)
        if settings.DEBUG:
            logger.info(
                "FreedomPay bind response url=%s status=%s payload=%s",
                self.last_endpoint,
                response.status_code,
                self.last_response,
            )
        if response.status_code >= 400:
            error_message = (
                data.get("pg_error_description")
                or data.get("pg_error_message")
                or response.text
                or "FreedomPay rejected the request"
            )
            raise FreedomPayError(error_message)
        return data

    def start_card_bind(
        self,
        user_id: int,
        order_id: Optional[str] = None,
        *,
        post_link: str,
        back_link: str,
    ) -> str:
        script_path = "cardstorage/add"
        script_name = "add"
        pg_order_id = order_id or f"bind-{user_id}-{uuid.uuid4().hex}"
        if not post_link or not back_link:
            raise FreedomPayError("FreedomPay callback/back links are required")
        params: Dict[str, Any] = {
            "pg_merchant_id": self.merchant_id,
            "pg_user_id": str(user_id),
            "pg_order_id": pg_order_id,
            "pg_post_link": post_link,
            "pg_back_link": back_link,
            "pg_salt": uuid.uuid4().hex,
        }
        params["pg_sig"] = self.sign(params, script_name)
        self.last_request = _mask_sensitive(dict(params))
        if settings.DEBUG:
            logger.info("FreedomPay bind request payload=%s", self.last_request)
        data = self.request(script_path, params)
        pg_status = str(data.get("pg_status") or "").lower()
        if pg_status not in ("ok", "success"):
            message = (
                data.get("pg_error_description")
                or data.get("pg_error_message")
                or "FreedomPay declined card binding session"
            )
            raise FreedomPayError(message)
        redirect_url = data.get("pg_redirect_url")
        if not redirect_url:
            raise FreedomPayError("FreedomPay did not return redirect URL")
        return str(redirect_url)


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

        api_base = (settings.FREEDOM_PAY_API_BASE or "").rstrip("/")
        endpoint = f"{api_base}/merchant/{settings.FREEDOM_PAY_MERCHANT_ID}/card/init"

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

        data["pg_sig"] = make_signature(extract_script_name(endpoint), data, settings.FREEDOM_PAY_TOKEN)

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
            api_base = (settings.FREEDOM_PAY_API_BASE or "").rstrip("/")
            endpoint = f"{api_base}/merchant/{settings.FREEDOM_PAY_MERCHANT_ID}/card/init"
            response = requests.post(
                endpoint,
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
