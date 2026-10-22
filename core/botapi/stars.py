"""Telegram Stars: счёт, подтверждение оплаты, возвраты и сверка.

Всё, что касается денег, живёт здесь, а не в боте: бот лишь передаёт то,
что прислал Telegram. Идемпотентность держится на двух уникальных ключах —
payload счёта и telegram_payment_charge_id — поэтому повторный апдейт,
ручная перепроверка и сверка по расписанию не могут начислить дважды.
"""
from __future__ import annotations

import base64
import logging
import os
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.langutils import tr
from payments.models import FunnelEvent, Payment, StarInvoice
from plans.models import TokenPackage
from plans.stars import stars_mode

from .models import TelegramChat
from .telegram import TelegramError, tg_api

logger = logging.getLogger("botapi.stars")

INVOICE_TTL = timedelta(hours=24)
REUSE_WINDOW = timedelta(hours=1)
CURRENCY = "XTR"


class StarsError(Exception):
    """Отказ с кодом, который бот покажет человеку или запишет в лог."""

    def __init__(self, code: str, http: int = 409, **extra):
        super().__init__(code)
        self.code = code
        self.http = http
        self.extra = extra


def _new_payload() -> str:
    return "i1." + base64.urlsafe_b64encode(os.urandom(16)).decode("ascii").rstrip("=")


def user_for_telegram(telegram_id):
    from allauth.socialaccount.models import SocialAccount

    account = (SocialAccount.objects.filter(provider="telegram", uid=str(telegram_id))
               .select_related("user").first())
    return account.user if account else None


def _funnel(name: str, user, telegram_id, **meta) -> None:
    try:
        FunnelEvent.objects.create(name=name, user=user, device_key=f"tg:{telegram_id}",
                                   meta=meta)
    except Exception:  # noqa: BLE001
        logger.exception("funnel %s не записался", name)


# ---------------------------------------------------------------- счёт ---

_TITLES = {
    "ru": "EsAI · {name}",
    "en": "EsAI · {name}",
    "kg": "EsAI · {name}",
}
_DESCRIPTIONS = {
    "ru": "{tokens} кредитов на баланс EsAI. Кредиты не сгорают и работают "
          "везде: чат, картинки, видео и студия мультфильмов.",
    "en": "{tokens} credits for your EsAI balance. Credits never expire and "
          "work everywhere: chat, images, video and the cartoon studio.",
    "kg": "EsAI балансына {tokens} кредит. Кредиттер күйбөйт: чат, сүрөт, "
          "видео жана мультфильм студиясы.",
}
_LABELS = {"ru": "{tokens} кредитов", "en": "{tokens} credits", "kg": "{tokens} кредит"}
# Запасное слово, если у пакета нет названия совсем.
_NAMELESS = {"ru": "пакет", "en": "package", "kg": "пакет"}


def package_name_for(invoice: StarInvoice, lang: str = "ru",
                     package: TokenPackage | None = None) -> str:
    """Название пакета на языке человека.

    Счёт хранит только русское имя (снимок на момент покупки), а витрина
    показывает name_en/name_kg. Берём перевод у самого пакета по package_id:
    тогда и повторно выставленный счёт (REUSE_WINDOW) говорит на актуальном
    языке. Пакет могли удалить — тогда остаётся снимок.
    """
    lang = lang if lang in _TITLES else "ru"
    if package is None or package.pk != invoice.package_id:
        package = TokenPackage.objects.filter(pk=invoice.package_id).first()
    name = (tr(package, "name", lang) if package else "") or invoice.package_name or ""
    return name.strip() or _NAMELESS[lang]


