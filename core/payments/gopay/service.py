"""Единственное место, где счёт единого QR меняет состояние и начисляет кредиты.

Правила, на которых всё держится:

* зачисляем ТОЛЬКО по ответу COMMITTED на наш собственный подписанный запрос
  статуса. Вебхук — повод спросить, а не основание платить: секрет вебхуков
  лежит в базе открытым текстом, а всё остальное для подделки покупатель знает;
* зачисляем один раз: строка платежа под блокировкой + проверка «по заказу уже
  начислено / изъято / возврат отмечен» + те же проверки внутри общего кода
  начисления. Повтор вебхука, опрос, сверка и ручная перепроверка идут сюда же;
* перед зачислением сходится всё: номер заказа, номер платежа GoPay (оба
  обязательны), сумма до тыйына, валюта и среда (тест/бой). Любое расхождение —
  не начисляем и зовём человека;
* COMMITTED побеждает любой наш статус, навсегда. «Просрочен» и «отменён» по
  нашим часам — не истина о деньгах: банк мог провести оплату в последнюю секунду;
* сначала GoPay, потом блокировки. При ATOMIC_REQUESTS блокировка строки живёт
  до конца запроса, и сетевой вызов под ней подвесил бы всех, кто ждёт эту строку;
* каждая запись в flags — под блокировкой на перечитанной строке: пометка
  одного пути (needs_review, late_commit) не должна затереться копией другого.

Задачи Celery отсюда не запускаются: ставит их в очередь тот, кто зовёт
(представления и задачи), — так модуль не тянет за собой очередь.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from ..models import GoPayInvoice, Payment
from . import client as _client
from . import config
from .client import (RETURN_URL_RE, GoPayClient, GoPayError, GoPayRejected,
                     GoPayUnavailable, PaymentState)

logger = logging.getLogger("payments.gopay")

# Подстраховка: живой QR у покупателя один (новый вытесняет прежние), а этот
# предел достижим, только если GoPay отказывает в отменах.
MAX_OPEN_AT_PROVIDER = 6
# К счёту, которому осталось меньше, не возвращаем: человек не успеет открыть банк.
RESUME_MIN_SECONDS_LEFT = 90
# Сколько ждём после нашего срока, прежде чем закрыть счёт своими часами.
LOCAL_EXPIRY_GRACE = timedelta(minutes=10)
# Через сколько после нашего срока отменяем у GoPay счёт, который он сам не закрыл.
CANCEL_AFTER_EXPIRY = timedelta(seconds=120)
LATE_SWEEP_WINDOW = timedelta(hours=6)         # закрытие подтверждено GoPay
UNCONFIRMED_SWEEP_WINDOW = timedelta(days=7)   # закрыто только нашими часами (flags.local_expiry)
CALLBACKS_CAP = 40
APPS_CACHE_TTL = 6 * 3600
APPS_LAST_GOOD_TTL = 7 * 24 * 3600
APPS_MAX = 24
# Предохранитель: GoPay не должен занять общую очередь Celery (два слота на всех).
DOWN_AFTER_FAILURES = 2
DOWN_TTL = 45
ALERT_AFTER_FAILURES = 5
ALERT_EVERY = 1800

SOURCES = ("create", "webhook", "query", "reconcile", "admin", "cancel", "chain_check")
# Исходы, после которых GoPay считается «не отвечающим нам»: молчит, не принимает
# ключ, организация не активна или ключей нет. Любой другой отказ — он жив.
_FAILING_KINDS = ("unavailable", "auth", "org_inactive", "not_configured")

_ALERT_TTL = 6 * 3600
_HEALTH_TTL = 3600
_APPS_FAIL_TTL = 300
_LINK_KEY_RE = re.compile(r"[A-Za-z0-9_\-]{1,32}")
_LINK_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]{1,31}):")
# Ссылка уйдёт в href кнопки банка: схемы, которые исполняют код или читают
# локальные данные, не пропускаем, что бы ни прислал GoPay.
_UNSAFE_SCHEMES = frozenset({"javascript", "data", "vbscript", "file", "blob", "about"})


# ------------------------------------------------------------ мелочи ---

def _aware(value: str):
    """Время из GoPay — только если в нём есть часовой пояс.

    Ответы API приходят без пояса (UTC это или Бишкек — документация молчит),
    и такое время мы не используем вовсе: подставляем свои часы.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if (parsed.tzinfo is not None and parsed.utcoffset() is not None) else None


def _date(value: str):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _https(url) -> str:
    url = str(url or "")
    return url if (url.startswith("https://") and len(url) <= 500) else ""


def _safe_links(links) -> dict:
    """Ссылки в банковские приложения, которые не страшно поставить в href."""
    result = {}
    if not isinstance(links, dict):
        return result
    for key, value in links.items():
        if len(result) >= APPS_MAX:
            break
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if not _LINK_KEY_RE.fullmatch(key) or len(value) > 2000:
            continue
        match = _LINK_SCHEME_RE.match(value)
        if not match or match.group(1).lower() in _UNSAFE_SCHEMES:
            continue
        result[key] = value
    return result


def _money(value) -> str:
    return format(Decimal(value), ".2f")


def _log_event(*args, **kwargs):
    from audit.services import log_event

    return log_event(*args, **kwargs)


def _call(env: str, fn):
    """Один вызов клиента с учётом исхода в «здоровье» GoPay."""
    try:
        result = fn()
    except GoPayError as exc:
        note_result(env, exc)
        raise
    note_result(env, None)
    return result


def _client_for(env: str) -> GoPayClient:
    """Клиент среды. Через модуль клиента, чтобы у тестов была одна точка подмены."""
    try:
        return _client.get_client(env)
    except GoPayError as exc:
        note_result(env, exc)
        raise


