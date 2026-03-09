from __future__ import annotations
import os
import httpx
from decimal import Decimal, InvalidOperation
from typing import Dict, Tuple, Iterable, Optional, Any
from django.db import transaction
from .models import CurrencyRate, Currency, UserSubscription, SubscriptionStatus, PaymentStatus
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


API_BASE = settings.EXCHANGE_API_BASE
API_KEY = settings.EXCHANGE_API_KEY

# Returns (rates, source_url)


def fetch_usd_base_rates() -> Tuple[Dict[str, Decimal], str]:
    # API returns conversion from USD -> <CURRENCY>
    url = f"{API_BASE}/{API_KEY}/latest/USD"
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPError as e:
        raise RuntimeError(f"Failed to fetch rates: {e}") from e

    if data.get("result") != "success" or "conversion_rates" not in data:
        raise RuntimeError("API returned invalid payload")

    raw = data["conversion_rates"]  # e.g. {"USD":1,"RUB":92.3,"KGS":86.0,...}

    rates: Dict[str, Decimal] = {}
    for code in (Currency.RUB, Currency.KGS):
        if code not in raw:
            continue
        # raw[code] = сколько <code> за 1 USD. Нам нужен rate_to_usd = 1/raw[code].
        try:
            v = Decimal(str(raw[code]))
            if v <= 0:
                continue
            rates[code] = (Decimal("1") / v).quantize(Decimal("0.00000001"))
        except (InvalidOperation, ZeroDivisionError):
            continue

    if not rates:
        raise RuntimeError("No required currencies in response")

    return rates, url


@transaction.atomic
def update_currency_rates() -> Dict[str, Decimal]:
    rates, source = fetch_usd_base_rates()
    for code, rate_to_usd in rates.items():
        CurrencyRate.objects.update_or_create(
            currency=code,
            defaults={"rate_to_usd": rate_to_usd, "source": source},
        )
    return rates


_ONE = Decimal("1")


def get_currency_per_usd_map(codes: Optional[Iterable[str]] = None) -> Dict[str, Decimal]:
    qs = CurrencyRate.objects.all()
    if codes:
        qs = qs.filter(currency__in=list(codes))
    out: Dict[str, Decimal] = {}
    for cr in qs.only("currency", "rate_to_usd"):
        try:
            if cr.rate_to_usd and cr.rate_to_usd > 0:
                out[cr.currency] = _ONE / cr.rate_to_usd  # USD→currency
        except (InvalidOperation, ZeroDivisionError):
            continue
    return out


def get_currency_per_usd_map_cached(codes: Optional[Iterable[str]] = None, timeout: int = 300) -> Dict[str, Decimal]:
    key = "plans:currency_per_usd:" + \
        (",".join(sorted(codes)) if codes else "all")
    data = cache.get(key)
    if data is not None:
        return data
    data = get_currency_per_usd_map(codes)
    cache.set(key, data, timeout=timeout)
    return data


BILLING_ISSUE_CARD_MISSING = "card_missing"
BILLING_ISSUE_CHARGE_FAILED = "charge_failed"
PERIOD_DAYS_MAP = {"weekly": 7, "monthly": 30, "yearly": 365}


def plan_cycle_days(period: str | None) -> int:
    return PERIOD_DAYS_MAP.get((period or "").strip().lower(), 30)


def _normalize_locale(locale: str | None) -> str:
    base = (locale or "ru").strip().lower().split("-")[0]
    if base in {"en"}:
        return "en"
    if base in {"kg", "ky"}:
        return "kg"
    return "ru"


def _fmt_deadline(dt, locale: str) -> str:
    if not dt:
        return ""
    try:
        local_dt = timezone.localtime(dt)
    except Exception:
        local_dt = dt
    # Keep it simple and explicit for all languages.
    return local_dt.strftime("%Y-%m-%d %H:%M")