def describe(invoice: StarInvoice, lang: str = "ru", *, resumed: bool = False,
             package: TokenPackage | None = None) -> dict:
    """Что нужно боту для sendInvoice: заголовок ≤ 32, описание ≤ 255."""
    lang = lang if lang in _TITLES else "ru"
    total = invoice.total_tokens
    title = _TITLES[lang].format(name=package_name_for(invoice, lang, package))[:32]
    description = _DESCRIPTIONS[lang].format(tokens=total)[:255]
    return {
        "order_id": invoice.payment.order_id,
        "payload": invoice.payload,
        "title": title,
        "description": description,
        "currency": CURRENCY,
        "prices": [{"label": _LABELS[lang].format(tokens=total)[:32],
                    "amount": int(invoice.stars_amount)}],
        "stars": int(invoice.stars_amount),
        "tokens": int(invoice.tokens),
        "bonus_tokens": int(invoice.bonus_tokens),
        "tokens_total": total,
        "package_id": invoice.package_id,
        "expires_at": invoice.expires_at.isoformat(),
        "resumed": resumed,
    }


def create_invoice(user, package: TokenPackage, telegram_id: int, lang: str = "ru") -> dict:
    mode = stars_mode()
    if mode == "off":
        raise StarsError("stars_disabled", 403)
    if mode == "staff" and not getattr(user, "is_staff", False):
        raise StarsError("stars_disabled", 403)
    if not getattr(user, "is_active", True):
        raise StarsError("user_inactive", 403)
    if not package.is_active or not package.stars_price:
        raise StarsError("package_not_available", 400)
    stars = int(package.stars_price)
    if stars < 1 or stars > 9999:
        raise StarsError("package_not_available", 400)

    now = timezone.now()
    # Тот же пакет, начатый час назад, — это тот же счёт, а не второй.
    existing = (StarInvoice.objects
                .filter(payment__user=user, telegram_id=int(telegram_id),
                        package_id=package.id, status=StarInvoice.STATUS_CREATED,
                        stars_amount=stars, created_at__gte=now - REUSE_WINDOW,
                        expires_at__gt=now)
                .select_related("payment").order_by("-created_at").first())
    if existing:
        return describe(existing, lang, resumed=True, package=package)

    tokens = int(package.tokens or 0)
    bonus = int(package.bonus_tokens or 0) + int(package.stars_bonus_tokens or 0)
    if tokens + bonus <= 0:
        raise StarsError("package_not_available", 400)

    with transaction.atomic():
        order_id = f"tgs-{user.id}-{package.id}-{os.urandom(5).hex()}"
        payment = Payment.objects.create(
            user=user,
            provider="telegram_stars",
            amount=Decimal(stars),
            currency=CURRENCY,
            order_id=order_id,
            description=f"Token package purchase #{package.id} (Telegram Stars)",
            is_test=False,
            request={
                "provider": "telegram_stars",
                "pay_method": "stars",
                "token_purchase": {
                    "package_id": package.id,
                    "tokens": tokens,
                    "bonus_tokens": bonus,
                },
                "stars": stars,
                "telegram_id": int(telegram_id),
                "lang": lang,
            },
            response={},
        )
        invoice = StarInvoice.objects.create(
            payment=payment,
            telegram_id=int(telegram_id),
            payload=_new_payload(),
            package_id=package.id,
            package_name=package.name,
            tokens=tokens,
            bonus_tokens=bonus,
            stars_amount=stars,
            expires_at=now + INVOICE_TTL,
        )
    _funnel("bot_stars_invoice", user, telegram_id, package_id=package.id, stars=stars)
    return describe(invoice, lang, package=package)


def set_invoice_message(payload: str, message_id) -> None:
    try:
        StarInvoice.objects.filter(payload=payload).update(invoice_message_id=int(message_id))
    except (TypeError, ValueError):
        pass


# ------------------------------------------------------------ проверка ---

def _validate(invoice: StarInvoice, telegram_id, total_amount, currency) -> None:
    if int(invoice.telegram_id) != int(telegram_id):
        raise StarsError("user_mismatch")
    if str(currency or "").upper() != CURRENCY:
        raise StarsError("currency_mismatch")
    if int(total_amount or 0) != int(invoice.stars_amount):
        raise StarsError("amount_mismatch", expected=int(invoice.stars_amount),
                         got=int(total_amount or 0))