def _alert(pay, inv, what: str) -> None:
    """Сигнал «нужен человек»: оплачено, а зачислить нельзя или не вышло.

    Другого канала уведомить администратора в проекте нет — событие уровня
    error в журнале и счётчик «Оплачено, но не зачислено» в админке. Не чаще
    раза в шесть часов на счёт и причину: сверка возвращается к такому счёту
    снова и снова.
    """
    try:
        try:
            if not cache.add(f"gopay:alert:inv:{inv.pk}:{what}", 1, _ALERT_TTL):
                return
        except Exception:  # noqa: BLE001 — без кэша лучше повторить сигнал, чем промолчать
            pass
        _log_event(
            "payment", message=f"GoPay: нужен разбор ({what}) order={pay.order_id}",
            user=pay.user, level="error",
            meta={"needs_review": True, "what": what, "provider": "gopay",
                  "order_id": pay.order_id, "payment_id": inv.provider_payment_id,
                  "env": inv.env})
        logger.error("gopay: нужен разбор (%s) order=%s payment_id=%s env=%s",
                     what, pay.order_id, inv.provider_payment_id, inv.env)
    except Exception:  # noqa: BLE001 — сигнал не важнее денег
        logger.exception("gopay: не удалось записать сигнал о разборе")


def _discount_moved(pay) -> bool:
    """Платёж создан со скидкой, а скидка за ним уже не закреплена."""
    try:
        if not (pay.request or {}).get("exit_discount"):
            return False
        from plans.models import ExitDiscountOffer

        return not ExitDiscountOffer.objects.filter(applied_to_payment_id=pay.pk).exists()
    except Exception:  # noqa: BLE001 — пометка для разбора не должна мешать зачислению
        return False


def _append_callback(pay, source: str, state: PaymentState) -> None:
    response = dict(pay.response or {})
    callbacks = list(response.get("callbacks") or [])
    entry = {"type": f"gopay_{source}", "payload": dict(state.raw)}
    # Счёт, который GoPay упорно показывает открытым, сверка спрашивает снова и
    # снова — одинаковые записи подряд историю не засоряют.
    if callbacks and callbacks[-1] == entry:
        return
    callbacks.append(entry)
    response["callbacks"] = callbacks[-CALLBACKS_CAP:]
    pay.response = response


# ------------------------------------------------------------ поиск ---

def invoice_of(payment):
    """Счёт QR этого платежа или None. Не бросает."""
    if payment is None:
        return None
    try:
        return payment.gopay_invoice
    except Exception:  # noqa: BLE001 — нет счёта, платёж не сохранён и т.п.
        return None


def open_invoices_for(user):
    """Живые QR покупателя: открыты, наш срок не вышел, покупатель их не оставлял."""
    return GoPayInvoice.objects.select_related("payment").filter(
        payment__user=user, status__in=GoPayInvoice.OPEN_STATES,
        expires_at__gt=timezone.now(), cancel_requested_at__isnull=True)


def open_at_provider_count(user) -> int:
    """Сколько счетов покупателя ещё открыто у GoPay — оставленные тоже считаются."""
    return GoPayInvoice.objects.filter(
        payment__user=user, status__in=GoPayInvoice.OPEN_STATES,
        expires_at__gt=timezone.now()).count()


def find_resumable(user, package_id):
    """Неоплаченный QR того же пакета, к которому можно вернуться, или None.

    Оплаченный, закрытый, оставленный, созданный в другой среде и почти
    истёкший счёт не возвращаем никогда.
    """
    try:
        package_id = int(package_id)
    except (TypeError, ValueError):
        return None
    return (GoPayInvoice.objects.select_related("payment")
            .filter(payment__user=user, payment__success=False,
                    payment__request__token_purchase__package_id=package_id,
                    status__in=GoPayInvoice.OPEN_STATES,
                    cancel_requested_at__isnull=True, env=config.env(),
                    expires_at__gt=timezone.now() + timedelta(seconds=RESUME_MIN_SECONDS_LEFT))
            .order_by("-created_at", "-id").first())


# --------------------------------------------------------- создание ---

def _best_effort_cancel(client: GoPayClient, env: str, state: PaymentState) -> None:
    """Счёт, который мы не возьмём, у GoPay оставлять оплачиваемым нельзя."""
    if not state.payment_id:
        return
    try:
        _call(env, lambda: client.cancel_payment(payment_id=state.payment_id))
    except GoPayError:
        pass
    except Exception:  # noqa: BLE001
        logger.warning("gopay: не удалось отменить непринятый счёт")


def _create_or_adopt(client: GoPayClient, env: str, payment, kwargs: dict,
                     success_url: str, failure_url: str) -> PaymentState:
    try:
        return _call(env, lambda: client.create_payment(
            **kwargs, success_url=success_url, failure_url=failure_url))
    except GoPayUnavailable as exc:
        error: GoPayError = exc
    except GoPayRejected as exc:
        error = exc
        if exc.kind == "invalid" and (success_url or kwargs.get("buyer_email")):
            # Необязательного мы добавляем два поля: адреса возврата и почту
            # покупателя. Отклонённый запрос ничего не создал, поэтому один
            # повтор без них безопасен. Почту убираем тоже: GoPay проверяет её
            # строже нас, и адрес, который ему не понравился, иначе навсегда
            # закрыл бы этому покупателю оплату по QR. Без почты страница GoPay
            # просто спросит контакт сама.
            try:
                return _call(env, lambda: client.create_payment(
                    **{**kwargs, "buyer_email": ""}, success_url="", failure_url=""))
            except (GoPayUnavailable, GoPayRejected) as exc2:
                error = exc2

    if isinstance(error, GoPayUnavailable) or error.kind in ("duplicate", "other"):
        # Исход неизвестен, «дубликат» или ответ, который не удалось понять:
        # платёж у GoPay мог появиться. Повторное создание дало бы ошибку
        # дубликата, поэтому спрашиваем по НАШЕМУ номеру заказа.
        try:
            return _call(env, lambda: client.query_payment(order_id=payment.order_id))
        except GoPayError:
            raise error from None
    raise error