def _chat_texts(locale: str) -> dict[str, str]:
    if locale == "en":
        return {
            "warning_card_missing": "Subscription payment issue: no linked card. Chat will be disabled on {deadline}. Please pay or link a card.",
            "warning_charge_failed": "Subscription payment issue: automatic charge failed. Chat will be disabled on {deadline}. Please pay your plan.",
            "warning_test_mode": "Test mode is active. You are using bonus generations. Connect a plan: {pricing_url}",
            "blocked_trial_expired": "Chat is unavailable: test bonus generations can be used without a plan only during the first 7 days after registration. Connect a plan: {pricing_url}",
            "blocked_card_missing": "Chat is unavailable because there is no active subscription: card is not linked and the 3-day payment grace period has ended. Please pay your plan.",
            "blocked_charge_failed": "Chat is unavailable because there is no active subscription: payment charge failed and the 3-day payment grace period has ended. Please pay your plan.",
            "blocked_no_active": "Chat is unavailable because there is no active subscription and no bonus generations left. Please pay your plan: {pricing_url}",
        }
    if locale == "kg":
        return {
            "warning_card_missing": "Жазылууну төлөө маселеси: карта байланган эмес. Чат {deadline} күнү өчүрүлөт. Төлөңүз же карта байлаңыз.",
            "warning_charge_failed": "Жазылууну төлөө маселеси: авто-эсептен чыгаруу ишке ашкан жок. Чат {deadline} күнү өчүрүлөт. Тарифти төлөңүз.",
            "warning_test_mode": "Тест режими активдүү. Сиз бонус генерацияларды колдонуп жатасыз. Тариф кошуңуз: {pricing_url}",
            "blocked_trial_expired": "Чат жеткиликсиз: тарифсиз бонус генерацияларды катталгандан кийинки алгачкы 7 күндө гана колдонсо болот. Тариф кошуңуз: {pricing_url}",
            "blocked_card_missing": "Активдүү жазылуу жок болгондуктан чат жеткиликсиз: карта байланган эмес жана 3 күндүк төлөм мөөнөтү бүттү. Тарифти төлөңүз.",
            "blocked_charge_failed": "Активдүү жазылуу жок болгондуктан чат жеткиликсиз: төлөм алынган жок жана 3 күндүк төлөм мөөнөтү бүттү. Тарифти төлөңүз.",
            "blocked_no_active": "Активдүү жазылуу да, бонус генерациялар да жок болгондуктан чат жеткиликсиз. Тарифти төлөңүз: {pricing_url}",
        }
    return {
        "warning_card_missing": "Проблема с оплатой подписки: карта не привязана. Чат будет отключен {deadline}. Оплатите тариф или привяжите карту.",
        "warning_charge_failed": "Проблема с оплатой подписки: автосписание не прошло. Чат будет отключен {deadline}. Оплатите тариф.",
        "warning_test_mode": "Включён тестовый режим. Вы используете бонусные генерации. Подключите тариф: {pricing_url}",
        "blocked_trial_expired": "Чат недоступен: без тарифа бонусные генерации можно использовать только первые 7 дней после регистрации. Подключите тариф: {pricing_url}",
        "blocked_card_missing": "Чат недоступен из-за отсутствия активной подписки: карта не привязана и 3-дневный срок на оплату истёк. Оплатите тариф.",
        "blocked_charge_failed": "Чат недоступен из-за отсутствия активной подписки: списание не удалось и 3-дневный срок на оплату истёк. Оплатите тариф.",
        "blocked_no_active": "Чат недоступен: нет активной подписки и закончились бонусные генерации. Подключите тариф: {pricing_url}",
    }


def _bonus_field_by_kind(kind: str) -> str:
    k = (kind or "text").strip().lower()
    if k == "image":
        return "bonus_images"
    if k == "music":
        return "bonus_music"
    if k == "song":
        return "bonus_songs"
    return "bonus_texts"


def _trial_window_open(user) -> bool:
    if not user:
        return False
    joined = getattr(user, "date_joined", None)
    if not joined:
        return False
    try:
        return timezone.now() < (joined + timezone.timedelta(days=7))
    except Exception:
        return False


def get_bonus_left(user, kind: str) -> int:
    if not user or not getattr(user, "pk", None):
        return 0
    field = _bonus_field_by_kind(kind)
    try:
        return int(getattr(user, field, 0) or 0)
    except Exception:
        return 0


def can_consume_bonus_without_subscription(user, kind: str) -> bool:
    if not _trial_window_open(user):
        return False
    return get_bonus_left(user, kind) > 0


def consume_bonus_without_subscription(user, kind: str) -> bool:
    if not user or not getattr(user, "pk", None):
        return False
    field = _bonus_field_by_kind(kind)
    User = type(user)
    with transaction.atomic():
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not _trial_window_open(locked):
            return False
        left = int(getattr(locked, field, 0) or 0)
        if left <= 0:
            return False
        setattr(locked, field, left - 1)
        locked.save(update_fields=[field])
    return True