def precheck(telegram_id, payload: str, total_amount, currency) -> StarInvoice:
    """Ответ на pre_checkout_query: только чтение, ничего не меняем."""
    invoice = StarInvoice.objects.filter(payload=payload).select_related(
        "payment", "payment__user").first()
    if not invoice:
        raise StarsError("not_found", 404)
    if invoice.status == StarInvoice.STATUS_PAID:
        raise StarsError("already_paid")
    if invoice.status != StarInvoice.STATUS_CREATED:
        raise StarsError("invoice_closed")
    if invoice.expires_at <= timezone.now():
        raise StarsError("expired")
    _validate(invoice, telegram_id, total_amount, currency)
    user = invoice.payment.user
    if not user or not getattr(user, "is_active", True):
        raise StarsError("user_inactive", 403)
    if not TokenPackage.objects.filter(pk=invoice.package_id, is_active=True).exists():
        raise StarsError("package_inactive")
    if stars_mode() == "off":
        raise StarsError("stars_disabled", 403)
    return invoice


# ---------------------------------------------------------- начисление ---

def confirm(telegram_id, payload: str, charge_id: str, *, provider_charge_id: str = "",
            total_amount=None, currency: str = CURRENCY, raw: dict | None = None,
            source: str = "bot") -> dict:
    """successful_payment → кредиты. Повтор того же charge_id — без второго начисления."""
    try:
        return _confirm(telegram_id, payload, charge_id, provider_charge_id=provider_charge_id,
                        total_amount=total_amount, currency=currency, raw=raw, source=source)
    except StarsError as exc:
        if exc.code in ("amount_mismatch", "currency_mismatch", "user_mismatch"):
            _record_mismatch(exc, raw)
        elif exc.code == "double_payment":
            _record_double_charge(exc)
        raise


def _confirm(telegram_id, payload: str, charge_id: str, *, provider_charge_id: str = "",
             total_amount=None, currency: str = CURRENCY, raw: dict | None = None,
             source: str = "bot") -> dict:
    from payments.views import _credit_token_package_for_payment, _log_payment_event

    charge_id = str(charge_id or "").strip()
    if not charge_id:
        raise StarsError("bad_charge_id", 400)

    with transaction.atomic():
        # Блокируем сам счёт: пользователь у платежа может быть пустым, а
        # FOR UPDATE по внешнему соединению Postgres не разрешает.
        invoice = (StarInvoice.objects.select_for_update(of=("self",))
                   .select_related("payment", "payment__user")
                   .filter(payload=payload).first())
        if not invoice:
            raise StarsError("not_found", 404)
        payment = invoice.payment
        user = payment.user

        if invoice.status == StarInvoice.STATUS_PAID:
            if invoice.telegram_payment_charge_id == charge_id:
                return _paid_payload(invoice, duplicate=True)
            # Второй платёж по тому же счёту — деньги вернуть, счёт не трогать.
            # Пометку пишет confirm() уже ПОСЛЕ выхода из транзакции: исключение
            # откатило бы её вместе со всем остальным.
            raise StarsError("double_payment", charge_id=charge_id, _invoice_pk=invoice.pk)
        if invoice.status == StarInvoice.STATUS_REFUNDED:
            raise StarsError("invoice_refunded", charge_id=charge_id)

        try:
            _validate(invoice, telegram_id, total_amount, currency)
        except StarsError as exc:
            # Запись о расхождении делаем ПОСЛЕ выхода из транзакции: исключение
            # откатывает всё, что сохранили внутри неё.
            exc.extra["charge_id"] = charge_id
            exc.extra["_invoice_pk"] = invoice.pk
            raise

        if not user or not getattr(user, "is_active", True):
            raise StarsError("user_inactive", 403)

        invoice.status = StarInvoice.STATUS_PAID
        invoice.telegram_payment_charge_id = charge_id
        invoice.provider_payment_charge_id = str(provider_charge_id or "")[:128]
        invoice.paid_at = timezone.now()
        invoice.raw = raw or {}
        try:
            invoice.save(update_fields=["status", "telegram_payment_charge_id",
                                        "provider_payment_charge_id", "paid_at", "raw",
                                        "updated_at"])
        except IntegrityError:
            # Тот же charge_id уже записан у другого счёта — Telegram не выдаёт
            # один идентификатор дважды, значит, апдейт пришёл повторно.
            raise StarsError("charge_id_reused", charge_id=charge_id)

        payment.success = True
        payment.error = None
        payment.response = {**(payment.response or {}), "telegram_payment_charge_id": charge_id,
                            "source": source, "paid_at": invoice.paid_at.isoformat()}
        _credit_token_package_for_payment(payment, payment.order_id)
        payment.save(update_fields=["success", "error", "response"])

    _log_payment_event(payment, "stars_paid")
    _funnel("bot_stars_paid", user, telegram_id, stars=invoice.stars_amount,
            package_id=invoice.package_id, source=source)
    return _paid_payload(invoice, duplicate=False)