def create_invoice(payment, *, description: str, lifetime_seconds: int, buyer_email: str = "",
                   success_url: str = "", failure_url: str = "") -> GoPayInvoice:
    """Создать счёт у GoPay и сохранить его. Бросает GoPayError."""
    env = ((payment.request or {}).get("gopay") or {}).get("env")
    if env not in config.ENVS:
        raise GoPayError("у платежа не записана среда GoPay", code="not_configured",
                         kind="not_configured")
    if env == config.ENV_TEST and not config.is_staff_user(payment.user):
        # Второй рубеж правила «тест только сотрудникам» (первый — в покупке):
        # чтение настроек может откатиться к значению из окружения.
        raise GoPayError("тестовая среда только для сотрудников", code="test_non_staff",
                         kind="mismatch")
    if provider_down(env):
        # Быстрый отказ вместо двадцати секунд ожидания, пока GoPay лежит.
        raise GoPayUnavailable("GoPay временно недоступен", code="circuit_open")
    client = _client_for(env)

    # Срок считаем от момента ДО запроса: наш дедлайн не позже, чем у GoPay.
    t0 = timezone.now()
    success_url, failure_url = str(success_url or ""), str(failure_url or "")
    if not (RETURN_URL_RE.fullmatch(success_url) and RETURN_URL_RE.fullmatch(failure_url)):
        success_url = failure_url = ""
    if not config.send_buyer_email():
        buyer_email = ""
    kwargs = {"order_id": payment.order_id, "amount": payment.amount,
              "description": description, "lifetime": int(lifetime_seconds),
              "buyer_email": buyer_email}
    try:
        state = _create_or_adopt(client, env, payment, kwargs, success_url, failure_url)
    except ValueError:
        # Номер заказа длиннее 32 символов или сумма не до тыйына: это наша
        # ошибка, а не GoPay, и запрос никуда не уходил.
        raise GoPayError("некорректный заказ", code="bad_order", kind="mismatch") from None

    expects_test = env == config.ENV_TEST
    if state.order_id != (payment.order_id or "") or state.amount != payment.amount:
        _best_effort_cancel(client, env, state)
        raise GoPayError("ответ не про наш заказ", code="response_mismatch", kind="mismatch")
    if state.testing_mode is None or state.testing_mode != expects_test:
        # Ключи вставлены не в те поля (тестовые в боевые или наоборот).
        _best_effort_cancel(client, env, state)
        raise GoPayError("режим платежа не совпал со средой", code="mode_mismatch",
                         kind="mismatch")
    if not state.payment_id:
        raise GoPayError("нет номера платежа", code="incomplete_response", kind="mismatch")
    if not expects_test and not state.qr_data:
        # Боевой счёт без QR показать нечем. Тестовому QR не обязателен: он и так
        # «не предназначен для оплаты», а цепочку проверить нужно.
        _best_effort_cancel(client, env, state)
        raise GoPayError("нет данных QR", code="incomplete_response", kind="mismatch")
    if state.status not in ("created", "pending"):
        raise GoPayError("неожиданный статус нового счёта", code="unexpected_status",
                         kind="mismatch")

    try:
        # Точка сохранения: нарушение уникальности не должно отравить транзакцию запроса.
        with transaction.atomic():
            invoice = GoPayInvoice.objects.create(
                payment=payment, env=env, provider_payment_id=state.payment_id,
                status=state.status, amount=payment.amount,
                lifetime_seconds=int(lifetime_seconds), qr_data=state.qr_data,
                qr_url=_https(state.qr_url), checkout_url=_https(state.checkout_url),
                app_links=_safe_links(state.app_links),
                expires_at=t0 + timedelta(seconds=int(lifetime_seconds)),
                provider_expires_at=state.expires_at_raw, last_checked_at=timezone.now())
    except IntegrityError:
        raise GoPayError("такой счёт уже сохранён", code="duplicate_invoice",
                         kind="mismatch") from None
    # Только gopay_create: ни одной ссылки в response — иначе карточный код
    # принял бы счёт за ссылку на страницу банка.
    payment.response = {"gopay_create": dict(state.raw)}
    payment.save(update_fields=["response"])
    logger.info("gopay создан счёт order=%s payment_id=%s env=%s amount=%s",
                payment.order_id, state.payment_id, env, payment.amount)

    if not expects_test and not _apps_known(env) and not provider_down(env):
        refresh_apps_cache(env, client)
    return invoice


# ------------------------------------------------- применение статуса ---

def _is_late(inv, committed_at) -> bool:
    """Оплата пришла по счёту, который мы уже закрыли, оставили или чей срок вышел."""
    return (inv.status in GoPayInvoice.CLOSED_UNPAID or inv.cancel_requested_at is not None
            or committed_at > inv.expires_at + CANCEL_AFTER_EXPIRY)


def apply_state(invoice, state: PaymentState, *, source: str) -> str:
    """Применить состояние платежа у GoPay. Единственный путь зачисления.

    Итоги: credited / already / pending / closed / ignored / mismatch / no_user / failed.
    Для source="cancel" (ответ на наш запрос отмены) среда не сверяется:
    флаг testing_mode документация обещает только в ответах создания и статуса.
    """
    return _apply(invoice, state, source=source, check_mode=(source != "cancel"))