def get_chat_access_state(user, locale: str | None = None, kind: str = "text") -> dict[str, Any]:
    """
    Unified chat access status for API + UI:
    - blocked: chat must be denied
    - warning: chat is still available but will be disabled after grace period
    """
    result: dict[str, Any] = {
        "blocked": False,
        "warning": None,
        "warning_code": "",
        "error": None,
        "error_code": "",
        "grace_until": None,
    }
    if not user or not getattr(user, "pk", None):
        return result

    loc = _normalize_locale(locale)
    texts = _chat_texts(loc)
    pricing_url = "/pricing"
    now = timezone.now()

    active_sub = (
        UserSubscription.objects
        .filter(user=user, status=SubscriptionStatus.ACTIVE)
        .order_by("-start_date")
        .first()
    )
    if active_sub:
        issue = (active_sub.billing_issue_code or "").strip().lower()
        if (
            str(active_sub.payment_status or "").lower() == PaymentStatus.UNPAID
            and issue in {BILLING_ISSUE_CARD_MISSING, BILLING_ISSUE_CHARGE_FAILED}
            and active_sub.grace_until
            and now < active_sub.grace_until
        ):
            key = "warning_card_missing" if issue == BILLING_ISSUE_CARD_MISSING else "warning_charge_failed"
            code = "chat_warning_payment_card_missing" if issue == BILLING_ISSUE_CARD_MISSING else "chat_warning_payment_charge_failed"
            deadline = _fmt_deadline(active_sub.grace_until, loc)
            result["warning"] = texts[key].format(deadline=deadline)
            result["warning_code"] = code
            result["grace_until"] = active_sub.grace_until.isoformat()
        return result

    latest_sub = (
        UserSubscription.objects
        .filter(user=user)
        .order_by("-start_date")
        .first()
    )
    if not latest_sub:
        if can_consume_bonus_without_subscription(user, kind):
            result["warning"] = texts["warning_test_mode"].format(pricing_url=pricing_url)
            result["warning_code"] = "chat_warning_test_mode_bonus_only"
            return result
        if get_bonus_left(user, kind) > 0 and not _trial_window_open(user):
            result["blocked"] = True
            result["error"] = texts["blocked_trial_expired"].format(pricing_url=pricing_url)
            result["error_code"] = "chat_blocked_trial_expired_no_subscription"
            return result
        result["blocked"] = True
        result["error"] = texts["blocked_no_active"].format(pricing_url=pricing_url)
        result["error_code"] = "chat_blocked_no_active_subscription"
        return result

    issue = (latest_sub.billing_issue_code or "").strip().lower()
    if (
        str(latest_sub.payment_status or "").lower() == PaymentStatus.UNPAID
        and issue in {BILLING_ISSUE_CARD_MISSING, BILLING_ISSUE_CHARGE_FAILED}
        and latest_sub.grace_until
    ):
        result["grace_until"] = latest_sub.grace_until.isoformat()
        if now < latest_sub.grace_until:
            # Safety fallback: if status data became inconsistent, keep grace behavior.
            key = "warning_card_missing" if issue == BILLING_ISSUE_CARD_MISSING else "warning_charge_failed"
            code = "chat_warning_payment_card_missing" if issue == BILLING_ISSUE_CARD_MISSING else "chat_warning_payment_charge_failed"
            deadline = _fmt_deadline(latest_sub.grace_until, loc)
            result["warning"] = texts[key].format(deadline=deadline)
            result["warning_code"] = code
            return result

        result["blocked"] = True
        if issue == BILLING_ISSUE_CARD_MISSING:
            result["error"] = texts["blocked_card_missing"]
            result["error_code"] = "chat_blocked_no_active_subscription_card_missing"
        else:
            result["error"] = texts["blocked_charge_failed"]
            result["error_code"] = "chat_blocked_no_active_subscription_charge_failed"
        return result

    if can_consume_bonus_without_subscription(user, kind):
        result["warning"] = texts["warning_test_mode"].format(pricing_url=pricing_url)
        result["warning_code"] = "chat_warning_test_mode_bonus_only"
        return result
    if get_bonus_left(user, kind) > 0 and not _trial_window_open(user):
        result["blocked"] = True
        result["error"] = texts["blocked_trial_expired"].format(pricing_url=pricing_url)
        result["error_code"] = "chat_blocked_trial_expired_no_subscription"
        return result
    result["blocked"] = True
    result["error"] = texts["blocked_no_active"].format(pricing_url=pricing_url)
    result["error_code"] = "chat_blocked_no_active_subscription"
    return result


def get_chat_billing_block_message(user) -> str | None:
    """
    Backward compatible helper for code paths that only need block message.
    """
    state = get_chat_access_state(user, "ru")
    return state.get("error") if state.get("blocked") else None