def _record_mismatch(exc: "StarsError", raw: dict | None) -> None:
    """Пометить счёт как несошедшийся — вне транзакции, чтобы пометка осталась."""
    from payments.views import _log_payment_event

    pk = exc.extra.pop("_invoice_pk", None)
    if not pk:
        return
    invoice = StarInvoice.objects.filter(pk=pk).select_related("payment").first()
    if not invoice or invoice.status != StarInvoice.STATUS_CREATED:
        return
    invoice.status = StarInvoice.STATUS_FAILED
    invoice.flags = {**(invoice.flags or {}), "mismatch": exc.code,
                     **{k: v for k, v in exc.extra.items()}}
    invoice.raw = raw or {}
    invoice.save(update_fields=["status", "flags", "raw", "updated_at"])
    invoice.payment.error = f"stars_{exc.code}"
    invoice.payment.save(update_fields=["error"])
    _log_payment_event(invoice.payment, f"stars_{exc.code}")


def _record_double_charge(exc: "StarsError") -> None:
    """След о втором платеже по оплаченному счёту — вне транзакции, чтобы остался.

    Счёт при этом не меняется: законный первый платёж остаётся оплаченным, а
    лишний мы возвращаем автовозвратом. Пометка нужна, чтобы по счёту было
    видно, что был второй платёж и чем он кончился.
    """
    from payments.views import _log_payment_event

    pk = exc.extra.pop("_invoice_pk", None)
    charge_id = str(exc.extra.get("charge_id") or "")
    if not pk or not charge_id:
        return
    try:
        with transaction.atomic():
            invoice = (StarInvoice.objects.select_for_update(of=("self",))
                       .select_related("payment").filter(pk=pk).first())
            if not invoice:
                return
            flags = dict(invoice.flags or {})
            seen = list(flags.get("double_charges") or [])
            if charge_id not in seen:
                seen.append(charge_id)
            flags.update({"double_charge": charge_id, "double_charges": seen})
            invoice.flags = flags
            invoice.save(update_fields=["flags", "updated_at"])
            payment = invoice.payment
            # error у успешного платежа не трогаем: он читается как «оплата не
            # прошла». Подробности кладём в response.
            payment.response = {**(payment.response or {}), "double_charge": charge_id}
            payment.save(update_fields=["response"])
        _log_payment_event(payment, "stars_double_charge")
    except Exception:  # noqa: BLE001 — пометка не должна мешать автовозврату
        logger.exception("stars: пометка двойного платежа %s не записалась", charge_id)


def _invoice_lang(invoice: StarInvoice) -> str:
    """Язык человека: настройка чата важнее языка, с которым выставляли счёт."""
    lang = (TelegramChat.objects.filter(telegram_id=invoice.telegram_id)
            .values_list("lang", flat=True).first())
    lang = lang or (invoice.payment.request or {}).get("lang")
    return lang if lang in _TITLES else "ru"