def _apply(invoice, state: PaymentState, *, source: str, check_mode: bool) -> str:
    if source not in SOURCES:
        raise ValueError(f"gopay: неизвестный источник состояния: {source}")
    from ..views import _credit_token_package_for_payment, _log_payment_event, _order_settled

    # Оплату без сверки среды не принимаем ни от кого: послабление для ответа на
    # отмену касается только закрытия счёта, но не зачисления.
    check_mode = check_mode or state.status == "committed"
    alert = ""
    with transaction.atomic():
        inv = GoPayInvoice.objects.select_for_update().get(pk=invoice.pk)
        pay = Payment.objects.select_for_update().get(pk=inv.payment_id)
        now = timezone.now()
        flags = dict(inv.flags or {})
        # Каким счёт был до этого ответа: по разнице решаем, писать ли событие в
        # журнал, и отличаем ПЕРВЫЙ увиденный COMMITTED от повторного.
        before = (inv.status, dict(flags), pay.success, pay.error)
        first_commit = inv.status != GoPayInvoice.STATUS_COMMITTED
        resp = pay.response or {}
        # «Закрыт для начислений»: уже начислено, начисленное изъято возвратом
        # или администратор отметил возврат. Отметка возврата бывает и без
        # начисления (оплачено, не зачислено, возвращено руками) — её
        # _order_settled не видит, поэтому проверяем отдельно.
        credited = _order_settled(pay, pay.order_id)
        refunded = bool(resp.get("admin_refund"))
        settled = credited or refunded
        committed = state.status == "committed"

        # 1. Наш ли это платёж. При любом расхождении не начисляем ничего.
        mismatch = ""
        if state.order_id and state.order_id != (pay.order_id or ""):
            mismatch = "order_id"
        elif state.payment_id and state.payment_id != inv.provider_payment_id:
            mismatch = "payment_id"
        elif committed and not (state.order_id and state.payment_id):
            mismatch = "ids_missing"
        elif check_mode and (state.testing_mode is None
                             or state.testing_mode != (inv.env == config.ENV_TEST)):
            mismatch = "mode"
        elif committed and (state.amount is None or state.amount != pay.amount
                            or inv.amount != pay.amount
                            or (pay.currency or "").upper() != "KGS"):
            mismatch = "amount"
        elif (committed and not settled and inv.env == config.ENV_TEST
              and not config.is_staff_user(pay.user)):
            mismatch = "test_non_staff"

        if mismatch:
            flags["needs_review"] = f"mismatch:{mismatch}"
            if (committed and mismatch in ("mode", "amount", "test_non_staff")
                    and inv.status != GoPayInvoice.STATUS_COMMITTED):
                # Номера наши, и GoPay говорит, что деньги пришли: счёт ОПЛАЧЕН И
                # НА РАЗБОРЕ. Его нельзя ни закрыть по нашим часам, ни показать
                # как «QR истёк», ни отпустить его скидку.
                committed_at = inv.committed_at or _aware(state.committed_at_raw) or now
                if _is_late(inv, committed_at):
                    flags["late_commit"] = True
                inv.status = GoPayInvoice.STATUS_COMMITTED
                inv.committed_at = committed_at
                inv.finalized_at = inv.finalized_at or now
                flags.pop("local_expiry", None)
            inv.flags = flags
            inv.last_checked_at = now
            inv.save()
            if not settled:
                pay.error = ("amount_mismatch" if mismatch == "amount"
                             else f"gopay_mismatch:{mismatch}")
                pay.save(update_fields=["error"])
            if committed:
                alert = f"mismatch:{mismatch}"
            result = "mismatch"
        else:
            # 2. Учёт.
            if source == "webhook":
                inv.last_webhook_at = now
            else:
                inv.last_checked_at = now
            flags.pop("not_found", None)        # GoPay этот платёж всё-таки знает
            if state.status != "unknown" and state.status != inv.status:
                _append_callback(pay, source, state)

            # 3. Статус.
            if committed:
                committed_at = inv.committed_at or _aware(state.committed_at_raw) or now
                # «Поздняя оплата» решается один раз — когда мы впервые видим
                # COMMITTED. Иначе перепроверка обычного оплаченного счёта через
                # день пометила бы поздним и его.
                if inv.status != GoPayInvoice.STATUS_COMMITTED and _is_late(inv, committed_at):
                    flags["late_commit"] = True
                inv.status = GoPayInvoice.STATUS_COMMITTED
                inv.committed_at = committed_at
                inv.bank_op_date = inv.bank_op_date or _date(state.bank_op_date)
                inv.finalized_at = inv.finalized_at or now
                flags.pop("local_expiry", None)
                if settled:
                    # Начислено, изъято или возврат отмечен: не начисляем и не
                    # трогаем ни success, ни error.
                    result = "already"
                    if (first_commit and not resp.get("token_purchase_applied")
                            and (refunded or resp.get("token_purchase_clawed_back"))):
                        # Платёж отметили возвращённым, пока QR ещё не был оплачен
                        # (отменить его у GoPay не вышло), — а деньги потом пришли.
                        # Зачислять нельзя, но и промолчать нельзя: это настоящие
                        # деньги, о которых никто не узнает.
                        flags["needs_review"] = "paid_after_refund_mark"
                        alert = "paid_after_refund_mark"
                elif not pay.user_id:
                    result = "no_user"
                    pay.error = "gopay_no_user"
                    alert = "no_user"
                else:
                    # До начисления: само начисление гасит скидку.
                    discount_moved = _discount_moved(pay)
                    pay.success, pay.error = True, ""
                    try:
                        # Точка сохранения: упавшее начисление не должно отравить
                        # транзакцию — статус счёта и ошибку ещё нужно записать.
                        with transaction.atomic():
                            _credit_token_package_for_payment(pay, pay.order_id,
                                                              defer_notify=True)
                        result = "credited"
                        if discount_moved:
                            # Оплачено со скидкой, которую этот платёж уже не держал.
                            flags["needs_review"] = "discount_reused"
                            alert = "discount_reused"
                    except Exception as exc:  # noqa: BLE001 — любая ошибка = «не зачислено»
                        logger.exception("gopay: начисление не удалось order=%s", pay.order_id)
                        pay.success = False
                        pay.error = f"token_purchase_apply_failed:{type(exc).__name__}"
                        result = "failed"
                        alert = "credit_failed"
            elif state.status in GoPayInvoice.CLOSED_UNPAID:
                if inv.status == GoPayInvoice.STATUS_COMMITTED or credited:
                    # Оплаченный заказ неоплаченным не становится.
                    flags["status_after_commit"] = state.provider_status
                    result = "ignored"
                else:
                    if inv.status in GoPayInvoice.OPEN_STATES:
                        inv.status = state.status
                        inv.finalized_at = now
                    # Закрытый счёт остаётся с первым статусом закрытия, но само
                    # закрытие теперь ПОДТВЕРЖДЕНО GoPay.
                    flags.pop("local_expiry", None)
                    if not refunded:
                        pay.success = False
                        pay.error = f"gopay_status:{inv.status}"
                    result = "closed"
            elif state.status in GoPayInvoice.OPEN_STATES:
                if (inv.status == GoPayInvoice.STATUS_CREATED
                        and state.status == GoPayInvoice.STATUS_PENDING):
                    inv.status = GoPayInvoice.STATUS_PENDING
                # Закрытый или оплаченный счёт заново не открываем; local_expiry
                # остаётся — GoPay закрытия не подтвердил.
                result = "pending"
            else:
                # Незнакомый статус — «ещё ждём»: ни успех, ни падение.
                flags["unknown_status"] = state.provider_status[:32]
                result = "pending"

            inv.flags = flags
            inv.save()
            if result != "already":
                pay.save(update_fields=["response", "success", "error"])
            else:
                pay.save(update_fields=["response"])

    # Вне блокировок, каждое — по мере сил.
    # В журнал событий — только то, что что-то изменило или требует человека.
    # Открытую вкладку опрашивают раз в пять секунд, сверка ходит каждую минуту:
    # строка «…pending FAIL» на каждый такой запрос (до двухсот на один
    # неоплаченный QR) похоронила бы под собой сигналы «нужен разбор», а чистить
    # журнал некому. Повтор того же закрытия, расхождения или той же ошибки
    # начисления — тоже не событие: о них раз в шесть часов напоминает _alert.
    if result == "credited":
        noteworthy = True
    elif result in ("pending", "already"):
        noteworthy = bool(alert)
    else:
        noteworthy = (inv.status, flags, pay.success, pay.error) != before
    if noteworthy:
        try:
            _log_payment_event(pay, f"gopay_{source}_{result}")
        except Exception:  # noqa: BLE001 — журнал не важнее денег
            logger.exception("gopay: не удалось записать событие оплаты")
    logger.info("gopay %s order=%s payment_id=%s -> %s%s", source, pay.order_id,
                inv.provider_payment_id, result, f" ({mismatch})" if mismatch else "")
    if alert:
        _alert(pay, inv, alert)
    return result


