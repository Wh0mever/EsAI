"""Воронка оплаты: приём клиентских шагов и отчёт для панели.

Задача клиента: понять, на каком шаге отваливаются те, кто не заплатил. По
таблице платежей видно только конец пути, и там 12 оплат из 95 попыток —
но неясно, отказал банк или человек просто не вернулся со страницы оплаты.

Разделение здесь и делается: платёж без единого ответа от платёжной системы —
это «ушёл и не вернулся», а не «отказано». Смешивать их нельзя, лечатся они
по-разному: первое — удобством оплаты, второе — способом платежа.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import FunnelEvent, Payment


class _FunnelThrottle(AnonRateThrottle):
    # Шаги шлются без токена — значит, считаются по IP, а первый экран
    # видеостудии шлёт шаг на каждый клик. В общем анонимном лимите (30 в
    # минуту) их делили бы со входом по почте и списком пакетов: несколько
    # гостей за одним адресом выбрали бы его раньше, чем нажмут «Войти».
    scope = "funnel_event"
    rate = "120/min"


class FunnelEventView(APIView):
    """POST — записать шаг воронки. Открыт всем: до оплаты человек ещё гость.

    Имена шагов принимаются только из списка: открытый на запись эндпоинт без
    белого списка — это приглашение засорить таблицу чем угодно.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [_FunnelThrottle]

    def post(self, request):
        name = str((request.data or {}).get("name") or "").strip()
        if name not in FunnelEvent.NAMES:
            return Response({"detail": "unknown step"}, status=status.HTTP_400_BAD_REQUEST)

        device_key = (request.headers.get("X-Device-Key") or "").strip()[:64]
        if not device_key:
            device_key = str((request.data or {}).get("device_key") or "").strip()[:64]

        meta = (request.data or {}).get("meta")
        FunnelEvent.objects.create(
            name=name,
            user=request.user if request.user.is_authenticated else None,
            device_key=device_key,
            meta=meta if isinstance(meta, dict) else {},
        )
        return Response({"ok": True}, status=status.HTTP_201_CREATED)


def _payment_stage(p: Payment) -> str:
    """На каком шаге остановился платёж.

    Ответы платёжной системы лежат в response["callbacks"] (браузерный возврат
    и постбэк). Их отсутствие означает ровно одно: человека увели на оплату, и
    оттуда он не вернулся.
    """
    if p.success:
        return "paid"

    # Крипта живёт по своим правилам: там нет «ответа платёжной системы», зато
    # есть счёт, который час ждёт перевода, и частичная оплата. Считать всё это
    # «ушёл и не вернулся» — значит смотреть на выдуманную картину.
    invoice = getattr(p, "crypto_invoice", None)
    if invoice is not None:
        if invoice.credited_tokens > 0:
            return "partial"
        if invoice.status in ("failed", "refunded"):
            return "declined"
        if invoice.is_open and invoice.expires_at and invoice.expires_at > timezone.now():
            return "pending"
        return "left"

    # Единый QR (GoPay): ссылки на чужую страницу нет, а в callbacks лежит
    # история статусов — по общему правилу ниже истёкший QR считался бы
    # «оплата отклонена», а открытый — «ушёл и не вернулся».
    qr = _gopay_invoice(p)
    if qr is not None:
        if qr.status == "failed":
            return "declined"
        abandoned = qr.cancel_requested_at is not None
        if qr.is_open and not abandoned and qr.expires_at > timezone.now():
            return "pending"
        if qr.status == "cancelled" or abandoned:
            # Человек сам ушёл с экрана QR («оплатить другим способом»).
            return "canceled"
        return "left"

    callbacks = (p.response or {}).get("callbacks") or []
    if p.error and "canceled" in str(p.error):
        return "canceled"
    if callbacks:
        return "declined"
    if (p.response or {}).get("yookassa_create") or (p.response or {}).get("init"):
        return "left"
    return "left"


def _gopay_invoice(p: Payment):
    """Счёт единого QR этого платежа или None (обратная связь один-к-одному не бросает)."""
    try:
        return p.gopay_invoice
    except Exception:  # noqa: BLE001 — счёта нет
        return None