def _paid_payload(invoice: StarInvoice, *, duplicate: bool) -> dict:
    from plans.tiers import user_tier

    user = invoice.payment.user
    try:
        user.refresh_from_db(fields=["token_balance", "is_paid"])
    except Exception:  # noqa: BLE001
        pass
    return {
        "status": "duplicate" if duplicate else "paid",
        "credited": invoice.total_tokens,
        "balance_tokens": int(getattr(user, "token_balance", 0) or 0),
        "tier": user_tier(user),
        "is_paid": bool(getattr(user, "is_paid", False)),
        "package_name": package_name_for(invoice, _invoice_lang(invoice)),
        "order_id": invoice.payment.order_id,
        "invoice_message_id": invoice.invoice_message_id,
    }


# ------------------------------------------------------------- возврат ---

def mark_refunded(*, charge_id: str = "", payload: str = "", reason: str = "telegram",
                  by=None) -> dict:
    """Зафиксировать возврат и изъять кредиты. Идемпотентно."""
    from payments.views import _clawback_token_package_for_payment, _log_payment_event

    qs = StarInvoice.objects.select_for_update(of=("self",)).select_related("payment", "payment__user")
    with transaction.atomic():
        invoice = None
        if charge_id:
            invoice = qs.filter(telegram_payment_charge_id=charge_id).first()
        if invoice is None and payload:
            invoice = qs.filter(payload=payload).first()
            recorded = (invoice.telegram_payment_charge_id or "") if invoice else ""
            if invoice is not None and charge_id and recorded and recorded != charge_id:
                # Возврат относится к ДРУГОМУ платежу по этому же счёту: это
                # второй платёж, который мы сами вернули автовозвратом. Законный
                # первый платёж и его кредиты трогать нельзя.
                return {"status": "foreign_charge", "order_id": invoice.payment.order_id}
        if invoice is None:
            raise StarsError("not_found", 404)
        if invoice.status == StarInvoice.STATUS_REFUNDED:
            return {"status": "already_refunded", "order_id": invoice.payment.order_id}
        payment = invoice.payment
        invoice.status = StarInvoice.STATUS_REFUNDED
        invoice.refunded_at = timezone.now()
        invoice.refund_reason = str(reason or "")[:120]
        invoice.refund_by = by if getattr(by, "pk", None) else None
        invoice.save(update_fields=["status", "refunded_at", "refund_reason", "refund_by",
                                    "updated_at"])
        payment.error = "stars_refunded"
        if payment.user:
            _clawback_token_package_for_payment(payment, payment.order_id, {})
        payment.save(update_fields=["error", "response"])
    _log_payment_event(payment, "stars_refunded")
    debited = int((payment.response or {}).get("clawback_debited") or 0)
    return {"status": "refunded", "order_id": payment.order_id, "debited": debited,
            "credited": invoice.total_tokens}


def refund(invoice: StarInvoice, *, reason: str, by=None, force: bool = False) -> dict:
    """Вернуть Stars через Telegram и изъять кредиты.

    Возврат в Telegram только полный. Если кредиты уже потрачены, изымаем что
    осталось — но без force такой возврат не делаем: это уже спор, а не кнопка.
    """
    if invoice.status != StarInvoice.STATUS_PAID or not invoice.telegram_payment_charge_id:
        raise StarsError("not_refundable", 400)
    user = invoice.payment.user
    balance = int(getattr(user, "token_balance", 0) or 0) if user else 0
    if not force and balance < invoice.total_tokens:
        raise StarsError("credits_spent", 409, balance=balance, credited=invoice.total_tokens)
    try:
        tg_api("refundStarPayment", user_id=invoice.telegram_id,
               telegram_payment_charge_id=invoice.telegram_payment_charge_id)
    except TelegramError as exc:
        if "ALREADY_REFUNDED" not in (exc.description or "").upper():
            raise StarsError("telegram_refused", 502, description=exc.description)
    return mark_refunded(charge_id=invoice.telegram_payment_charge_id, reason=reason, by=by)