def fetch_state(invoice) -> PaymentState:
    """Один подписанный запрос статуса ключами среды СЧЁТА. Ничего не пишет."""
    client = _client_for(invoice.env)
    return _call(invoice.env,
                 lambda: client.query_payment(payment_id=invoice.provider_payment_id))


def _touch_checked(invoice, *, not_found: bool = False) -> None:
    with transaction.atomic():
        inv = GoPayInvoice.objects.select_for_update().get(pk=invoice.pk)
        now = timezone.now()
        inv.last_checked_at = now
        fields = ["last_checked_at", "updated_at"]
        if not_found:
            flags = dict(inv.flags or {})
            previous = flags.get("not_found")
            count = int(previous.get("count") or 0) if isinstance(previous, dict) else 0
            flags["not_found"] = {"count": count + 1, "at": now.isoformat()}
            inv.flags = flags
            fields.append("flags")
        inv.save(update_fields=fields)


def refresh_invoice(invoice, *, source: str = "query") -> str:
    """Спросить GoPay и применить ответ. GoPayUnavailable пробрасывается.

    Кроме итогов apply_state возвращает not_configured / not_found /
    provider_error. На предохранитель не смотрит — это дело вызывающего:
    человек, нажавший «перепроверить», и вебхук спрашивают всегда.
    """
    if source not in SOURCES:
        raise ValueError(f"gopay: неизвестный источник состояния: {source}")
    try:
        state = fetch_state(invoice)
    except GoPayUnavailable:
        raise
    except GoPayRejected as exc:
        if exc.provider_code == "4041":
            # Счётчик, а не приговор: счёт остаётся в сверке, а запись исчезнет
            # при первом же нормальном ответе.
            _touch_checked(invoice, not_found=True)
            return "not_found"
        logger.warning("gopay: статус не получен invoice=%s code=%s provider_code=%s",
                       invoice.pk, exc.code, exc.provider_code)
        _touch_checked(invoice)
        return "provider_error"
    except GoPayError as exc:
        if exc.kind == "not_configured":
            return "not_configured"
        logger.warning("gopay: статус не получен invoice=%s code=%s", invoice.pk, exc.code)
        return "provider_error"
    # Ответ на запрос статуса всегда сверяется со средой — даже если спросили
    # из-за отказа в отмене (source="cancel").
    return _apply(invoice, state, source=source, check_mode=True)


# ----------------------------------------------------------- отмена ---

def _reload(invoice) -> GoPayInvoice:
    return GoPayInvoice.objects.select_related("payment").get(pk=invoice.pk)


def _cancel_outcome(invoice, still_open: str) -> str:
    """Что стало со счётом после попытки отмены."""
    inv = _reload(invoice)
    if inv.status == GoPayInvoice.STATUS_COMMITTED or inv.payment.success:
        return "committed"
    if inv.status in GoPayInvoice.CLOSED_UNPAID and not (inv.flags or {}).get("local_expiry"):
        return "cancelled" if inv.status == GoPayInvoice.STATUS_CANCELLED else "closed"
    # Открыт — или закрыт только нашими часами, что для GoPay то же самое.
    return still_open


def _requery_after_refusal(invoice, still_open: str) -> str:
    try:
        refresh_invoice(invoice, source="cancel")
    except Exception:  # noqa: BLE001 — не узнали состояние: считаем счёт открытым
        return still_open
    return _cancel_outcome(invoice, still_open)