def _method_of(p: Payment) -> tuple[str, str, str]:
    """(провайдер, способ, подпись) — строка разбивки «чем платили»."""
    provider = str(p.provider or "")
    method = str((p.request or {}).get("pay_method") or "")
    if provider == "gopay":
        return provider, method, "Единый QR (GoPay)"
    if provider == "freedompay":
        if method == "card":
            return provider, method, "Карта (FreedomPay)"
        if not method:
            return provider, method, "FreedomPay без выбора способа"
        return provider, method, f"{method.upper()} (FreedomPay)"
    if provider == "yookassa":
        return provider, "", "ЮKassa"
    if provider.startswith("crypto_"):
        return provider, "", "Крипта"
    if provider == "telegram_stars":
        return provider, "", "Telegram Stars"
    return provider, method, provider or "—"


def _qr_report(payments, events) -> dict:
    """Единый QR: что произошло на сервере и что человек видел на экране.

    created / paid / expired считаются по строкам платежей — эти числа сходятся
    с разбивкой by_method на той же странице. Остальное — события клиента
    (разные устройства). paid_seen — «увидел наш экран „Оплачено“»: с телефона
    многие платят в приложении банка и во вкладку не возвращаются, поэтому оно
    по замыслу меньше paid и «оплатами» не называется.
    """
    created = paid = expired = 0
    for p in payments:
        if str(p.provider or "") != "gopay":
            continue
        qr = _gopay_invoice(p)
        if qr is None:
            continue
        created += 1
        paid += 1 if p.success else 0
        expired += 1 if qr.status == "expired" else 0
    return {
        "created": created,
        "shown": events.get("kgs_qr_shown", 0),
        "app_open": events.get("kgs_qr_app_open", 0),
        "saved": events.get("kgs_qr_save", 0),
        "other_method": events.get("kgs_qr_other_method", 0),
        "paid": paid,
        "expired": expired,
        "paid_seen": events.get("kgs_qr_paid", 0),
    }


def _registered_after(ev, view_name: str, since) -> int:
    """Сколько устройств открыли раздел гостем, а потом появились уже с пользователем."""
    guest_devices = set(
        ev.filter(name=view_name, user__isnull=True).exclude(device_key="")
        .values_list("device_key", flat=True))
    if not guest_devices:
        return 0
    return (FunnelEvent.objects.filter(created_at__gte=since, device_key__in=guest_devices,
                                       user__isnull=False)
            .values("device_key").distinct().count())


def _return_to(p: Payment) -> str:
    return str((p.request or {}).get("return_to") or "")


def _is_vstudio_return(path: str) -> bool:
    # «/video-studio» тоже содержит «studio» — без этой проверки оплаты из
    # видеостудии засчитывались бы мультстудии.
    return path.startswith("/video-studio")


def _shares(rows) -> list:
    top = rows[0][2]
    return [{"key": k, "label": label, "count": n,
             "share": round(n * 100 / top) if top else None} for k, label, n in rows]


def studio_report(since) -> list:
    """Воронка студии: где гость теряется между первым экраном и оплатой.

    Шаги не строго последовательны (примерку можно пропустить), поэтому доля
    считается от открывших студию, а не от предыдущего шага.
    """
    from cartoon.models import CartoonGuestTryOn, CartoonProject

    ev = FunnelEvent.objects.filter(created_at__gte=since, name__startswith="studio_")
    counts = dict(ev.values_list("name").annotate(n=Count("device_key", distinct=True)))

    # «Вошёл после студии»: устройство открывало студию гостем, а потом
    # появилось в событиях уже с пользователем.
    registered = _registered_after(ev, "studio_view", since)

    paid = 0
    for p in Payment.objects.filter(created_at__gte=since, success=True,
                                    request__token_purchase__isnull=False).exclude(is_test=True):
        path = _return_to(p)
        if "studio" in path and not _is_vstudio_return(path):
            paid += 1

    rows = [
        ("studio_view", "Открыли студию", counts.get("studio_view", 0)),
        ("studio_hero_pick", "Выбрали героя", counts.get("studio_hero_pick", 0)),
        ("studio_scene_add", "Добавили сцену в ленту", counts.get("studio_scene_add", 0)),
        ("studio_tryon", "Нажали «Примерить»", counts.get("studio_tryon", 0)),
        ("guest_free_tryon", "Получили бесплатную примерку",
         CartoonGuestTryOn.objects.filter(created_at__gte=since).count()),
        ("studio_auth_prompt", "Увидели окно входа", counts.get("studio_auth_prompt", 0)),
        ("registered", "Вошли после студии", registered),
        ("draft_import", "Лента перенесена после входа",
         CartoonProject.objects.filter(created_at__gte=since).exclude(import_key="").count()),
        ("studio_render_click", "Нажали «Снять сцену»", counts.get("studio_render_click", 0)),
        ("studio_paywall", "Не хватило кредитов", counts.get("studio_paywall", 0)),
        ("paid", "Оплатили из студии", paid),
    ]
    return _shares(rows)


