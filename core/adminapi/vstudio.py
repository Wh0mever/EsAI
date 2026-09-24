"""Отчёт видеостудии в панели (§11).

  GET vstudio/report/?days=30[&model=<openrouter_id>][&kind=video|image]

Только staff. Цифры считает vstudio.reports из дублей и журнала генераций:
дубли по статусам и кодам ошибок, lost и needs_review, доля с референсами и
кадрами, длина промпта и доля выше мягкого лимита, «Сжать с ИИ», медиана и
p90 времени, кредиты, себестоимость, маржа, частичные списания. Страница в
admin-new — Фаза 1.5; до неё ответ читают глазами или скриптом.
"""
from __future__ import annotations

from django.apps import apps
from rest_framework import status
from rest_framework.response import Response

from .views import StaffAPIView

_MODEL_MAX = 128   # Take.model_ref


class VStudioReportView(StaffAPIView):
    def get(self, request):
        # Модели видеостудии импортируем только здесь: пока приложение не в
        # INSTALLED_APPS, импорт на загрузке маршрутов уронил бы всю панель.
        if not apps.is_installed("vstudio"):
            return Response({"error": "Видеостудия не подключена на этом сервере.",
                             "error_code": "vstudio_disabled"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
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
