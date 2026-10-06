from __future__ import annotations

# Сверка «повисших» оплат FreedomPay.
#
# Кредиты начисляет подписанное server-to-server уведомление FreedomPay
# (POST /api/payments/tokens/postback/). До 02.10.2026 мы отвечали на него 400:
# подпись проверялась с именем скрипта «postback», а FreedomPay для адреса со
# слэшем на конце подписывает с пустым именем. Теперь подпись сходится, но
# уведомление всё равно может потеряться (наш сервер был недоступен), а
# браузерный success — презентационный и не начисляет.
#
# Поэтому сверка остаётся страховкой: сами спрашиваем статус у FreedomPay через их
# API get_status2 (исходящий запрос) и начисляем подтверждённые оплаты. Запускается
# по расписанию (beat, каждые ~2 мин) И мгновенно на возврате пользователя из
# оплаты (см. FreedomPayTokenPurchaseSuccessView). Полностью идемпотентно.

import logging
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import timedelta
from decimal import Decimal

import requests
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

_RECON_LOCK = "payments:reconcile:lock"


def _status_url() -> str:
    """URL get_status2 в той же папке, что и init_payment (https://api.freedompay.kg/get_status2.php)."""
    init = (getattr(settings, "FREEDOM_PAY_INIT_PAYMENT_URL", "") or "").rstrip("/")
    base = init.rsplit("/", 1)[0] if "/" in init else init
    return f"{base}/get_status2.php"


def fetch_payment_status(order_id: str) -> dict:
    """Спросить у FreedomPay статус платежа по order_id. Возвращает распарсенный
    XML как dict или {} при любой ошибке (никогда не бросает)."""
    from .freedompay import make_api_signature

    merchant = str(getattr(settings, "FREEDOM_PAY_MERCHANT_ID", "") or "")
    secret = getattr(settings, "FREEDOM_PAY_TOKEN", "") or ""
    if not (merchant and secret and order_id):
        return {}
    params = {
        "pg_merchant_id": merchant,
        "pg_order_id": order_id,
        "pg_salt": "recon" + str(order_id)[-10:],
    }
    params["pg_sig"] = make_api_signature("get_status2.php", params, secret)
    try:
        r = requests.post(_status_url(), data=params, timeout=25)
        root = ET.fromstring(r.text)
        return {child.tag: (child.text or "").strip() for child in root}
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_payment_status failed order=%s: %s", order_id, exc)
        return {}


def _package_id_from_order(order_id: str) -> int | None:
    # tokpkg-<user>-<pkg>-<rand>
    parts = (order_id or "").split("-")
    if len(parts) >= 3 and parts[0] == "tokpkg":
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