def cancel_invoice(invoice, *, reason: str = "") -> str:
    """Отменить неоплаченный счёт у GoPay.

    Итоги: cancelled / committed / closed / not_open / busy / retry.
    busy — «банк прямо сейчас работает с этим QR»: покупателя нельзя отпускать
    платить другим способом. retry — «GoPay не смог отменить, но на оплату
    ничто не указывает». До вызова GoPay ничего не пишется и не блокируется.
    """
    inv = _reload(invoice)
    if inv.status == GoPayInvoice.STATUS_COMMITTED or inv.payment.success:
        return "committed"
    if inv.status in GoPayInvoice.CLOSED_UNPAID and not (inv.flags or {}).get("local_expiry"):
        # Закрытие, сделанное только нашими часами, сюда не попадает: что с
        # таким счётом у GoPay, неизвестно, и отменить его там всё равно нужно.
        return "not_open"

    try:
        client = _client_for(inv.env)
        state = _call(inv.env,
                      lambda: client.cancel_payment(payment_id=inv.provider_payment_id))
    except GoPayRejected as exc:
        if exc.kind == "cannot_cancel":
            # Код 0013 значит в том числе «банк уже подтвердил оплату, GoPay её
            # дообрабатывает». Поэтому не «счёт мёртв», а сразу спросить статус.
            return _requery_after_refusal(inv, "busy")
        if exc.kind == "cancel_retry":
            return "retry"
        # Незнакомый отказ (или метода отмены у GoPay нет вовсе): узнаём
        # настоящее состояние; на оплату при этом ничто не указывает.
        return _requery_after_refusal(inv, "retry")
    except GoPayError:
        return "retry"

    if state.status == "committed":
        # На отмену ответили «оплачен». По такому ответу не зачисляем: пусть
        # решает обычный запрос статуса со всеми сверками.
        return _requery_after_refusal(inv, "busy")
    apply_state(inv, state, source="cancel")
    outcome = _cancel_outcome(inv, "busy")
    if outcome in ("cancelled", "closed"):
        with transaction.atomic():
            locked = GoPayInvoice.objects.select_for_update().get(pk=inv.pk)
            flags = dict(locked.flags or {})
            flags["cancel_reason"] = str(reason or "")[:40]
            locked.flags = flags
            locked.cancel_requested_at = locked.cancel_requested_at or timezone.now()
            locked.save(update_fields=["flags", "cancel_requested_at", "updated_at"])
    return outcome


def mark_abandoned(invoice, reason: str) -> bool:
    """Покупатель оставил QR, а GoPay его (пока) не отменил.

    С этого момента счёт не показывается, к нему не возвращаются и скидку он
    не держит. Статус и платёж не трогаем: счёт остаётся в сверке, и поздний
    COMMITTED по нему всё равно зачислится.
    """
    with transaction.atomic():
        inv = GoPayInvoice.objects.select_for_update().get(pk=invoice.pk)
        Payment.objects.select_for_update().get(pk=inv.payment_id)
        flags = dict(inv.flags or {})
        applies = inv.status in GoPayInvoice.OPEN_STATES or (
            inv.status == GoPayInvoice.STATUS_EXPIRED and flags.get("local_expiry"))
        if not applies or inv.cancel_requested_at is not None:
            return False
        inv.cancel_requested_at = timezone.now()
        flags["abandoned"] = str(reason or "")[:24]
        inv.flags = flags
        inv.save(update_fields=["cancel_requested_at", "flags", "updated_at"])
        return True


def mark_expired_locally(invoice) -> bool:
    """Закрыть счёт своими часами, когда GoPay спросить не удаётся.

    Не истина о деньгах: пометка local_expiry держит счёт в сверке, пока GoPay
    сам не назовёт конечный статус, и скидку такой счёт не отпускает. Срок
    проверяется здесь же, а не только у вызывающего.
    """
    from ..views import _order_settled

    with transaction.atomic():
        inv = GoPayInvoice.objects.select_for_update().get(pk=invoice.pk)
        pay = Payment.objects.select_for_update().get(pk=inv.payment_id)
        now = timezone.now()
        if inv.status not in GoPayInvoice.OPEN_STATES:
            return False
        if now < inv.expires_at + LOCAL_EXPIRY_GRACE:
            return False
        flags = dict(inv.flags or {})
        flags["local_expiry"] = True
        inv.flags = flags
        inv.status = GoPayInvoice.STATUS_EXPIRED
        inv.finalized_at = now
        inv.save(update_fields=["flags", "status", "finalized_at", "updated_at"])
        settled = _order_settled(pay, pay.order_id) or bool((pay.response or {}).get("admin_refund"))
        if not settled:
            pay.success = False
            pay.error = "gopay_status:expired"
            pay.save(update_fields=["success", "error"])
        return True


# ------------------------------------------------- экран оплаты (JSON) ---

def ui_state(invoice) -> str:
    """Состояние для экрана оплаты — коротко и без внутренней кухни."""
    payment = invoice.payment
    resp = payment.response or {}
    if payment.success:
        return "paid"
    if invoice.status == GoPayInvoice.STATUS_COMMITTED:
        if resp.get("admin_refund") or resp.get("token_purchase_clawed_back"):
            return "cancelled"          # оплачен, потом возвращён руками
        return "processing"             # деньги пришли, зачисление впереди или на разборе
    if invoice.status == GoPayInvoice.STATUS_FAILED:
        return "failed"
    if invoice.status == GoPayInvoice.STATUS_CANCELLED:
        return "cancelled"
    if invoice.status == GoPayInvoice.STATUS_EXPIRED:
        return "expired"
    if invoice.cancel_requested_at is not None:
        return "cancelled"              # оставлен: у GoPay ещё открыт, но больше не показываем
    if timezone.now() >= invoice.expires_at:
        return "expired"
    return "awaiting_payment"


