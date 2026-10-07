"""Видеостудия в панели: отчёт (§11) и витрина первого экрана.

  GET vstudio/report/?days=30[&model=<openrouter_id>][&kind=video|image]

Только staff. Цифры считает vstudio.reports из дублей и журнала генераций:
дубли по статусам и кодам ошибок, lost и needs_review, доля с референсами и
кадрами, длина промпта и доля выше мягкого лимита, «Сжать с ИИ», медиана и
p90 времени, кредиты, себестоимость, маржа, частичные списания. Страница в
admin-new — Фаза 1.5; до неё ответ читают глазами или скриптом.

  GET    vstudio/showcase/?scope=staff|all[&q=][&page=]   витрина и кандидаты
  POST   vstudio/showcase/ {take, title, category, …}     поставить дубль
  PATCH  vstudio/showcase/<id>/                           название, раздел, порядок, показ
  DELETE vstudio/showcase/<id>/                           убрать из витрины

Витрину («Сделано в EsAI») видят все посетители студии. Что можно показывать,
что уходит наружу и запись в журнал действий — в vstudio.showcase; здесь
только разбор запроса и форма ответа. Отказы — телом {"detail": "<текст>"},
как у остальной панели.
"""
from __future__ import annotations

from django.apps import apps
from rest_framework import status
from rest_framework.response import Response

from .views import PAGE_SIZE, StaffAPIView, _paginate

_MODEL_MAX = 128   # Take.model_ref
_QUERY_MAX = 200


def _not_installed() -> Response:
    return Response({"error": "Видеостудия не подключена на этом сервере.",
                     "error_code": "vstudio_disabled"},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE)


class VStudioReportView(StaffAPIView):
    def get(self, request):
        # Модели видеостудии импортируем только здесь: пока приложение не в
        # INSTALLED_APPS, импорт на загрузке маршрутов уронил бы всю панель.
        if not apps.is_installed("vstudio"):
            return _not_installed()
        from vstudio import reports

        params = request.query_params
        kind = (params.get("kind") or "").strip()
        model = (params.get("model") or "").strip()
        if kind and kind not in reports.KINDS:
            return Response({"error": "kind: только video или image.", "error_code": "bad_request"},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(model) > _MODEL_MAX:
            return Response({"error": "Слишком длинный ID модели.", "error_code": "bad_request"},
                            status=status.HTTP_400_BAD_REQUEST)
        days = reports.parse_days(params.get("days"))
        return Response(reports.build_report(days, model=model, kind=kind))


def _showcase():
    """Сервис витрины или None, если видеостудия не подключена (импорт — как у отчёта)."""
    if not apps.is_installed("vstudio"):
        return None
    from vstudio import showcase

    return showcase


def _body(request) -> dict:
    data = getattr(request, "data", None)
    return data if hasattr(data, "get") else {}


class VStudioShowcaseView(StaffAPIView):
    """GET — витрина целиком и готовые дубли, которых в ней нет; POST — поставить дубль."""

    def get(self, request):
        showcase = _showcase()
        if showcase is None:
            return _not_installed()
        scope = showcase.parse_scope(request.query_params.get("scope"))
        query = str(request.query_params.get("q") or "").strip()[:_QUERY_MAX]
        count, page = _paginate(showcase.candidates_qs(scope, query), request)
        return Response({
            "items": showcase.staff_items(),
            "candidates": {"count": count, "page_size": PAGE_SIZE,
                           "results": [showcase.take_row(take) for take in page]},
            "scope": scope,
            "categories": [{"key": key, "label": label} for key, label in showcase.CATEGORY_CHOICES],
            "public_limit": showcase.MAX_PUBLIC,
        })

    def post(self, request):
        showcase = _showcase()
        if showcase is None:
            return _not_installed()
        item, created = showcase.add(_body(request), actor=request.user, request=request)
        return Response(showcase.staff_json(item),
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class VStudioShowcaseItemView(StaffAPIView):
    """PATCH — поправить строку витрины; DELETE — убрать работу (сам дубль остаётся)."""

    def patch(self, request, pk):
        showcase = _showcase()
        if showcase is None:
            return _not_installed()
        item = showcase.edit(showcase.get_item(pk), _body(request), actor=request.user,
                             request=request)
        return Response(showcase.staff_json(item))

    def delete(self, request, pk):
        showcase = _showcase()
        if showcase is None:
            return _not_installed()
        showcase.remove(showcase.get_item(pk), actor=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