def vstudio_report(since) -> list:
    """Воронка видеостудии: от первого экрана до запуска и оплаты.

    Как и у мультстудии, доля считается от открывших видеостудию: шаги можно
    пропускать (без фото, без @). Исходы генераций (выдано, ошибка, потеряно)
    здесь не считаются — их источник правды таблица дублей и отчёт vstudio.
    """
    ev = FunnelEvent.objects.filter(created_at__gte=since, name__startswith="vstudio_")
    counts = dict(ev.values_list("name").annotate(n=Count("device_key", distinct=True)))

    def devices(qs) -> int:
        return qs.values("device_key").distinct().count()

    # Загрузка шлёт {ok, code}: отказ (HEIC не прочитался, слишком большое,
    # не картинка) — отдельная строка, иначе он прячется среди удачных.
    uploads = ev.filter(name="vstudio_upload")
    upload_ok = devices(uploads.filter(meta__ok=True))
    upload_failed = devices(uploads.filter(meta__ok=False))

    paid = sum(1 for p in Payment.objects.filter(created_at__gte=since, success=True,
                                                 request__token_purchase__isnull=False)
               .exclude(is_test=True)
               if _is_vstudio_return(_return_to(p)))

    rows = [
        ("vstudio_view", "Открыли видеостудию", counts.get("vstudio_view", 0)),
        ("vstudio_home_pick", "Нажали на первом экране", counts.get("vstudio_home_pick", 0)),
        ("vstudio_auth_prompt", "Увидели окно входа", counts.get("vstudio_auth_prompt", 0)),
        ("registered", "Вошли после видеостудии", _registered_after(ev, "vstudio_view", since)),
        ("vstudio_upload", "Загрузили фото", upload_ok),
        ("vstudio_upload_failed", "Фото не приняли", upload_failed),
        ("vstudio_mention", "Упомянули материал через @", counts.get("vstudio_mention", 0)),
        ("vstudio_imagegen", "Создали картинку для @", counts.get("vstudio_imagegen", 0)),
        ("vstudio_blocked", "Запуск остановила проверка", counts.get("vstudio_blocked", 0)),
        ("vstudio_run_click", "Нажали «Создать»", counts.get("vstudio_run_click", 0)),
        ("vstudio_paywall", "Не хватило кредитов", counts.get("vstudio_paywall", 0)),
        ("paid", "Оплатили из видеостудии", paid),
        ("vstudio_condense", "Нажали «Сжать с ИИ»", counts.get("vstudio_condense", 0)),
        ("vstudio_share", "Поделились результатом", counts.get("vstudio_share", 0)),
    ]
    return _shares(rows)