def _verify_and_credit(payment) -> str:
    """Проверить статус у FreedomPay и начислить пакет, если ОПЛАЧЕНО и подтверждено.

    Гейты: pg_status=ok, pg_transaction_status ∈ {ok,success,captured}, сумма и
    валюта совпадают с заказом. Начисление идемпотентно (по TokenTransaction
    reason='purchase' + meta.order_id и флагу token_purchase_applied). Уведомление
    отправляется ПОСЛЕ коммита (best-effort), чтобы сбой почты не откатил кредит.
    """
    from .models import Payment
    from plans.models import TokenPackage, TokenTransaction
    from plans.wallet import credit_tokens

    order_id = payment.order_id
    st = fetch_payment_status(order_id)
    if not st:
        return "no_status"
    ok = str(st.get("pg_status") or "").lower() == "ok"
    tx_ok = str(st.get("pg_transaction_status") or "").lower() in {"ok", "success", "captured"}
    if not (ok and tx_ok):
        return f"not_paid:{st.get('pg_status')}/{st.get('pg_transaction_status')}"

    # Сверка суммы и валюты с заказом (защита от подмены/бага провайдера).
    try:
        amt_ok = Decimal(str(st.get("pg_amount") or "0")) == (payment.amount or Decimal("0"))
    except Exception:
        amt_ok = False
    cur = str(st.get("pg_currency") or "").upper()
    cur_ok = (not cur) or (cur == (payment.currency or "").upper())
    if not (amt_ok and cur_ok):
        logger.warning(
            "reconcile amount/currency mismatch order=%s api_amt=%s api_cur=%s pay=%s %s",
            order_id, st.get("pg_amount"), cur, payment.amount, payment.currency,
        )
        return "amount_mismatch"

    pkg_id = _package_id_from_order(order_id)
    info = (payment.request or {}).get("token_purchase") or {}
    # Начисляем по снапшоту, зафиксированному в момент покупки (см. комментарий
    # в payments/views.py::_credit_token_package_for_payment) — а не по текущей
    # живой конфигурации TokenPackage, которая могла измениться за время между
    # инициацией оплаты и этим reconcile-проходом.
    total = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
    if total <= 0:
        try:
            pkg = TokenPackage.objects.get(pk=int(pkg_id))
            total = int(pkg.tokens or 0) + int(pkg.bonus_tokens or 0)
        except Exception:
            total = 0
    if total <= 0:
        return "zero_amount"

    credited_now = False
    with transaction.atomic():
        pp = Payment.objects.select_for_update().get(pk=payment.pk)
        already = TokenTransaction.objects.filter(
            user=pp.user, reason="purchase", meta__order_id=order_id
        ).exists()
        if not already:
            credit_tokens(pp.user, total, "purchase", meta={
                "order_id": order_id, "package_id": pkg_id, "tokens": total,
                "bonus_tokens": 0, "source": "status_reconcile",
            })
            credited_now = True
        resp = pp.response or {}
        cbs = list(resp.get("callbacks") or [])
        cbs.append({"type": "status_reconcile", "payload": st})
        resp["callbacks"] = cbs
        resp["token_purchase_applied"] = True
        pp.response = resp
        pp.success = True
        pp.save(update_fields=["response", "success"])

    # Exit-discount: пометить redeemed_at, если скидка была применена к этому
    # платежу (best-effort, отдельной транзакцией — сбой НЕ должен откатывать
    # или ронять уже совершённое начисление токенов покупателю).
    if credited_now:
        try:
            from .views import _mark_exit_discount_redeemed
            _mark_exit_discount_redeemed(payment)
        except Exception:  # noqa: BLE001
            logger.exception("exit_discount_redeem_mark_failed order=%s", order_id)

    # Реферальная revenue-share выплата пригласившему (ПОСЛЕ коммита покупки,
    # отдельной транзакцией). Пригласивший получает % от КУПЛЕННЫХ кредитов —
    # пожизненно, при каждом пополнении. Сама выплата живёт в payments/referral.py
    # (общая для всех провайдеров), идемпотентна по order_id и не роняет покупку.
    if credited_now:
        from .referral import settle_referral

        settle_referral(payment, order_id, total)

    # После коммита — пометить платным + уведомить (не критично, не роняем кредит).
    if credited_now:
        try:
            from .views import _mark_user_paid, _notify_balance_topup
            _mark_user_paid(payment.user)
            _notify_balance_topup(payment.user, total)
        except Exception as exc:  # noqa: BLE001
            logger.warning("post-credit notify failed order=%s: %s", order_id, exc)
    return "credited" if credited_now else "already"


def _has_payment_marker(p) -> bool:
    for cb in (p.response or {}).get("callbacks") or []:
        payload = (cb or {}).get("payload") or {}
        if not payload.get("pg_payment_id"):
            continue
        # Уведомление о НЕуспешной оплате тоже несёт pg_payment_id, но признаком
        # оплаты не служит: иначе каждый отказ карты опрашивался бы у FreedomPay
        # каждые две минуты всю неделю. Свежий заказ и так проверяется два часа.
        if cb.get("type") == "post" and str(payload.get("pg_result") or "1").strip() != "1":
            continue
        return True
    return False


