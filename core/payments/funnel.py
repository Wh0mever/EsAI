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


class FunnelEventView(APIView):
    """POST — записать шаг воронки. Открыт всем: до оплаты человек ещё гость.

    Имена шагов принимаются только из списка: открытый на запись эндпоинт без
    белого списка — это приглашение засорить таблицу чем угодно.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

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
    callbacks = (p.response or {}).get("callbacks") or []
    if p.error and "canceled" in str(p.error):
        return "canceled"
    if callbacks:
        return "declined"
    if (p.response or {}).get("yookassa_create") or (p.response or {}).get("init"):
        return "left"
    return "left"


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
    )
    stages = {"paid": 0, "declined": 0, "canceled": 0, "left": 0}
    for p in payments:
        stages[_payment_stage(p)] += 1

    started = len(payments)
    returned = stages["paid"] + stages["declined"] + stages["canceled"]

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
    ]

    by_currency = list(
        Payment.objects.filter(created_at__gte=since,
                               request__token_purchase__isnull=False)
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

    return {
        "days": days,
        "steps": steps,
        "reasons": reasons,
        "by_currency": by_currency,
        "by_package": sorted(packages.values(), key=lambda r: -r["всего"]),
        "conversion": round(stages["paid"] * 100 / started, 1) if started else None,
    }
