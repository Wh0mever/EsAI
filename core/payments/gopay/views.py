"""Эндпоинты единого QR (GoPay): состояние счёта, отказ от него и вебхук.

Сами эти представления денег не начисляют и статусов не решают: всё, что
меняет счёт, живёт в service.py. Здесь — кто вправе спросить, когда пора
перепроверить и что ответить.

* Состояние счёта вкладка опрашивает каждые несколько секунд. К GoPay из
  этого запроса не ходим никогда: ставим задачу на перепроверку (не чаще
  раза в несколько секунд на счёт) и отвечаем тем, что есть.
* Отказ от QR («оплатить другим способом») — единственное место, где запрос
  покупателя сам зовёт GoPay: человек ждёт ответа, можно ли платить иначе.
* Вебхук — повод спросить, а не основание платить. Подписанное «оплачено»
  запускает наш собственный подписанный запрос статуса, и зачисляется его
  ответ. Секрет вебхуков лежит в базе открытым текстом, а всё остальное для
  подделки покупатель знает и так.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from ..models import GoPayInvoice, GoPayWebhookEvent
# Циклов нет: payments.views не знает ни про этот модуль, ни про plans.views.
from ..views import _IgnoreAcceptNegotiation
from . import service as gopay_service
from .client import GoPayError, PaymentState

logger = logging.getLogger("payments.gopay")

# Больше этого тело вебхука быть не может: всё, что крупнее, даже не разбираем.
MAX_BODY = 64 * 1024

# Как часто открытая вкладка вправе вызвать перепроверку у GoPay, секунды.
POLL_OPEN_SECONDS = 5          # счёт ждёт оплату
POLL_CLOSED_SECONDS = 30       # закрыт без оплаты: окно поздней оплаты
POLL_PROCESSING_SECONDS = 15   # деньги пришли, зачисление впереди

# Событие вебхука -> статус, который оно обязано нести в теле.
_EVENT_STATUS = {
    "payment.committed": "committed",
    "payment.failed": "failed",
    "payment.expired": "expired",
    "payment.cancelled": "cancelled",
}
# Больше не влезет в поле суммы журнала — и к нашим заказам отношения не имеет.
_JOURNAL_AMOUNT_MAX = Decimal("9999999999.99")


# ------------------------------------------------------------ очередь ---

def _enqueue_check(invoice, countdown: int = 0) -> None:
    """Поставить перепроверку счёта у GoPay. Очередь недоступна — догонит сверка."""
    try:
        from ..tasks import check_gopay_invoice

        check_gopay_invoice.apply_async((invoice.id,), countdown=int(countdown or 0))
    except Exception:  # noqa: BLE001 — очередь не важнее ответа
        logger.warning("gopay: не удалось поставить перепроверку счёта %s", invoice.id)


def _enqueue_cancel(invoice_id: int, reason: str = "") -> None:
    """Поставить отмену оставленного счёта у GoPay. Не вышло — отменит сверка."""
    try:
        from ..tasks import cancel_gopay_invoice

        cancel_gopay_invoice.delay(invoice_id, reason)
    except Exception:  # noqa: BLE001
        logger.warning("gopay: не удалось поставить отмену счёта %s", invoice_id)


# -------------------------------------------------------------- поиск ---

def _owned_invoice(request, order_id: str):
    return (GoPayInvoice.objects.select_related("payment")
            .filter(payment__order_id=order_id, payment__user=request.user)
            .first())


def _reload(invoice):
    return GoPayInvoice.objects.select_related("payment").get(pk=invoice.pk)


def _find_invoice(state: PaymentState):
    """Наш счёт по событию GoPay: по номеру заказа, иначе по номеру платежа."""
    invoices = GoPayInvoice.objects.select_related("payment")
    if state.order_id:
        return invoices.filter(payment__order_id=state.order_id,
                               payment__provider="gopay").first()
    if state.payment_id:
        return invoices.filter(provider_payment_id=state.payment_id).first()
    return None


# ------------------------------------------------- состояние и отмена ---

class GoPayInvoiceStatusView(APIView):
    """GET /api/plans/purchase/qr/<order_id>/ — что со счётом прямо сейчас.

    Этим же адресом вкладка узнаёт, что оплата прошла, пока человек был в
    приложении банка: страница могла перезагрузиться, а счёт — уже оплачен.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "gopay_status"

    def get(self, request, order_id: str):
        invoice = _owned_invoice(request, order_id)
        if invoice is None:
            # Именно 404, а не 403: по ответу нельзя перебрать чужие заказы.
            return Response({"detail": "not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

        self._maybe_refresh(invoice)
        return Response(gopay_service.invoice_json(_reload(invoice)))

    @staticmethod
    def _maybe_refresh(invoice) -> None:
        """Поставить перепроверку, если наши данные подустарели. GoPay отсюда не зовём."""
        if invoice.payment.success:
            return
        if gopay_service.provider_down(invoice.env):
            # GoPay лежит: иначе каждая открытая вкладка клала бы в общую
            # очередь по задаче раз в пять секунд.
            return
        now = timezone.now()
        if invoice.status in GoPayInvoice.OPEN_STATES:
            window = POLL_OPEN_SECONDS
        elif (invoice.status in GoPayInvoice.CLOSED_UNPAID
              and now < invoice.expires_at + gopay_service.LOCAL_EXPIRY_GRACE):
            # Банк мог провести оплату в последнюю секунду — какое-то время
            # после закрытия ещё спрашиваем, но реже.
            window = POLL_CLOSED_SECONDS
        elif gopay_service.ui_state(invoice) == "processing":
            window = POLL_PROCESSING_SECONDS
        else:
            return
        stale = (invoice.last_checked_at is None
                 or (now - invoice.last_checked_at).total_seconds() > window)
        if not stale:
            return
        if not cache.add(f"gopay:poll:{invoice.id}", "1", window):
            return
        _enqueue_check(invoice)


class GoPayInvoiceCancelView(APIView):
    """POST /api/plans/purchase/qr/<order_id>/cancel/ — «оплатить другим способом».

    Клиент смотрит на одно поле — released:
      true  — QR покупателя больше не держит (закрыт у GoPay или оставлен):
              можно вернуться к выбору способа, скидка свободна;
      false — остаёмся на экране QR: он оплачен (committed) или банк прямо
              сейчас проводит по нему оплату (busy).
    Тело необязательно: {"abandon": true} — «всё равно уйти», повторный запрос
    после busy.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "gopay_cancel"

    def post(self, request, order_id: str):
        invoice = _owned_invoice(request, order_id)
        if invoice is None:
            return Response({"detail": "not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

        data = request.data if isinstance(request.data, dict) else {}
        abandon = data.get("abandon") is True

        if (gopay_service.provider_down(invoice.env) and not invoice.payment.success
                and invoice.status in GoPayInvoice.OPEN_STATES):
            # GoPay только что несколько раз не ответил: тот же исход, что у
            # несостоявшейся отмены, но без ожидания ещё одного таймаута.
            result = "retry"
        else:
            # Запрос к GoPay — до любых блокировок строк.
            result = gopay_service.cancel_invoice(invoice, reason="user")

        released = result in ("cancelled", "closed", "not_open")
        if result == "retry" or (result == "busy" and abandon):
            # retry: GoPay не смог отменить, но на оплату ничто не указывает —
            # покупателя не держим у QR четверть часа из-за чужого сбоя.
            # busy + abandon: человек подождал и всё равно уходит. Счёт
            # остаётся в сверке; поздняя оплата по нему зачислится.
            if gopay_service.mark_abandoned(invoice, "user"):
                transaction.on_commit(
                    lambda i=invoice.id: _enqueue_cancel(i, "user"))
            released = True
        elif result == "busy":
            # Банк, возможно, как раз подтверждает оплату: отпустить сейчас —
            # значит отправить только что заплатившего платить второй раз, а
            # возврата через API у GoPay нет. Скоро посмотрим ещё раз.
            _enqueue_check(invoice, countdown=10)

        # Замок «идёт создание» больше не нужен: следующий клик по этому пакету
        # должен получить новый QR, а не «слишком часто».
        package_id = (((invoice.payment.request or {}).get("token_purchase") or {})
                      .get("package_id"))
        try:
            cache.delete(f"gopay:create:{request.user.id}:{package_id}")
        except Exception:  # noqa: BLE001 — замок и сам истечёт
            pass

        return Response({"result": result, "released": released,
                         "invoice": gopay_service.invoice_json(_reload(invoice))})


# -------------------------------------------------------------- вебхук ---

class GoPayWebhookView(APIView):
    """POST /api/payments/gopay/webhook/ — событие GoPay.

    Подпись считается по телу РОВНО как оно пришло, поэтому request.data здесь
    не читается никогда: после него исходных байт уже не получить.

    Ответы:
      400 — подпись не сошлась (или её нет): ничего не пишем, GoPay не зовём;
      200 — подписанное событие принято, в том числе про чужой заказ;
      503 — подписанное «оплачено», а подтвердить его своим запросом к GoPay не
            удалось: в этом запросе не зачисляем ничего и просим доставить
            событие ещё раз. Параллельно счёт догоняют перепроверка и сверка.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "gopay_webhook"
    # GoPay вправе прислать любой Accept — 406 до обработчика нам не нужен.
    content_negotiation_class = _IgnoreAcceptNegotiation

    def post(self, request, *args, **kwargs):
        raw = request.body or b""        # первым делом: байты ровно как пришли
        if len(raw) > MAX_BODY:
            return Response({"status": "too_large"}, status=drf_status.HTTP_400_BAD_REQUEST)

        nonce = str(request.headers.get("GoPay-Nonce") or "").strip()
        signature = str(request.headers.get("GoPay-Signature") or "").strip()
        envs = gopay_service.verify_webhook(nonce, signature, raw)
        if not envs:
            # Ни тела, ни заголовков в журнале; ничего не сохраняем.
            logger.warning("gopay webhook: подпись не принята")
            return Response({"status": "invalid_signature"},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._ok("ignored")
        if not isinstance(body, dict):
            return self._ok("ignored")

        raw_event = body.get("event")
        event = raw_event[:48] if isinstance(raw_event, str) else ""
        data = body.get("data") if isinstance(body.get("data"), dict) else None

        if not event:
            # Старый «плоский» callback_url. Из такого тела не применяем ничего:
            # оно лишь повод спросить GoPay своим подписанным запросом.
            invoice = _find_invoice(PaymentState.from_payload(body))
            if invoice is not None:
                _enqueue_check(invoice)
            return self._ok()
        if data is None or not (event.startswith("payment.") or event == "receipt.sent"):
            # test.ping, subscription.*, invoice.*, static_qr.* — принять и забыть.
            return self._ok()

        state = PaymentState.from_payload(data)
        envelope_created_at = body.get("created_at")
        key = gopay_service.event_key(
            event, state, envelope_created_at if isinstance(envelope_created_at, str) else "")
        if GoPayWebhookEvent.objects.filter(event_key=key, processed=True).exists():
            # До любого обращения к GoPay: повтор события не стоит ничего.
            return self._ok("duplicate")

        invoice = _find_invoice(state)
        expected = _EVENT_STATUS.get(event)

        # --- Подтверждающий запрос: ДО того, как записана или заблокирована
        #     хоть одна строка. Спрашиваем по НАШЕМУ сохранённому номеру платежа
        #     и ключами среды счёта.
        confirmed, note = None, ""
        if (invoice is not None and expected == "committed" and state.status == "committed"
                and invoice.env in envs):
            if invoice.payment.success:
                note = "already"            # подтверждать нечего, GoPay не зовём
            else:
                try:
                    confirmed = gopay_service.fetch_state(invoice)
                except GoPayError as exc:
                    note = f"query_failed:{exc.code}"

        try:
            # Точка сохранения обязательна: запрос обёрнут в транзакцию
            # (ATOMIC_REQUESTS), и без неё повтор события сломал бы её всю.
            with transaction.atomic():
                row = GoPayWebhookEvent.objects.create(
                    event_key=key, event=event,
                    provider_payment_id=state.payment_id, order_id=state.order_id,
                    status=state.provider_status,
                    amount=(state.amount if state.amount is not None
                            and state.amount <= _JOURNAL_AMOUNT_MAX else None),
                    testing_mode=bool(state.testing_mode),
                    payload=gopay_service.sanitize_event(body))
        except IntegrityError:
            row = GoPayWebhookEvent.objects.filter(event_key=key).first()
            if row is None or row.processed:
                return self._ok("duplicate")

        if invoice is None:
            # Другая интеграция той же точки или быстрый платёж из кабинета.
            # processed остаётся False: если заказ появится позже, повторная
            # доставка будет обработана.
            row.result = "unknown_order"
            row.save(update_fields=["result"])
            return self._ok()

        processed = True
        retry_later = False
        if event == "receipt.sent":
            url = data.get("receipt_url")
            if isinstance(url, str) and url.startswith("https://") and len(url) <= 500:
                GoPayInvoice.objects.filter(pk=invoice.pk, receipt_url="").update(receipt_url=url)
                result = "receipt_saved"
            else:
                result = "ignored_event"
        elif expected is None:
            result = "ignored_event"
        elif state.status != expected:
            # Событие говорит одно, статус в теле — другое: не верим ни тому, ни
            # другому, спрашиваем сами.
            result = "event_status_mismatch"
            _enqueue_check(invoice)
        elif invoice.env not in envs:
            # Подписано секретом другой среды: из тела не берём ничего.
            result = "secret_env_mismatch"
            _enqueue_check(invoice)
        elif expected == "committed":
            if note == "already":
                result = "already"
            elif confirmed is None:
                # Спросить GoPay не удалось. Событие остаётся необработанным;
                # отвечаем 503, чтобы GoPay доставил его снова, а счёт тем
                # временем догоняют перепроверка и сверка.
                result = note or "query_failed"
                processed = False
                retry_later = True
                _enqueue_check(invoice, countdown=15)
            else:
                result, processed = self._apply(invoice, confirmed, state)
                if result == "pending":
                    # Событие пришло раньше, чем его увидел запрос статуса самого
                    # GoPay, — или событие подделано. В обоих случаях не
                    # зачисляем и смотрим ещё раз чуть позже.
                    result, processed = "query_pending", False
                    _enqueue_check(invoice, countdown=10)
        else:
            # failed / expired / cancelled применяем из подписанного тела:
            # зачислить такие события не могут, только закрыть неоплаченный счёт.
            result, processed = self._apply(invoice, state, state)

        row.processed = processed
        row.result = str(result)[:64]
        row.save(update_fields=["processed", "result"])
        if retry_later:
            return Response({"status": "retry_later"},
                            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE)
        return self._ok()

    @staticmethod
    def _ok(status: str = "ok") -> Response:
        return Response({"status": status}, status=drf_status.HTTP_200_OK)

    @staticmethod
    def _apply(invoice, state: PaymentState, event_state: PaymentState) -> tuple[str, bool]:
        """Применить состояние; сбой — не ошибка запроса, а повод перепроверить."""
        try:
            with transaction.atomic():
                return gopay_service.apply_state(invoice, state, source="webhook"), True
        except Exception:  # noqa: BLE001 — журнал и ответ важнее причины
            logger.exception("gopay webhook: не удалось применить событие order=%s",
                             event_state.order_id)
            _enqueue_check(invoice)
            return "error", False
