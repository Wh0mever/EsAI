"""Кто сейчас обрабатывает крипту и включена ли она вообще.

Ключи читаются в порядке «админка -> окружение»: подменить ключ на проде
можно из панели, не трогая .env и не перезапуская контейнеры. Наружу они не
отдаются никогда — только маска (adminapi._mask_key).

Режим намеренно не булев:
  off   — метода нет ни у кого (и на витрине его не видно);
  staff — виден только сотрудникам: так проверяют боевые ключи, пока
          обычные люди платят как платили;
  on    — открыт всем.
"""
from __future__ import annotations

from django.conf import settings

MODE_OFF = "off"
MODE_STAFF = "staff"
MODE_ON = "on"
MODES = (MODE_OFF, MODE_STAFF, MODE_ON)


def _runtime(key: str, default):
    try:
        from adminapi.runtime import get_runtime

        return get_runtime(key, default)
    except Exception:  # noqa: BLE001 — настройки не должны ронять оплату
        return default


def mode() -> str:
    value = str(_runtime("crypto_payments_mode",
                         str(getattr(settings, "CRYPTO_PAYMENTS_MODE", MODE_OFF)))).strip().lower()
    return value if value in MODES else MODE_OFF


def api_key() -> str:
    return str(_runtime("NOWPAYMENTS_API_KEY",
                        str(getattr(settings, "NOWPAYMENTS_API_KEY", "")))).strip()


def ipn_secret() -> str:
    return str(_runtime("NOWPAYMENTS_IPN_SECRET",
                        str(getattr(settings, "NOWPAYMENTS_IPN_SECRET", "")))).strip()


def fee_paid_by_user() -> bool:
    """Добавлять ли комиссию процессора к сумме покупателя."""
    value = _runtime("crypto_fee_paid_by_user",
                     bool(getattr(settings, "NOWPAYMENTS_FEE_PAID_BY_USER", True)))
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def settlement_currency() -> str:
    """Код валюты кошелька выплат у процессора (пусто — не задан)."""
    value = _runtime("crypto_settlement_currency",
                     getattr(settings, "NOWPAYMENTS_SETTLEMENT_CURRENCY", ""))
    return str(value or "").strip().lower()


def fixed_rate() -> bool:
    """Фиксировать ли курс на время счёта (дороже по минимальной сумме)."""
    return bool(getattr(settings, "NOWPAYMENTS_FIXED_RATE", False))


def get_adapter(name: str = "nowpayments"):
    """Адаптер процессора. Пока он один, но точка расширения — здесь."""
    from .nowpayments import NowPayments

    if name not in ("nowpayments", "crypto_nowpayments"):
        raise ValueError(f"неизвестный процессор: {name}")
    return NowPayments(
        api_key=api_key(),
        ipn_secret=ipn_secret(),
        api_url=str(getattr(settings, "NOWPAYMENTS_API_URL", "") or ""),
        sandbox=bool(getattr(settings, "NOWPAYMENTS_SANDBOX", False)),
        fixed_rate=fixed_rate(),
        fee_paid_by_user=fee_paid_by_user(),
        settlement_currency=settlement_currency(),
    )


def provider_code(name: str = "nowpayments") -> str:
    """Значение Payment.provider для этого процессора."""
    return f"crypto_{name}"


def is_configured() -> bool:
    return bool(api_key())


def is_enabled_for(user=None) -> bool:
    """Показывать ли крипту этому человеку."""
    current = mode()
    if current == MODE_OFF or not is_configured():
        return False
    if current == MODE_ON:
        return True
    return bool(user is not None and getattr(user, "is_authenticated", False)
                and (user.is_staff or user.is_superuser))


def ipn_url(request=None) -> str:
    """Куда процессор пришлёт уведомление об оплате.

    Берём адрес из настроек, а не из заголовков запроса: заголовок Host
    подделывается, и тогда уведомления о наших платежах ушли бы чужому.
    Только https — по http процессор отправит статус платежа открытым текстом.
    """
    from django.conf import settings as dj_settings
    from django.urls import reverse

    from .base import ProviderError

    base_url = str(getattr(dj_settings, "SITE_BASE_URL", "") or "").strip().rstrip("/")
    if not base_url and request is not None:
        base_url = f"{request.scheme}://{request.get_host()}"
    if not base_url:
        raise ProviderError("не задан SITE_BASE_URL", code="ipn_url_missing")
    if not base_url.startswith("https://") and not dj_settings.DEBUG:
        raise ProviderError("адрес уведомлений не https", code="ipn_url_insecure")
    return f"{base_url}{reverse('payments:crypto-nowpayments-ipn')}"
