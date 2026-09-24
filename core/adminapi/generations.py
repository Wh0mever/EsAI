"""Журнал генераций в админке.

Клиент (21.09.2026): в кабинете OpenRouter появилась оплаченная генерация,
которую в EsAI никто не смог найти. Теперь по ID провайдера, почте или времени
находится запись со всей цепочкой: кто → когда → чем → что → сколько стоило →
сколько списали → на каком шаге всё остановилось.

  GET  generations/?kind=&status=&source=&review=1&q=<почта|ID провайдера>&page=
  POST generations/<id>/reviewed/   — снять отметку «нужен разбор»
"""
from __future__ import annotations

import re

from django.db.models import Count, Q, Sum
from django.urls import NoReverseMatch, reverse
from rest_framework import status
from rest_framework.response import Response

from ai.models import GenerationLog

from .views import StaffAPIView, _paginate

_TAKE_UID = re.compile(r"^[0-9a-f]{32}$")


def _take_link(g: GenerationLog) -> tuple[str, str]:
    """Дубль видеостудии, к которому относится запись: uid и ссылка в админке.

    Журнал хранит uid дубля в params.take (пишет конвейер vstudio). Ссылка
    ведёт на список дублей с фильтром по uid — так не нужен числовой id и
    лишний запрос на каждую строку. Пока приложение vstudio не подключено,
    маршрута нет, и ссылка пустая, а uid всё равно виден.
    """
    if g.source != GenerationLog.SOURCE_VSTUDIO:
        return "", ""
    params = g.params if isinstance(g.params, dict) else {}
    uid = str(params.get("take") or "")
    # uid идёт в строку запроса ссылки — берём только то, что похоже на uid.
    if not _TAKE_UID.match(uid):
        return "", ""
    try:
        url = f"{reverse('admin:vstudio_take_changelist')}?uid={uid}"
    except NoReverseMatch:
        url = ""
    return uid, url


def _row(g: GenerationLog) -> dict:
    take_uid, take_admin_url = _take_link(g)
    return {
        "id": g.pk,
        "created_at": g.created_at.isoformat(),
        "updated_at": g.updated_at.isoformat(),
        "user_id": g.user_id,
        "user_email": g.user.email if g.user_id else "",
        "kind": g.kind,
        "kind_label": g.get_kind_display(),
        "source": g.source,
        "source_label": g.get_source_display(),
        "provider": g.provider,
        "model": g.model,
        "status": g.status,
        "status_label": g.get_status_display(),
        "provider_id": g.provider_id,
        # Целиком: обрезка до 600 символов выглядела в админке как «человек
        # вставил промпт не до конца», хотя провайдеру ушёл весь текст.
        "prompt": g.prompt,
        "prompt_length": len(g.prompt or ""),
        "params": g.params or {},
        "credits_planned": g.credits_planned,
        "credits_charged": g.credits_charged,
        "provider_cost_usd": str(g.provider_cost_usd) if g.provider_cost_usd is not None else None,
        "result_url": g.result_url,
        "error": g.error,
        "stages": g.stages or [],
        "ip": g.ip,
        "needs_review": g.needs_review,
        "scene_id": g.scene_id,
        "session_id": g.session_id,
        "take_uid": take_uid,
        "take_admin_url": take_admin_url,
    }


class GenerationsView(StaffAPIView):
    def get(self, request):
        qs = GenerationLog.objects.select_related("user").order_by("-id")
        params = request.query_params
        kind = (params.get("kind") or "").strip()
        state = (params.get("status") or "").strip()
        source = (params.get("source") or "").strip()
        query = (params.get("q") or "").strip()
        if kind:
            qs = qs.filter(kind=kind)
        if source:
            qs = qs.filter(source=source)
        if state:
            qs = qs.filter(status=state)
        if params.get("review") in ("1", "true"):
            qs = qs.filter(needs_review=True)
        if query:
            # Из кабинета провайдера копируют начало ID («gen-vid-1789973061…»),
            # поэтому ищем по вхождению, а не по точному совпадению.
            cond = (Q(provider_id__icontains=query.rstrip("….")) |
                    Q(user__email__icontains=query) | Q(model__icontains=query))
            # uid дубля видеостудии из её админки — точное совпадение по params.take.
            if _TAKE_UID.match(query):
                cond |= Q(params__take=query)
            qs = qs.filter(cond)
        totals = GenerationLog.objects.aggregate(
            review=Count("id", filter=Q(needs_review=True)),
            lost=Count("id", filter=Q(status=GenerationLog.STATUS_LOST)),
            open=Count("id", filter=Q(status__in=GenerationLog.OPEN_STATES)),
            lost_usd=Sum("provider_cost_usd", filter=Q(status=GenerationLog.STATUS_LOST)),
        )
        count, page = _paginate(qs, request)
        return Response({
            "count": count,
            "results": [_row(g) for g in page],
            "totals": {"review": totals["review"] or 0, "lost": totals["lost"] or 0,
                       "open": totals["open"] or 0,
                       "lost_usd": str(totals["lost_usd"] or 0)},
            # Список «Откуда» для фильтра (?source=): фронт берёт его отсюда,
            # и следующий новый источник не потребует правки страницы.
            "sources": [{"key": k, "label": str(label)} for k, label in GenerationLog.SOURCE_CHOICES],
        })


class GenerationReviewedView(StaffAPIView):
    def post(self, request, pk):
        row = GenerationLog.objects.select_related("user").filter(pk=pk).first()
        if not row:
            return Response({"detail": "Запись не найдена"}, status=status.HTTP_404_NOT_FOUND)
        row.needs_review = False
        row.save(update_fields=["needs_review", "updated_at"])
        return Response(_row(row))