def invoice_json(invoice, *, resumed: bool = False) -> dict:
    """Счёт в том виде, в каком его показывает экран оплаты. Набор ключей постоянен."""
    payment = invoice.payment
    request = payment.request or {}
    purchase = request.get("token_purchase") or {}
    tokens = int(purchase.get("tokens") or 0)
    bonus = int(purchase.get("bonus_tokens") or 0)
    total = tokens + bonus
    state = ui_state(invoice)
    awaiting = state == "awaiting_payment"
    now = timezone.now()

    original_amount = discount_percent = None
    discount = request.get("exit_discount")
    if isinstance(discount, dict) and discount:
        try:
            original_amount = _money(str(discount.get("original_amount")))
        except (InvalidOperation, TypeError, ValueError):
            original_amount = None
        try:
            discount_percent = int(discount.get("percent"))
        except (TypeError, ValueError):
            discount_percent = None

    return {
        "kind": "qr",
        "provider": "gopay",
        "resumed": bool(resumed),
        "order_id": payment.order_id,
        "status": invoice.status,
        "ui_state": state,
        "amount": _money(payment.amount),
        "currency": "KGS",
        "original_amount": original_amount,
        "discount_percent": discount_percent,
        "package": {
            "id": purchase.get("package_id"),
            "name": str((request.get("gopay") or {}).get("package_name") or ""),
            "tokens": tokens,
            "bonus_tokens": bonus,
        },
        "credits": {"total": total, "credited": total if payment.success else 0},
        # QR и ссылки отдаём, только пока по ним можно платить.
        "qr": {"data": invoice.qr_data if awaiting else "",
               "image_url": invoice.qr_url if awaiting else ""},
        # Тестовый QR не оплачивается — кнопки банков там обещали бы лишнее.
        "apps": apps_for(invoice) if (awaiting and invoice.env != config.ENV_TEST) else [],
        "checkout_url": invoice.checkout_url if awaiting else "",
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
        "expires_at": invoice.expires_at.isoformat(),
        "server_time": now.isoformat(),
        "seconds_left": max(0, int((invoice.expires_at - now).total_seconds())),
        "lifetime_seconds": int(invoice.lifetime_seconds),
        "is_test": bool(payment.is_test),
        "can_cancel": awaiting,
        "return_to": request.get("return_to") or "",
    }


# ------------------------------------------------------------ вебхук ---

def verify_webhook(nonce: str, signature: str, raw_body: bytes) -> list[str]:
    """Среды, чей секрет вебхуков подтверждает это тело. Пусто — подпись неверна.

    Один секрет на точку или свой на среду — у GoPay не описано, поэтому
    пробуем все заданные. Одинаковые секреты в обеих средах дают обе среды.
    """
    try:
        return [env for env, secret in config.webhook_secrets()
                if _client.verify_signature(secret, nonce, raw_body, signature)]
    except Exception:  # noqa: BLE001 — сбой проверки = подпись не принята
        return []


def event_key(event: str, state: PaymentState, envelope_created_at: str) -> str:
    """Ключ события для журнала: номера события у GoPay нет, собираем сами."""
    text = (f"gopay|{state.payment_id}|{event}|{state.provider_status}|"
            f"{envelope_created_at}")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_event(body: dict) -> dict:
    """Тело события для журнала: только белый список полей, ничего лишнего."""
    if not isinstance(body, dict):
        return {"event": "", "created_at": "", "data": {}}
    event = body.get("event")
    created_at = body.get("created_at")
    data = body.get("data")
    clean = dict(PaymentState.from_payload(data).raw)
    if event == "receipt.sent" and isinstance(data, dict):
        url = data.get("receipt_url")
        if isinstance(url, str) and _https(url):
            clean["receipt_url"] = url
    return {"event": event[:48] if isinstance(event, str) else "",
            "created_at": created_at[:40] if isinstance(created_at, str) else "",
            "data": clean}


# ---------------------------------------------- банковские приложения ---

def _apps_key(env: str) -> str:
    return f"gopay:apps:v1:{env}"


def _apps_last_key(env: str) -> str:
    return f"gopay:apps:last:{env}"


def _apps_known(env: str) -> bool:
    """Список уже спрашивали (пусть он и пуст) — или недавно не смогли получить.

    Нужно только покупке: она не должна на каждом счёте заново ждать ответа
    GoPay о банках, если у ключа их нет или метод сейчас не отвечает.
    """
    try:
        return (cache.get(_apps_key(env)) is not None
                or bool(cache.get(_apps_last_key(env)))
                or bool(cache.get(f"gopay:apps:fail:{env}")))
    except Exception:  # noqa: BLE001
        return True


def apps_fresh(env: str) -> bool:
    """Есть ли свежая (не старше шести часов) копия списка банков, пусть и пустая.

    Нужно сверке: «последний удачный» список живёт неделю и годится только как
    запас. Если считать его за «список известен», свежая копия не обновлялась
    бы ни разу за эту неделю — банк, который GoPay добавил, убрал или выключил
    на iPhone, висел бы со старыми данными, а запас истёк бы одновременно с ней.
    В сеть не ходит.
    """
    try:
        return cache.get(_apps_key(env)) is not None
    except Exception:  # noqa: BLE001 — кэш лежит: обновлять всё равно некуда
        return True


def refresh_apps_cache(env: str, client: GoPayClient | None = None) -> list[dict]:
    """Обновить список банков из GoPay. Не бросает: при сбое отдаёт то, что в кэше."""
    try:
        client = client or _client_for(env)
        apps = _call(env, lambda: client.payment_apps("any"))
        # Самые популярные — первыми: предел не должен отрезать главный банк страны.
        apps = sorted(apps, key=lambda a: a.get("order", 999))[:APPS_MAX]
        cache.set(_apps_key(env), apps, APPS_CACHE_TTL)
        if apps:
            # Пустой ответ не затирает последний непустой список: банки не
            # исчезают все разом, а сбой на стороне GoPay — бывает.
            cache.set(_apps_last_key(env), apps, APPS_LAST_GOOD_TTL)
            return apps
        return cached_apps(env)
    except Exception:  # noqa: BLE001 — кнопки банков не важнее самой оплаты
        try:
            cache.set(f"gopay:apps:fail:{env}", 1, _APPS_FAIL_TTL)
        except Exception:  # noqa: BLE001
            pass
        return cached_apps(env)


def cached_apps(env: str) -> list[dict]:
    """Список банков из кэша. В сеть не ходит никогда."""
    try:
        for key in (_apps_key(env), _apps_last_key(env)):
            apps = cache.get(key)
            if isinstance(apps, list) and apps:
                return [a for a in apps if isinstance(a, dict) and a.get("code")]
    except Exception:  # noqa: BLE001
        pass
    return []