def auto_refund(telegram_id, charge_id: str, reason: str) -> bool:
    """Вернуть деньги за платёж, который не сошёлся со счётом. Без вопросов."""
    try:
        tg_api("refundStarPayment", user_id=int(telegram_id),
               telegram_payment_charge_id=charge_id)
        logger.warning("stars: автовозврат %s (%s)", charge_id, reason)
        return True
    except TelegramError as exc:
        logger.error("stars: автовозврат %s не удался: %s", charge_id, exc.description)
        return False


# --------------------------------------------------------------- сверка ---

def expire_stale() -> int:
    return StarInvoice.objects.filter(
        status=StarInvoice.STATUS_CREATED, expires_at__lt=timezone.now()
    ).update(status=StarInvoice.STATUS_EXPIRED)


def reconcile(limit: int = 100, max_pages: int = 20) -> dict:
    """Пройти по журналу Stars бота и начислить то, что бот пропустил.

    Журнал у Telegram append-only, поэтому храним смещение и читаем только
    новое. Входящий платёж с нашим payload и счётом в статусе «выставлен» —
    это пропущенный апдейт: начисляем тем же confirm().
    """
    from adminapi.runtime import get_runtime, set_runtime

    if not (getattr(settings, "TELEGRAM_PRODUCT_BOT_TOKEN", "") or "").strip():
        return {"status": "no_token"}
    try:
        offset = int(get_runtime("stars_tx_offset", 0) or 0)
    except Exception:  # noqa: BLE001
        offset = 0
    credited = refunded = seen = 0
    journal_ok = True
    for _ in range(max_pages):
        try:
            data = tg_api("getStarTransactions", offset=offset, limit=limit) or {}
        except TelegramError as exc:
            logger.warning("stars: getStarTransactions: %s", exc.description)
            journal_ok = False
            break
        rows = data.get("transactions") or []
        for tx in rows:
            seen += 1
            source = tx.get("source") or {}
            receiver = tx.get("receiver") or {}
            if source.get("type") == "user" and source.get("invoice_payload"):
                payload = str(source.get("invoice_payload"))
                invoice = StarInvoice.objects.filter(payload=payload).first()
                # Просроченный счёт тоже засчитываем: оплатить можно до самой
                # границы срока, а бот принимает такое подтверждение, так что
                # сверка не вправе быть строже основного пути.
                if invoice and invoice.status in (StarInvoice.STATUS_CREATED,
                                                  StarInvoice.STATUS_EXPIRED):
                    try:
                        confirm(invoice.telegram_id, payload, str(tx.get("id")),
                                total_amount=tx.get("amount"), currency=CURRENCY,
                                raw={"reconcile": tx}, source="reconcile")
                        credited += 1
                    except StarsError as exc:
                        logger.warning("stars: сверка %s: %s", payload, exc.code)
            elif receiver.get("type") == "user":
                # Наш исходящий перевод пользователю — это возврат.
                charge_id = str(tx.get("id") or "")
                invoice = StarInvoice.objects.filter(
                    telegram_payment_charge_id=charge_id).first()
                if invoice and invoice.status == StarInvoice.STATUS_PAID:
                    try:
                        mark_refunded(charge_id=charge_id, reason="reconcile")
                        refunded += 1
                    except StarsError:
                        pass
        offset += len(rows)
        if len(rows) < limit:
            break
    try:
        set_runtime("stars_tx_offset", offset)
    except Exception:  # noqa: BLE001
        logger.exception("stars: смещение не сохранилось")
    # Журнал не прочитан — значит, мы не знаем, какие счета оплачены. Гасить их
    # сейчас нельзя: оплаченный, но не зачисленный счёт вышел бы из сверки.
    expired = expire_stale() if journal_ok else 0
    return {"status": "ok" if journal_ok else "journal_unavailable", "seen": seen,
            "credited": credited, "refunded": refunded, "expired": expired,
            "offset": offset}
