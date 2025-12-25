import logging
import uuid
import hashlib
from decimal import Decimal
from typing import Optional, Dict, Any
from urllib.parse import urlsplit, urljoin
import xml.etree.ElementTree as ET
import requests
from django.conf import settings
from django.urls import reverse
from django.db import DatabaseError, connection

from .models import Payment
from users.models import User, UserCardBind
from users.services import activate_free_plan_for_user
from plans.models import CurrencyRate

logger = logging.getLogger("payments.freedompay")


def extract_script_name(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    path = parsed.path or raw.split("?", 1)[0]
    path = path.rstrip("/")
    if not path:
        return ""
    parts = [segment for segment in path.split("/") if segment]
    if not parts:
        return ""

    # имя файла
    tail = parts[-1]

    # cardstorage/add → add
    if len(parts) >= 2 and parts[-2] == "cardstorage" and tail == "add":
        return "add"

    # card/init → init
    if len(parts) >= 2 and parts[-2] == "card" and tail == "init":
        return "init"

    # card/direct → direct
    if len(parts) >= 2 and parts[-2] == "card" and tail == "direct":
        return "direct"

    # fallback
    return tail

def parse_freedompay_callback(payload) -> dict:
    """
    Extracts and parses pg_xml from request.data and returns a dict.
    payload = request.data (QueryDict or dict)
    """
    pg_xml_raw = payload.get("pg_xml")
    if not pg_xml_raw:
        return {}

    # FreedomPay sometimes sends as list: {'pg_xml': ['<xml...>']}
    if isinstance(pg_xml_raw, list):
        pg_xml_raw = pg_xml_raw[0]

    try:
        root = ET.fromstring(pg_xml_raw)
    except Exception:
        return {}

    result = {}
    for child in root:
        result[child.tag] = (child.text or "").strip()

    return result

def make_api_signature(script_name: str, params: Dict[str, Any], secret_key: str) -> str:
    filtered = {
        k: v for k, v in (params or {}).items()
        if k != "pg_sig" and v is not None
    }
    script = extract_script_name(script_name) or script_name or ""
    pieces = [script]
    for key in sorted(filtered.keys()):
        pieces.append(str(filtered[key]))
    pieces.append(secret_key or "")
    raw = ";".join(pieces)
    if settings.DEBUG:
        logger.warning("FreedomPay API signature base string: %s", raw)
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

def save_freedompay_callback(callback_data: Dict[str, Any]) -> None:

    data = parse_freedompay_callback(callback_data)

    # {'pg_card_hash': '4111-11XX-XXXX-1111', 'pg_card_month': '12', 'pg_card_year': '30', 'pg_bank': '<bank>', 'pg_country': 'CA', 'pg_card_3ds': '0', 'pg_status': 'success', 'pg_card_id': '<card_id>', 'pg_card_token': '<card-token-uuid>', 'pg_user_id': '<user_id>',}
    
    if not data or data.get("pg_status") != "success":
        logger.warning("FreedomPay callback with invalid or failed status: %s", data)
        return False
    
    try:
        user = User.objects.get(id=int(data.get("pg_user_id")))
        UserCardBind.objects.create(
            user=user,
            card_token=data.get("pg_card_token", ""),
            card_hash=data.get("pg_card_hash", ""),
            card_month=data.get("pg_card_month", ""),
            card_year=data.get("pg_card_year", ""),
            card_bank=data.get("pg_bank", ""),
            card_country=data.get("pg_country", ""),
            card_3ds=bool(int(data.get("pg_card_3ds", "0"))),
        )
        try:
            activate_free_plan_for_user(user)
        except Exception:
            logger.exception("Failed to auto-activate free plan for user=%s", user.id)
        return True
    except Exception as e:
        logger.exception("Failed to save FreedomPay card bind: %s", e)
        return False

class FreedomPayError(Exception):
    """FreedomPay request failed."""

class FreedomPayHPPClient:
    """FreedomPay Hosted Payment Page client."""

    def __init__(self):
        self.merchant_id = (settings.FP_MERCHANT_ID or "").strip()
        self.secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
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

    # ----------------------------- SIGNATURE (ADD) -----------------------------
    
    def sign_add(self, params: Dict[str, Any]) -> str:
        filtered = {k: v for k, v in params.items() if k != "pg_sig"}
        pieces = ["add"]
        for key in sorted(filtered.keys()):
            pieces.append(str(filtered[key]))
        pieces.append(self.secret)
        raw = ";".join(pieces)
        logger.warning("FreedomPay ADD signature base: %s", raw)
        return hashlib.md5(raw.encode()).hexdigest()

    # ----------------------------- HTTP REQUEST -----------------------------

    def request(self, script: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/merchant/{self.merchant_id}/{script}".replace("//merchant", "/merchant")
        self.last_endpoint = url
        self.last_response = {}

        if settings.DEBUG:
            logger.info("FreedomPay request url=%s payload=%s", url, _mask_sensitive(params))

        try:
            response = requests.post(url, data=params, timeout=30)
        except requests.RequestException:
            logger.exception("FreedomPay HPP HTTP error")
            raise FreedomPayError("FreedomPay request failed")

        # Try parse JSON first, then XML
        try:
            data = response.json()
        except ValueError:
            try:
                root = ET.fromstring(response.text)
                if list(root):
                    data = {child.tag: (child.text or "").strip() for child in root}
                else:
                    data = {root.tag: (root.text or "").strip()}
            except Exception:
                logger.exception("FreedomPay HPP invalid response: %s", response.text[:200])
                raise FreedomPayError("FreedomPay response parsing failed")

        self.last_response = _mask_sensitive(data)

        if settings.DEBUG:
            logger.info(
                "FreedomPay response url=%s status=%s payload=%s",
                self.last_endpoint,
                response.status_code,
                self.last_response,
            )

        if response.status_code >= 400:
            raise FreedomPayError(
                data.get("pg_error_description")
                or data.get("pg_error_message")
                or "FreedomPay rejected the request"
            )

        return data

    # ----------------------------- BIND CARD -----------------------------

    def start_card_bind(
        self,
        user_id: int,
        *,
        post_link: str,
        back_link: str,
    ) -> str:
        """
        Start card binding session (cardstorage/add)
        """
        script_path = "cardstorage/add"

        if not post_link or not back_link:
            raise FreedomPayError("FreedomPay callback/back links are required")

        params: Dict[str, Any] = {
            "pg_merchant_id": self.merchant_id,
            "pg_user_id": str(user_id),
            "pg_post_link": post_link,
            "pg_back_link": back_link,
            "pg_salt": uuid.uuid4().hex,
        }


        # SIGNATURE FOR ADD
        params["pg_sig"] = self.sign_add(params)

        self.last_request = _mask_sensitive(dict(params))

        if settings.DEBUG:
            logger.warning("FreedomPay bind request payload=%s", self.last_request)

        data = self.request(script_path, params)

        pg_status = str(data.get("pg_status") or "").lower()
        if pg_status not in ("ok", "success"):
            raise FreedomPayError(
                data.get("pg_error_description")
                or data.get("pg_error_message")
                or "FreedomPay declined card binding session"
            )

        redirect_url = data.get("pg_redirect_url")
        if not redirect_url:
            raise FreedomPayError("FreedomPay did not return redirect URL")

        return str(redirect_url)

class FreedomPay:
    def __init__(self, user: User):
        self.user = user
        self.base_url = (settings.FREEDOM_PAY_API_BASE or "").rstrip("/")
        self.merchant_id = (settings.FREEDOM_PAY_MERCHANT_ID or "").strip()
        self.secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
        self.logger = logging.getLogger("payments.freedompay")
        self.payment: Optional[Payment] = None
        self._requests: Dict[str, Dict[str, Any]] = {}
        self._responses: Dict[str, Dict[str, Any]] = {}

    def _ensure_config(self) -> None:
        if not (self.base_url and self.merchant_id and self.secret):
            raise FreedomPayError("FreedomPay configuration is incomplete")
        if not (settings.SITE_BASE_URL or "").strip():
            raise FreedomPayError("SITE_BASE_URL is required for callback URLs")

    def _normalize_amount(self, amount: Decimal | int | float | str) -> Decimal:
        try:
            value = Decimal(str(amount)).quantize(Decimal("0.01"))
        except Exception:
            raise FreedomPayError("Invalid amount")
        if value < Decimal("0.01"):
            raise FreedomPayError("Amount must be at least 0.01")
        return value

    def _apply_user_currency(self, amount: Decimal, currency: str) -> tuple[Decimal, str]:
        selected = (getattr(self.user, "selected_currency", "") or "").strip().upper()
        base_currency = (currency or "").strip().upper()
        if not selected:
            return amount, base_currency
        if selected == base_currency:
            return amount, base_currency
        if selected == "USD":
            return amount, "USD"

        rate = CurrencyRate.objects.filter(currency=selected).values_list("rate_to_usd", flat=True).first()
        if not rate:
            logger.warning("Currency rate missing for %s; fallback to %s", selected, base_currency)
            return amount, base_currency

        try:
            rate_dec = Decimal(str(rate))
            if rate_dec <= 0:
                raise ValueError("rate_to_usd must be positive")
            converted = amount / rate_dec  # rate_to_usd: 1 unit currency in USD
            return self._normalize_amount(converted), selected
        except Exception as exc:
            logger.warning("Currency conversion failed for %s: %s", selected, exc)
            return amount, base_currency

    def _fetch_card_token(self) -> str:
        card = UserCardBind.objects.filter(user=self.user).order_by("-created_at").first()
        token = (card.card_token or "").strip() if card else ""
        if not token:
            raise FreedomPayError("Card token not found")
        return token

    def _mask(self, data: Dict[str, Any]) -> Dict[str, Any]:
        masked = {}
        for key, value in data.items():
            if key in {"pg_card_token", "pg_sig"} and isinstance(value, str):
                masked[key] = "***"
            else:
                masked[key] = value
        return masked

    def _callback_url(self, name: str) -> str:
        base = (settings.SITE_BASE_URL or "").rstrip("/")
        path = reverse(f"payments:{name}")
        return urljoin(f"{base}/", path.lstrip("/"))

    def _parse_xml_response(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {"raw": raw}
        try:
            root = ET.fromstring(text)
        except Exception:
            return {"raw": raw}
        result: Dict[str, Any] = {}
        for child in root:
            result[child.tag] = (child.text or "").strip()
        if not result:
            result[root.tag] = (root.text or "").strip()
        return result

    def _request(self, script: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["pg_salt"] = uuid.uuid4().hex
        payload["pg_sig"] = make_api_signature(script, payload, self.secret)

        url = f"{self.base_url}/merchant/{self.merchant_id}/card/{script}"
        masked_payload = self._mask(payload)
        self.logger.warning(
            "FreedomPay %s request user=%s order=%s payload=%s",
            script,
            self.user.id,
            payload.get("pg_order_id"),
            masked_payload,
        )
        try:
            response = requests.post(url, data=payload, timeout=30)
        except requests.RequestException as exc:
            raise FreedomPayError(f"{script}_request_failed:{exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = self._parse_xml_response(response.text)
        except Exception:
            body = {"raw": response.text}

        self.logger.warning(
            "FreedomPay %s response user=%s order=%s status=%s body=%s",
            script,
            self.user.id,
            payload.get("pg_order_id"),
            response.status_code,
            body,
        )

        self._requests[script] = masked_payload
        self._responses[script] = body

        if response.status_code >= 400:
            raise FreedomPayError(f"{script}_http_error:{response.status_code}")

        status = (body.get("pg_status") or "").lower()
        if status != "ok":
            raise FreedomPayError(f"{script}_status_error:{status or 'unknown'}")
        if script == "direct":
            trx_status = (body.get("pg_transaction_status") or "").lower()
            if trx_status != "ok":
                raise FreedomPayError(f"transaction_status_error:{trx_status or 'unknown'}")

        if body.get("pg_payment_id"):
            payload["pg_payment_id"] = body["pg_payment_id"]
        return body

    def _create_payment_log(self, *, amount_major: Decimal, currency: str, order_id: str, description: str, test: bool) -> None:
        self.payment = Payment.objects.create(
            user=self.user,
            amount=amount_major,
            currency=currency,
            order_id=order_id,
            description=description,
            is_test=test,
        )

    def _finalize_payment(self, success: bool, error: str = "") -> None:
        if not self.payment:
            return
        self.payment.request = self._requests
        self.payment.response = self._responses
        self.payment.success = success
        self.payment.error = error or ""
        self.payment.save(update_fields=["request", "response", "success", "error"])

    def charge(
        self,
        *,
        amount: Decimal | int | float | str,
        currency: str,
        order_id: str,
        description: str = "",
        card_token: Optional[str] = None,
        test: bool = False,
    ) -> Dict[str, Any]:
        self._ensure_config()
        normalized_amount = self._normalize_amount(amount)
        currency_code = (currency or "").upper()
        if not currency_code:
            raise FreedomPayError("Currency is required")
        normalized_amount, currency_code = self._apply_user_currency(normalized_amount, currency_code)
        order_id = (order_id or "").strip()
        if not order_id:
            raise FreedomPayError("Order ID is required")
        token = (card_token or "").strip() or self._fetch_card_token()
        description = description or f"Payment for user {self.user.id}"
        amount_minor = int((normalized_amount * 100).quantize(Decimal("1")))

        self._create_payment_log(
            amount_major=normalized_amount,
            currency=currency_code,
            order_id=order_id,
            description=description,
            test=test or settings.DEBUG,
        )

        base_payload = {
            "pg_merchant_id": self.merchant_id,
            "pg_amount": format(normalized_amount, "f"),
            "pg_currency": currency_code,
            "pg_order_id": order_id,
            "pg_user_id": str(self.user.id),
            "pg_card_token": token,
            "pg_description": description,
            "pg_payment_id": uuid.uuid4().hex,
            "pg_testing_mode": int(test or settings.DEBUG),
            "pg_success_url": self._callback_url("freedompay-charge-success"),
            "pg_failure_url": self._callback_url("freedompay-charge-failure"),
            "pg_post_link": self._callback_url("freedompay-charge-postback"),
        }

        try:
            init_response = self._request("init", dict(base_payload))
            payment_id = init_response.get("pg_payment_id") or base_payload["pg_payment_id"]
            base_payload["pg_payment_id"] = payment_id
            direct_response = self._request("direct", dict(base_payload))
            result = {
                "pg_status": direct_response.get("pg_status"),
                "pg_transaction_status": direct_response.get("pg_transaction_status"),
                "init": init_response,
                "direct": direct_response,
            }
            self._finalize_payment(success=True)
            return result
        except Exception as exc:
            self._finalize_payment(success=False, error=str(exc))
            raise

    def remove_card(self, card_token: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_config()
        token = (card_token or "").strip() or self._fetch_card_token()
        payload: Dict[str, Any] = {
            "pg_merchant_id": self.merchant_id,
            "pg_user_id": str(self.user.id),
            "pg_card_token": token,
        }
        payload["pg_salt"] = uuid.uuid4().hex
        payload["pg_sig"] = make_api_signature("remove", payload, self.secret)

        url = f"{self.base_url}/merchant/{self.merchant_id}/cardstorage/remove"
        masked_payload = self._mask(payload)
        self.logger.warning(
            "FreedomPay remove request user=%s payload=%s",
            self.user.id,
            masked_payload,
        )
        try:
            response = requests.post(url, data=payload, timeout=30)
        except requests.RequestException as exc:
            raise FreedomPayError(f"remove_request_failed:{exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = self._parse_xml_response(response.text)
        except Exception:
            body = {"raw": response.text}

        self.logger.warning(
            "FreedomPay remove response user=%s status=%s body=%s",
            self.user.id,
            response.status_code,
            body,
        )

        if response.status_code >= 400:
            error_code = str(body.get("pg_error_code") or "")
            error_desc = str(body.get("pg_error_description") or "").lower()
            if error_code == "1804" or "карта не найдена" in error_desc:
                return body
            raise FreedomPayError(f"remove_http_error:{response.status_code}")
        status = (body.get("pg_status") or "").lower()
        if status and status != "deleted":
            raise FreedomPayError(f"remove_status_error:{status}")
        if not status:
            card_value = body.get("card")
            if card_value not in ("", None):
                raise FreedomPayError("remove_status_error:unknown")
        return body