def apps_for(invoice) -> list[dict]:
    """Кнопки банков для этого счёта: готовые ссылки GoPay, иначе — по шаблонам."""
    catalog = {a["code"]: a for a in cached_apps(invoice.env)}
    links = _safe_links(invoice.app_links or {})
    if not links and invoice.qr_data:
        # Шаблон подставляем как есть, без URL-кодирования — так делает пример
        # самого GoPay.
        built = {}
        for entry in sorted(catalog.values(), key=lambda a: (a.get("order", 999), a["code"])):
            template = entry.get("url") or ""
            if "{qr_data}" in template:
                built[entry["code"]] = template.replace("{qr_data}", invoice.qr_data)
        links = _safe_links(built)

    items = []
    for code, url in links.items():
        entry = catalog.get(code)       # None — список GoPay этого кода не знает
        order = entry.get("order", 999) if entry is not None else 999
        items.append((order if isinstance(order, int) else 999, {
            "code": code,
            "name": (entry or {}).get("name") or code.capitalize(),
            "url": url,
            "icon": _https((entry or {}).get("icon") or ""),
            # True / False / None. False обязан дойти до клиента: банк, которого
            # нет на iPhone, там прячут — поэтому никаких «x or None».
            "ios": entry.get("is_active_on_ios") if entry is not None else None,
            # True или None, но не False: признака «на Android недоступен» у GoPay
            # нет вовсе. android_package_name — это всего лишь имя пакета в
            # магазине, и пустое поле значит «не знаем», а не «спрячь банк» —
            # тем более что готовую ссылку на этот банк GoPay прислал сам.
            "android": (True if entry is not None and entry.get("android_package_name")
                        else None),
        }))
    items.sort(key=lambda pair: (pair[0], pair[1]["name"]))
    return [item for _, item in items][:APPS_MAX]


# --------------------------------------------- здоровье и предохранитель ---

def _health_key(env: str) -> str:
    return f"gopay:health:{env}"


def _down_key(env: str) -> str:
    return f"gopay:down:{env}"


def note_result(env: str, exc: GoPayError | None = None) -> None:
    """Учесть исход обращения к GoPay. Не бросает: кэш не должен ломать оплату."""
    try:
        if exc is not None and getattr(exc, "code", "") == "circuit_open":
            return                      # наш собственный быстрый отказ — не событие
        # По классу причины, а не по классу исключения: проверка соединения в
        # админке собирает исход из словаря, и он должен считаться так же.
        if exc is None or exc.kind not in _FAILING_KINDS:
            # GoPay ответил и принял нас — даже отказ значит, что он жив.
            cache.delete_many([_health_key(env), _down_key(env)])
            return
        previous = cache.get(_health_key(env))
        previous = previous if isinstance(previous, dict) else {}
        fails = int(previous.get("fails") or 0) + 1
        cache.set(_health_key(env), {
            "fails": fails, "kind": exc.kind, "code": exc.code,
            "since": previous.get("since") or timezone.now().isoformat(),
        }, _HEALTH_TTL)
        if exc.kind == "unavailable" and fails >= DOWN_AFTER_FAILURES:
            cache.set(_down_key(env), 1, DOWN_TTL)
        if fails >= ALERT_AFTER_FAILURES and cache.add(f"gopay:alert:{env}", 1, ALERT_EVERY):
            _log_event(
                "payment",
                message=(f"GoPay ({env}): {fails} запросов подряд без результата "
                         f"({exc.kind}/{exc.code})"),
                level="error", meta={"gopay_health": exc.kind, "env": env, "fails": fails})
            logger.error("gopay (%s): %s запросов подряд без результата (%s/%s)",
                         env, fails, exc.kind, exc.code)
    except Exception:  # noqa: BLE001
        pass


def provider_down(env: str) -> bool:
    """Сработал ли предохранитель: GoPay только что несколько раз не ответил."""
    try:
        return bool(cache.get(_down_key(env)))
    except Exception:  # noqa: BLE001
        return False


def health(env: str) -> dict:
    state = {"ok": True, "fails": 0, "kind": "", "code": "", "since": None, "down": False}
    try:
        data = cache.get(_health_key(env))
        if isinstance(data, dict) and int(data.get("fails") or 0) > 0:
            state.update({"ok": False, "fails": int(data.get("fails") or 0),
                          "kind": str(data.get("kind") or ""),
                          "code": str(data.get("code") or ""),
                          "since": data.get("since") or None})
        state["down"] = provider_down(env)
    except Exception:  # noqa: BLE001
        pass
    return state


def _unsettled_queryset():
    return GoPayInvoice.objects.select_related("payment").filter(
        status=GoPayInvoice.STATUS_COMMITTED, payment__success=False)


def _is_unsettled(invoice) -> bool:
    # Сверяем в Python, а не фильтром по JSON: строк таких единицы, а исключение
    # по ключу JSON ведёт себя по-разному на SQLite (тесты) и PostgreSQL (бой).
    resp = invoice.payment.response or {}
    return not (resp.get("admin_refund") or resp.get("token_purchase_clawed_back"))


def in_flight_count(env: str) -> int:
    """Сколько счетов среды ещё могут изменить исход (и потому нуждаются в ключах)."""
    now = timezone.now()
    closed = Q(status__in=GoPayInvoice.CLOSED_UNPAID)
    moving = GoPayInvoice.objects.filter(env=env).filter(
        Q(status__in=GoPayInvoice.OPEN_STATES)
        | (closed & Q(finalized_at__gte=now - LATE_SWEEP_WINDOW))
        | (closed & Q(flags__has_key="local_expiry")
           & Q(finalized_at__gte=now - UNCONFIRMED_SWEEP_WINDOW))
    ).count()
    unsettled = sum(1 for inv in _unsettled_queryset().filter(env=env) if _is_unsettled(inv))
    return moving + unsettled


def admin_state() -> dict:
    """Живая часть блока GoPay в админке: здоровье, незавершённые счета, «оплачено, не зачислено»."""
    return {
        "health": {env: health(env) for env in config.ENVS},
        "in_flight": {env: in_flight_count(env) for env in config.ENVS},
        "unsettled": sum(1 for inv in _unsettled_queryset() if _is_unsettled(inv)),
    }