def funnel_report(days: int = 30) -> dict:
    """Сводка воронки за период."""
    since = timezone.now() - timedelta(days=days)

    events = dict(
        FunnelEvent.objects.filter(created_at__gte=since)
        .values_list("name")
        .annotate(n=Count("device_key", distinct=True))
    )

    payments = list(
        Payment.objects.filter(created_at__gte=since,
                               request__token_purchase__isnull=False)
        # Тестовые платежи (единый QR в тестовой среде) — проверка цепочки
        # сотрудником, а не покупка: в воронке им не место.
        .exclude(is_test=True)
        .select_related("crypto_invoice", "gopay_invoice")
    )
    stages = {"paid": 0, "declined": 0, "canceled": 0, "left": 0,
              "partial": 0, "pending": 0}
    for p in payments:
        stages[_payment_stage(p)] += 1

    started = len(payments)
    # Частично оплативший и ждущий перевода — это тоже «вернулся»: он до формы
    # дошёл и деньги отправил или отправляет.
    returned = (stages["paid"] + stages["declined"] + stages["canceled"]
                + stages["partial"] + stages["pending"])

    steps = [
        {"key": "pricing_view", "label": "Открыли тарифы",
         "count": events.get("pricing_view", 0)},
        {"key": "topup_click", "label": "Нажали «Пополнить»",
         "count": events.get("topup_click", 0)},
        {"key": "payment_started", "label": "Ушли на страницу оплаты", "count": started},
        {"key": "returned", "label": "Вернулись с оплаты", "count": returned},
        {"key": "paid", "label": "Оплатили", "count": stages["paid"]},
    ]

    # Где именно теряем. Считаем от шага к шагу, а не от начала: иначе провал
    # в середине размывается по всей воронке и его не видно.
    for i, s in enumerate(steps):
        prev = steps[i - 1]["count"] if i else 0
        s["lost"] = max(0, prev - s["count"]) if i else 0
        s["rate"] = round(s["count"] * 100 / prev) if i and prev else None

    reasons = [
        {"key": "left", "label": "Ушли на оплату и не вернулись",
         "count": stages["left"],
         "hint": "Платёжная система не прислала ни одного ответа — человек закрыл её страницу."},
        {"key": "declined", "label": "Оплата отклонена",
         "count": stages["declined"],
         "hint": "Ответ от платёжной системы пришёл, но неуспешный: карта, лимит, 3-D Secure."},
        {"key": "canceled", "label": "Отменили в платёжной системе",
         "count": stages["canceled"],
         "hint": "Человек дошёл до формы и нажал «отмена»."},
        {"key": "partial", "label": "Оплатили частично (крипта)",
         "count": stages["partial"],
         "hint": "Перевели меньше суммы — обычно не учли комиссию сети. "
                 "Кредиты начислены пропорционально, счёт ждёт доплаты."},
        {"key": "pending", "label": "Ждём оплату (крипта, QR)",
         "count": stages["pending"],
         "hint": "Счёт выставлен и ещё действует — человек в этот момент "
                 "может стоять в своём кошельке или в приложении банка."},
    ]

    by_currency = list(
        Payment.objects.filter(created_at__gte=since,
                               request__token_purchase__isnull=False)
        .exclude(is_test=True)
        .values("currency")
        .annotate(всего=Count("id"), оплачено=Count("id", filter=Q(success=True)))
        .order_by("-всего")
    )

    packages = {}
    for p in payments:
        pkg = ((p.request or {}).get("token_purchase") or {}).get("package_id")
        if not pkg:
            continue
        row = packages.setdefault(pkg, {"package_id": pkg, "всего": 0, "оплачено": 0})
        row["всего"] += 1
        row["оплачено"] += 1 if p.success else 0

    # Чем платили: единый QR и карта — обе в сомах, по валюте их не различить.
    methods = {}
    for p in payments:
        provider, method, label = _method_of(p)
        key = f"{provider}:{method}"
        row = methods.setdefault(key, {"key": key, "provider": provider, "method": method,
                                       "label": label, "всего": 0, "оплачено": 0})
        row["всего"] += 1
        row["оплачено"] += 1 if p.success else 0

    return {
        "days": days,
        "studio": studio_report(since),
        "vstudio": vstudio_report(since),
        "steps": steps,
        "reasons": reasons,
        "by_currency": by_currency,
        "by_package": sorted(packages.values(), key=lambda r: -r["всего"]),
        "by_method": sorted(methods.values(), key=lambda r: (-r["всего"], r["key"])),
        "qr": _qr_report(payments, events),
        "conversion": round(stages["paid"] * 100 / started, 1) if started else None,
    }