@shared_task(name="payments.tasks.reconcile_pending_token_payments")
def reconcile_pending_token_payments() -> dict:
    """Сверить оплаченные, но не начисленные token-заказы и начислить подтверждённые.

    Идемпотентно и защищено локом. Дёргаем FreedomPay-статус только для заказов,
    где есть признак оплаты (pg_payment_id) ИЛИ совсем свежих (<2ч) — чтобы не
    молотить API по заброшенным init'ам.
    """
    if not cache.add(_RECON_LOCK, "1", timeout=110):
        return {"status": "busy"}
    try:
        from .models import Payment
        from plans.models import TokenTransaction

        now = timezone.now()
        window = now - timedelta(days=7)
        recent = now - timedelta(hours=2)
        pays = (
            Payment.objects
            .filter(order_id__startswith="tokpkg-", created_at__gte=window)
            .exclude(user=None)
            # Крипту сверяет своя задача: у неё другой процессор, другой смысл
            # статусов и начисление по частям. Спрашивать про неё FreedomPay
            # бессмысленно, а «нет такого заказа» ещё и засоряет журнал.
            .exclude(provider__startswith="crypto_")
            # Рублёвые заказы идут через ЮKassa — у них своя сверка ниже.
            .exclude(provider="yookassa")
            # Единый QR — это GoPay: номера заказов те же «tokpkg-», но FreedomPay
            # о них ничего не знает. Их сверяет reconcile_gopay_invoices.
            .exclude(provider="gopay")
            # Уже зачисленные отсекаем в запросе, а не после среза: иначе
            # шестьдесят свежих брошенных заказов выталкивали из окна старый
            # оплаченный, и его больше никто не проверял.
            .exclude(success=True)
            .order_by("-id")[:200]
        )
        checked = credited = 0
        for p in pays:
            if TokenTransaction.objects.filter(
                user=p.user, reason="purchase", meta__order_id=p.order_id
            ).exists():
                continue
            if not (_has_payment_marker(p) or p.created_at >= recent):
                continue
            checked += 1
            try:
                if _verify_and_credit(p) == "credited":
                    credited += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile order=%s failed: %s", p.order_id, exc)
        if credited:
            logger.info("reconcile_pending_token_payments checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_RECON_LOCK)


# --------------------------------------------------------------- ЮKassa ---

_YK_RECON_LOCK = "payments:yookassa_reconcile:lock"


@shared_task(name="payments.tasks.reconcile_yookassa_payments")
def reconcile_yookassa_payments() -> dict:
    """Досверка рублёвых оплат: спросить ЮKassa про незакрытые заказы.

    Вебхук — основной путь, но он приходит один раз на событие. Если наш сервер
    был недоступен или ответил ошибкой, оплаченный заказ без этой задачи так и
    остался бы без кредитов. Смотрим заказы за последние сутки, которые ещё не
    зачислены и не отменены, и применяем ответ API тем же кодом, что и вебхук.
    """
    if not cache.add(_YK_RECON_LOCK, "1", timeout=240):
        return {"status": "busy"}
    try:
        from . import yookassa as yk
        from .models import Payment
        from .views import apply_yookassa_state

        if not (getattr(settings, "YOOKASSA_SHOP_ID", "") and getattr(settings, "YOOKASSA_SECRET_KEY", "")):
            return {"status": "disabled"}
        since = timezone.now() - timedelta(hours=24)
        pays = (Payment.objects
                .filter(provider="yookassa", success=False, created_at__gte=since)
                .exclude(user=None)
                .order_by("-id")[:100])
        checked = credited = 0
        for p in pays:
            # Платёж, отмеченный возвращённым: ЮKassa по-прежнему отвечает
            # «оплачен», и сверка вернула бы ему success=True, стерев отметку.
            resp = p.response or {}
            if resp.get("admin_refund") or resp.get("token_purchase_clawed_back") or resp.get("yookassa_refunded"):
                continue
            if str(p.error or "").startswith(("yookassa_status:", "amount_mismatch")):
                continue  # отменён или сумма не сошлась — решено окончательно
            yk_id = str((p.request or {}).get("yookassa_payment_id") or "").strip()
            if not yk_id:
                continue
            checked += 1
            try:
                if apply_yookassa_state(p, yk.fetch_payment(yk_id), source="yookassa_reconcile") == "credited":
                    credited += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("yookassa reconcile order=%s failed: %s", p.order_id, exc)
        if credited:
            logger.info("reconcile_yookassa_payments checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_YK_RECON_LOCK)


# --------------------------------------------------------------- крипта ---

_CRYPTO_LOCK = "payments:crypto_reconcile:lock"


@shared_task(name="payments.tasks.check_crypto_invoice", bind=True,
             max_retries=3, default_retry_delay=30)
def check_crypto_invoice(self, invoice_id: int) -> str:
    """Спросить процессор про один счёт и применить ответ.

    Ставится из открытой вкладки (человек смотрит на таймер) и из сверки.
    Недоступность процессора — повод повторить, а не потерять оплату.
    """
    from .crypto import credit as crypto_credit
    from .crypto import registry as crypto_registry
    from .crypto.base import ProviderError, ProviderUnavailable
    from .models import CryptoInvoice

    invoice = CryptoInvoice.objects.select_related("payment").filter(pk=invoice_id).first()
    if invoice is None:
        return "missing"
    try:
        state = crypto_registry.get_adapter(invoice.provider).fetch_invoice(
            invoice.provider_invoice_id)
    except ProviderUnavailable as exc:
        raise self.retry(exc=exc)
    except ProviderError as exc:
        logger.warning("crypto: счёт %s не проверить: %s", invoice.provider_invoice_id, exc)
        return "provider_error"
    return crypto_credit.apply_provider_status(invoice, state, source="reconcile")


@shared_task(name="payments.tasks.reconcile_crypto_invoices")
def reconcile_crypto_invoices() -> dict:
    """Сверка криптосчетов: деньги в блокчейне есть, а вебхук мог не дойти.

    Смотрим живые счета и — редко, раз в несколько часов — те, что закрылись
    без оплаты: перевод, отправленный после таймера, всё равно наш и должен
    быть зачислен.
    """
    from django.db.models import Q

    from .crypto import credit as crypto_credit
    from .models import CryptoInvoice

    if not cache.add(_CRYPTO_LOCK, "1", timeout=110):
        return {"status": "busy"}
    try:
        now = timezone.now()
        window = now - timedelta(days=7)
        slow_sweep = now - timedelta(hours=6)
        invoices = (
            CryptoInvoice.objects
            .select_related("payment")
            .filter(
                Q(status__in=list(CryptoInvoice.OPEN_STATES), created_at__gte=window)
                | Q(status__in=[CryptoInvoice.STATUS_EXPIRED, CryptoInvoice.STATUS_FAILED],
                    credited_tokens=0, created_at__gte=window)
                & (Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=slow_sweep))
            )
            .exclude(payment__user=None)
            .order_by("last_checked_at")[:60]
        )
        checked = credited = 0
        for invoice in invoices:
            # Просроченный и неоплаченный счёт помечаем сами: процессор иногда
            # тянет со статусом, а человек не должен смотреть на таймер,
            # которого уже нет. Перепроверять его это не мешает.
            if (invoice.status == CryptoInvoice.STATUS_WAITING
                    and invoice.actually_paid == 0):
                try:
                    crypto_credit.mark_expired_locally(invoice)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("crypto: не пометить просроченным %s: %s",
                                   invoice.provider_invoice_id, exc)
            try:
                result = check_crypto_invoice(invoice.id)
                checked += 1
                credited += 1 if result == "credited" else 0
            except Exception as exc:  # noqa: BLE001 — один счёт не роняет сверку
                logger.warning("crypto: сверка счёта %s не удалась: %s",
                               invoice.provider_invoice_id, exc)
        if credited:
            logger.info("reconcile_crypto_invoices checked=%s credited=%s", checked, credited)
        return {"status": "ok", "checked": checked, "credited": credited}
    finally:
        cache.delete(_CRYPTO_LOCK)


# ------------------------------------------------------ единый QR (GoPay) ---
#
# Все три задачи идут в общей очереди: один воркер на два слота, которые делят
# сверки FreedomPay, крипты, Stars и уведомления. Зависший GoPay не должен её
# занять — отсюда предохранитель, бюджет времени на проход и не больше одного
# повтора перепроверки.

_GOPAY_LOCK = "payments:gopay_reconcile:lock"
# Замок живёт дольше бюджета прохода: после проверки бюджета может уйти ещё
# один запрос (до 15 с), и следующий проход не должен стартовать поверх.
_GOPAY_LOCK_TTL = 120
_GOPAY_BUDGET_SECONDS = 40
_GOPAY_OPEN_WINDOW = timedelta(hours=48)
_GOPAY_OPEN_RECHECK = timedelta(seconds=20)
_GOPAY_SLICE = 40          # срезы A1 и A2
_GOPAY_SWEEP = 20          # B1, B2, D
_GOPAY_APPS_RETRY = 600    # как часто сверка пробует обновить список банков, секунды


def _clock() -> float:
    """Монотонные часы прохода (отдельной функцией — чтобы тест мог их подменить)."""
    return time.monotonic()


@shared_task(name="payments.tasks.check_gopay_invoice", bind=True,
             max_retries=1, default_retry_delay=20)
def check_gopay_invoice(self, invoice_id: int) -> str:
    """Спросить GoPay про один счёт и применить ответ.

    Ставится из открытой вкладки, из вебхука и после отказа в отмене. Повтор
    один: и опрос, и сверка всё равно поставят задачу снова, а длинная цепочка
    повторов при лежащем GoPay только заняла бы очередь.
    """
    from .gopay import service as gopay_service
    from .gopay.client import GoPayUnavailable
    from .models import GoPayInvoice

    invoice = GoPayInvoice.objects.select_related("payment").filter(pk=invoice_id).first()
    if invoice is None:
        return "missing"
    if gopay_service.provider_down(invoice.env):
        return "skipped_down"
    try:
        return gopay_service.refresh_invoice(invoice, source="query")
    except GoPayUnavailable as exc:
        raise self.retry(exc=exc)


@shared_task(name="payments.tasks.cancel_gopay_invoice", bind=True,
             max_retries=5, default_retry_delay=60)
def cancel_gopay_invoice(self, invoice_id: int, reason: str = "") -> str:
    """Отменить у GoPay счёт, который покупатель оставил или который вытеснен новым.

    Не вышло (GoPay недоступен, банк занят) — повторяем; после последнего
    повтора оставленный счёт на каждом проходе отменяет сверка.
    """
    from celery.exceptions import MaxRetriesExceededError

    from .gopay import service as gopay_service
    from .models import GoPayInvoice

    invoice = GoPayInvoice.objects.select_related("payment").filter(pk=invoice_id).first()
    if invoice is None:
        return "missing"
    if gopay_service.provider_down(invoice.env):
        result = "retry"            # GoPay лежит: не ждём таймаут, попробуем позже
    else:
        result = gopay_service.cancel_invoice(invoice, reason=str(reason or ""))
    if result in ("retry", "busy"):
        try:
            raise self.retry()
        except MaxRetriesExceededError:
            # Не ошибка задачи: счёт остаётся оставленным, его добьёт сверка.
            return result
    return result


@shared_task(name="payments.tasks.reconcile_gopay_invoices")
def reconcile_gopay_invoices() -> dict:
    """Сверка счетов единого QR: деньги в банке есть, а вебхук мог не дойти.

    Раз в минуту. Проходит по разделам:
      A  — открытые счета: спросить статус; оставленные и просроченные отменить
           у GoPay; если GoPay не отвечает дольше отсрочки — закрыть своими часами;
      B1 — закрытые только нашими часами (GoPay закрытие не подтвердил): неделю;
      B2 — закрытые с подтверждением GoPay: поздняя оплата, шесть часов;
      C  — список банковских приложений, если свежей копии нет в кэше;
      D  — оплаченные, но не зачисленные: без срока давности.
    """
    token = uuid.uuid4().hex
    if not cache.add(_GOPAY_LOCK, token, _GOPAY_LOCK_TTL):
        return {"status": "busy"}
    try:
        return _reconcile_gopay(_clock() + _GOPAY_BUDGET_SECONDS)
    finally:
        try:
            # Замок снимает только его владелец: проход, переживший свой замок,
            # не должен снять замок следующего прохода.
            if cache.get(_GOPAY_LOCK) == token:
                cache.delete(_GOPAY_LOCK)
        except Exception:  # noqa: BLE001 — замок истечёт сам
            pass


def _reconcile_gopay(deadline: float) -> dict:
    from django.db.models import F, Q

    from .gopay import config as gopay_config
    from .gopay import service as gopay_service
    from .gopay.client import GoPayUnavailable
    from .models import GoPayInvoice

    gp_logger = logging.getLogger("payments.gopay")
    now = timezone.now()
    stats = {"checked": 0, "credited": 0, "closed": 0}
    # Среда, по которой сработал предохранитель, пропускается на весь проход.
    skipped = [env for env in gopay_config.ENVS if gopay_service.provider_down(env)]
    unavailable: dict[str, int] = {}
    state = {"budget": False}

    def out_of_budget() -> bool:
        if _clock() >= deadline:
            state["budget"] = True
        return state["budget"]

    def env_off(env: str) -> bool:
        if env in skipped:
            return True
        if gopay_service.provider_down(env):
            skipped.append(env)
            return True
        return False

    def note_unavailable(env: str) -> None:
        # Второй отказ подряд — GoPay лежит для всех счетов среды, а не для одного.
        unavailable[env] = unavailable.get(env, 0) + 1
        if unavailable[env] >= 2 and env not in skipped:
            skipped.append(env)

    def reload(invoice):
        return GoPayInvoice.objects.select_related("payment").get(pk=invoice.pk)

    def count(result: str) -> None:
        stats["checked"] += 1
        if result == "credited":
            stats["credited"] += 1
        elif result == "closed":
            stats["closed"] += 1

    def refresh(invoice):
        """Итог перепроверки или None, если GoPay не ответил."""
        try:
            result = gopay_service.refresh_invoice(invoice, source="reconcile")
        except GoPayUnavailable:
            note_unavailable(invoice.env)
            return None
        count(result)
        return result

    def cancel(invoice, reason: str) -> str:
        outcome = gopay_service.cancel_invoice(invoice, reason=reason)
        if outcome in ("cancelled", "closed"):
            stats["closed"] += 1
        elif outcome == "committed" and reload(invoice).payment.success:
            stats["credited"] += 1
        return outcome

    def expire_locally(invoice) -> None:
        if gopay_service.mark_expired_locally(invoice):
            stats["closed"] += 1

    def each(invoices, handler) -> None:
        """Счёт за счётом: бюджет и предохранитель — перед каждым; один счёт не роняет проход."""
        for invoice in invoices:
            if out_of_budget():
                return
            if env_off(invoice.env):
                continue
            try:
                handler(invoice)
            except Exception as exc:  # noqa: BLE001
                gp_logger.warning("gopay: сверка счёта %s не удалась: %s",
                                  invoice.pk, type(exc).__name__)

    # Две скорости для закрытых счетов: первые полчаса — раз в две минуты (если
    # оплата и прошла в последнюю секунду, то видно это станет сразу), дальше —
    # раз в полчаса.
    def due_closed():
        return (Q(last_checked_at__isnull=True)
                | Q(finalized_at__gt=now - timedelta(minutes=30),
                    last_checked_at__lt=now - timedelta(minutes=2))
                | Q(last_checked_at__lt=now - timedelta(minutes=30)))

    oldest_checked_first = (F("last_checked_at").asc(nulls_first=True), "id")

    # --- A. Открытые счета ---------------------------------------------------
    def handle_open(invoice) -> None:
        grace_over = timezone.now() >= invoice.expires_at + gopay_service.LOCAL_EXPIRY_GRACE
        if refresh(invoice) is None:
            if grace_over:
                # GoPay не отвечает, а срок давно вышел: закрываем своими часами
                # (без запроса). Пометка local_expiry оставит счёт в сверке B1.
                expire_locally(invoice)
            return
        invoice = reload(invoice)
        if invoice.status not in GoPayInvoice.OPEN_STATES:
            return
        outcome = ""
        if invoice.cancel_requested_at is not None:
            # Оставлен покупателем: отменяем на каждом проходе, каким бы ни был срок.
            outcome = cancel(invoice, str((invoice.flags or {}).get("abandoned") or "abandoned"))
        elif timezone.now() >= invoice.expires_at + gopay_service.CANCEL_AFTER_EXPIRY:
            # Наш срок вышел, а GoPay счёт сам не закрыл (часы, часовой пояс).
            outcome = cancel(invoice, "expired")
        if outcome in ("retry", "busy") and grace_over:
            expire_locally(invoice)

    open_invoices = (
        GoPayInvoice.objects.select_related("payment")
        .filter(status__in=list(GoPayInvoice.OPEN_STATES),
                created_at__gte=now - _GOPAY_OPEN_WINDOW,
                payment__user__isnull=False)
        .filter(Q(last_checked_at__isnull=True)
                | Q(last_checked_at__lt=now - _GOPAY_OPEN_RECHECK))
        .exclude(env__in=list(skipped)))
    # Два среза, чтобы ни очередь старых счетов, ни всплеск новых не оставили
    # друг друга без проверки. A1 — самые свежие: QR оплачивают, если вообще
    # оплачивают, в первые минуты, и без вебхука именно это переключает «оплачено»
    # тому, кто закрыл вкладку. A2 — те, кого дольше всех не спрашивали.
    newest = list(open_invoices.order_by("-created_at", "-id")[:_GOPAY_SLICE])
    longest_unchecked = list(
        open_invoices.exclude(pk__in=[inv.pk for inv in newest])
        .order_by(*oldest_checked_first)[:_GOPAY_SLICE])
    each(newest + longest_unchecked, handle_open)

    # Среда, которую в этом проходе не спрашиваем (лежит или без ключей): её
    # открытые счета всё равно не должны висеть «ждём оплату» вечно. Закрываем
    # своими часами те, у кого вышла отсрочка, — без единого запроса к GoPay.
    silent = [env for env in gopay_config.ENVS
              if env in skipped or not gopay_config.is_configured(env)]
    if silent and not out_of_budget():
        overdue = (GoPayInvoice.objects.select_related("payment")
                   .filter(status__in=list(GoPayInvoice.OPEN_STATES), env__in=silent,
                           expires_at__lt=now - gopay_service.LOCAL_EXPIRY_GRACE)
                   .order_by("expires_at")[:100])
        for invoice in overdue:
            try:
                expire_locally(invoice)
            except Exception as exc:  # noqa: BLE001
                gp_logger.warning("gopay: не закрыть просроченный счёт %s: %s",
                                  invoice.pk, type(exc).__name__)

    # --- B1. Закрыты нашими часами, GoPay не подтвердил -----------------------
    # Неделя, а не шесть часов: такой счёт мог быть оплачен, пока мы не могли
    # спросить (сменили секрет, закрыли доступ по IP, упала сеть), и пока не
    # настроен вебхук, больше его никто не зачислит.
    def handle_unconfirmed(invoice) -> None:
        if refresh(invoice) is None:
            return
        invoice = reload(invoice)
        if (invoice.status == GoPayInvoice.STATUS_EXPIRED
                and (invoice.flags or {}).get("local_expiry")):
            # GoPay всё ещё считает счёт открытым (или не нашёл его): отменяем.
            # Первый же конечный ответ снимет пометку.
            cancel(invoice, "expired")

    if not out_of_budget():
        unconfirmed = list(
            GoPayInvoice.objects.select_related("payment")
            .filter(status=GoPayInvoice.STATUS_EXPIRED, flags__has_key="local_expiry",
                    payment__success=False,
                    finalized_at__gte=now - gopay_service.UNCONFIRMED_SWEEP_WINDOW)
            .filter(due_closed())
            .exclude(env__in=list(skipped))
            .order_by(*oldest_checked_first)[:_GOPAY_SWEEP])
        each(unconfirmed, handle_unconfirmed)

    # --- B2. Закрыты с подтверждением GoPay: поздняя оплата -------------------
    def settled_by_hand(invoice) -> bool:
        # В Python, а не фильтром по JSON: таких строк единицы, а исключение по
        # ключу JSON ведёт себя по-разному на SQLite (тесты) и PostgreSQL (бой).
        response = invoice.payment.response or {}
        return bool(response.get("admin_refund") or response.get("token_purchase_clawed_back"))

    def take(queryset, wanted, limit: int) -> list:
        picked = []
        for invoice in queryset[:limit * 10]:
            if wanted(invoice):
                picked.append(invoice)
                if len(picked) >= limit:
                    break
        return picked

    if not out_of_budget():
        late = take(
            GoPayInvoice.objects.select_related("payment")
            .filter(status__in=list(GoPayInvoice.CLOSED_UNPAID), payment__success=False,
                    finalized_at__gte=now - gopay_service.LATE_SWEEP_WINDOW)
            .filter(due_closed())
            .exclude(flags__has_key="local_expiry")
            .exclude(env__in=list(skipped))
            .order_by(*oldest_checked_first),
            lambda invoice: not settled_by_hand(invoice), _GOPAY_SWEEP)
        each(late, lambda invoice: refresh(invoice))

    # --- C. Список банковских приложений --------------------------------------
    # В тестовой среде кнопок банков нет вовсе. Обновляем, когда нет СВЕЖЕЙ копии
    # (шесть часов), а не когда список пуст: «последний удачный» список живёт
    # неделю и нужен как запас на случай сбоя, а не как повод не спрашивать —
    # иначе новый банк или снятая отметка iPhone доходили бы до покупателя через
    # неделю, а запас кончался бы вместе со свежей копией. Не чаще раза в десять
    # минут: метод может не отвечать, и спрашивать каждую минуту незачем.
    if not out_of_budget():
        try:
            env = gopay_config.env()
            if (env != gopay_config.ENV_TEST and not env_off(env)
                    and gopay_config.is_configured(env)
                    and not gopay_service.apps_fresh(env)
                    and cache.add(f"gopay:apps:recon:{env}", 1, _GOPAY_APPS_RETRY)):
                gopay_service.refresh_apps_cache(env)
        except Exception as exc:  # noqa: BLE001 — кнопки банков не важнее сверки
            gp_logger.warning("gopay: список банков не обновлён: %s", type(exc).__name__)

    # --- D. Оплачено, но не зачислено -----------------------------------------
    # Без срока давности: упавшее зачисление повторяем, пока не получится или
    # пока человек не отметит возврат. Счета на разборе (needs_review) не
    # трогаем — их судьбу решает администратор.
    def retryable(invoice) -> bool:
        response = invoice.payment.response or {}
        return not ((invoice.flags or {}).get("needs_review")
                    or response.get("admin_refund")
                    or response.get("token_purchase_clawed_back")
                    or response.get("token_purchase_applied"))

    if not out_of_budget():
        unsettled = take(
            GoPayInvoice.objects.select_related("payment")
            .filter(status=GoPayInvoice.STATUS_COMMITTED, payment__success=False,
                    payment__user__isnull=False,
                    # Отбор — в самом запросе: повторять здесь можно только упавшее
                    # начисление. Возвращённые и ушедшие на разбор счета никто не
                    # перепроверяет, их last_checked_at не меняется — они вечно
                    # стояли бы первыми, и когда их наберётся на всё окно выборки,
                    # до упавшего начисления очередь не дошла бы уже никогда.
                    payment__error__startswith="token_purchase_apply_failed")
            .filter(Q(last_checked_at__isnull=True)
                    | Q(finalized_at__gte=now - timedelta(hours=48),
                        last_checked_at__lt=now - timedelta(minutes=5))
                    | Q(last_checked_at__lt=now - timedelta(hours=6)))
            .exclude(env__in=list(skipped))
            .order_by(*oldest_checked_first),
            retryable, _GOPAY_SWEEP)
        each(unsettled, lambda invoice: refresh(invoice))

    result = {"status": "budget" if state["budget"] else "ok", **stats,
              "skipped_env": list(skipped)}
    if stats["credited"] or stats["closed"] or skipped or state["budget"]:
        gp_logger.info("gopay reconcile: %s", result)
    return result


@shared_task(name="payments.tasks.reconcile_star_transactions")
def reconcile_star_transactions() -> dict:
    """Сверка Telegram Stars: пропущенные апдейты и возвраты. См. botapi/stars.py."""
    from botapi.stars import reconcile

    try:
        result = reconcile()
    except Exception:  # noqa: BLE001
        logger.exception("stars reconcile failed")
        return {"status": "error"}
    if result.get("credited") or result.get("refunded"):
        logger.info("stars reconcile: %s", result)
    return result
