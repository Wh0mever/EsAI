"""Админка Creative Studio: /api/manage/creative/ (SPEC_B §8).

  GET   settings/   режим, общая наценка, по инструментам: включён, своя наценка, пример цены
  PATCH settings/   {mode?, markup_pct?, tools?: [{id, enabled?, markup_pct?, use_own_markup?}]}
  GET   log/        журнал изменений (audit.AdminActionLog, settings.edit + ключ creative_studio)
  GET   summary/    сводка за период ?from=ГГГГ-ММ-ДД&to=ГГГГ-ММ-ДД: задачи, кредиты, себестоимость, маржа

Только сотрудники (как вся панель); деньги — наценки — меняет только главный
администратор (IsSuperuser). Названия моделей поставщика здесь не отдаются:
админский JS публичен — только наши названия инструментов.
Отказы — {"detail": "<текст>"} как у остальной панели, у формы рядом errors {поле: текст}.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from adminapi.permissions import IsSuperuser
from adminapi.runtime import delete_runtime, get_runtime, set_runtime
from adminapi.views import StaffAPIView
from ai import pricing as ai_pricing
from audit.services import log_admin_action

from . import access, pricing, registry
from .models import JOB_OPEN, CreativeJob, CreativeTool

logger = logging.getLogger(__name__)

LOG_ACTION = "settings.edit"
LOG_KEY = "creative_studio"
LOG_LIMIT = 200
SUMMARY_MAX_DAYS = 366
SUPERUSER_MSG = IsSuperuser.message


def _bad(detail: str, http_status=status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({"detail": detail, **extra}, status=http_status)


def _pct_text(value) -> str | None:
    return None if value is None else format(Decimal(value).normalize(), "f")


def _parse_pct(raw):
    """Процент 0…1000 или None (пусто). ValueError — кривое значение."""
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw).replace(",", "."))
    except (InvalidOperation, ValueError):
        raise ValueError("Наценка — число от 0 до 1000.") from None
    if not value.is_finite() or value < 0 or value > 1000:
        raise ValueError("Наценка — число от 0 до 1000.")
    return value.quantize(Decimal("0.01"))


def _example_label(tool: registry.Tool, params: dict, inputs: dict) -> str:
    parts = []
    if "hint" in inputs:
        parts.append(f"{int(inputs['hint'].duration_s)} с")
    for key in ("duration",):
        if key in params:
            parts.append(f"{params[key]} с")
    for key in ("resolution", "quality"):
        if key in params:
            parts.append(str(params[key]))
    if params.get("count"):
        parts.append(f"{params['count']} шт.")
    if params.get("image") or params.get("product_images"):
        parts.append("с фото")
    return ", ".join(parts) or "по умолчанию"


def _tool_row(tool: registry.Tool, rows: dict, basis) -> dict:
    row = rows.get(tool.id)
    params, inputs = registry.hint_params(tool)
    cost = registry.cost_usd(tool, params, inputs)
    own = pricing.own_markup_pct(tool.id, rows)
    effective = pricing.markup_pct(tool.id, rows)
    try:
        credits = pricing.credits_for(cost, tool.id, effective) if basis is not None else None
    except Exception:
        credits = None
    return {
        "id": tool.id, "n": tool.n, "name": tool.name, "kind": tool.kind,
        "enabled": access.tool_enabled(tool.id, rows),
        "own_markup_pct": _pct_text(row.markup_pct) if row is not None and row.markup_pct is not None else None,
        "use_own_markup": bool(row.use_own_markup) if row is not None else False,
        "effective_markup_pct": _pct_text(max(effective, ai_pricing.current_config().floor_pct)),
        "uses_global": own is None,
        "example": {"label": _example_label(tool, params, inputs), "cost_usd": str(cost),
                    "credits": credits},
    }


def settings_payload() -> dict:
    rows = access.tool_rows()
    basis = ai_pricing.credit_basis()
    cfg = ai_pricing.current_config()
    return {
        "mode": access.creative_mode(),
        "mode_env": access.settings_mode(),
        "mode_override": access.runtime_mode() or None,
        "markup_pct": _pct_text(pricing.global_markup_pct()),
        "markup_default_pct": _pct_text(pricing.DEFAULT_MARKUP_PCT),
        "floor_pct": _pct_text(cfg.floor_pct),
        "credit_usd": str(basis.usd.quantize(Decimal("0.000001"))) if basis is not None else None,
        "tools": [_tool_row(t, rows, basis) for t in registry.TOOLS],
    }


class CreativeSettingsView(StaffAPIView):
    def get(self, request):
        return Response(settings_payload())

    def patch(self, request):
        data = request.data if hasattr(request.data, "get") else {}
        errors: dict = {}
        money = "markup_pct" in data or any(
            isinstance(t, dict) and ("markup_pct" in t or "use_own_markup" in t)
            for t in (data.get("tools") or []) if isinstance(data.get("tools"), list))
        if money and not getattr(request.user, "is_superuser", False):
            return _bad(SUPERUSER_MSG, status.HTTP_403_FORBIDDEN, code="superuser_required")

        changes_mode = None
        if "mode" in data:
            mode = str(data.get("mode") or "").strip().lower()
            if mode and mode not in access.MODES:
                errors["mode"] = "Режим — off, staff или on (пусто — как в окружении)."
            else:
                changes_mode = mode
        markup = None
        markup_set = "markup_pct" in data
        if markup_set:
            try:
                markup = _parse_pct(data.get("markup_pct"))
            except ValueError as exc:
                errors["markup_pct"] = str(exc)
        tool_changes = []
        raw_tools = data.get("tools")
        if raw_tools is not None:
            if not isinstance(raw_tools, list):
                errors["tools"] = "Ожидается список инструментов."
            else:
                for item in raw_tools:
                    if not isinstance(item, dict) or registry.get(item.get("id")) is None:
                        errors["tools"] = "Неизвестный инструмент."
                        break
                    change = {"id": item["id"]}
                    if "enabled" in item:
                        if not isinstance(item["enabled"], bool):
                            errors[f"tools.{item['id']}.enabled"] = "Да или нет."
                            continue
                        change["enabled"] = item["enabled"]
                    if "use_own_markup" in item:
                        if not isinstance(item["use_own_markup"], bool):
                            errors[f"tools.{item['id']}.use_own_markup"] = "Да или нет."
                            continue
                        change["use_own_markup"] = item["use_own_markup"]
                    if "markup_pct" in item:
                        try:
                            change["markup_pct"] = _parse_pct(item["markup_pct"])
                        except ValueError as exc:
                            errors[f"tools.{item['id']}.markup_pct"] = str(exc)
                            continue
                    tool_changes.append(change)
        if errors:
            return _bad("Проверьте поля.", errors=errors)

        before: dict = {}
        after: dict = {}
        with transaction.atomic():
            if changes_mode is not None:
                old = access.runtime_mode() or None
                new = changes_mode or None
                if old != new:
                    if new is None:
                        delete_runtime(access.RUNTIME_MODE_KEY)
                    else:
                        set_runtime(access.RUNTIME_MODE_KEY, new)
                    before["mode"], after["mode"] = old, new
            if markup_set:
                old_raw = get_runtime(pricing.RUNTIME_MARKUP_KEY, "") or None
                new_raw = _pct_text(markup)
                if (old_raw or None) != new_raw:
                    if new_raw is None:
                        delete_runtime(pricing.RUNTIME_MARKUP_KEY)
                    else:
                        set_runtime(pricing.RUNTIME_MARKUP_KEY, new_raw)
                    before["markup_pct"], after["markup_pct"] = old_raw, new_raw
            for change in tool_changes:
                slug = change.pop("id")
                row, _ = CreativeTool.objects.select_for_update().get_or_create(slug=slug)
                old = {"enabled": row.enabled, "markup_pct": _pct_text(row.markup_pct),
                       "use_own_markup": row.use_own_markup}
                for key, value in change.items():
                    setattr(row, key, value)
                row.save()
                new = {"enabled": row.enabled, "markup_pct": _pct_text(row.markup_pct),
                       "use_own_markup": row.use_own_markup}
                if old != new:
                    before[f"tool:{slug}"], after[f"tool:{slug}"] = old, new
            if after:
                log_admin_action(request.user, LOG_ACTION, before={LOG_KEY: before},
                                 after={LOG_KEY: after}, request=request)
        if after:
            transaction.on_commit(ai_pricing.invalidate_price_caches)
        payload = settings_payload()
        payload["changed"] = after
        return Response(payload)


class CreativeLogView(StaffAPIView):
    def get(self, request):
        from audit.models import AdminActionLog

        qs = (AdminActionLog.objects.select_related("actor")
              .filter(action=LOG_ACTION).order_by("-created_at", "-id"))
        items = []
        for row in qs[:LOG_LIMIT * 5]:
            after = row.after if isinstance(row.after, dict) else {}
            if LOG_KEY not in after:
                continue
            before = row.before if isinstance(row.before, dict) else {}
            items.append({"at": row.created_at.isoformat(), "actor": getattr(row.actor, "email", ""),
                          "before": before.get(LOG_KEY) or {}, "after": after.get(LOG_KEY) or {}})
            if len(items) >= LOG_LIMIT:
                break
        return Response({"items": items})


def _parse_day(raw, default):
    if not raw:
        return default
    try:
        return datetime.strptime(str(raw), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Дата — в виде ГГГГ-ММ-ДД.") from None


class CreativeSummaryView(StaffAPIView):
    def get(self, request):
        today = timezone.localdate()
        try:
            day_to = _parse_day(request.query_params.get("to"), today)
            day_from = _parse_day(request.query_params.get("from"), day_to - timedelta(days=29))
        except ValueError as exc:
            return _bad(str(exc))
        if day_from > day_to or (day_to - day_from).days > SUMMARY_MAX_DAYS:
            return _bad("Период — от одного дня до года.")
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(day_from, datetime.min.time()), tz)
        end = timezone.make_aware(datetime.combine(day_to + timedelta(days=1), datetime.min.time()), tz)
        qs = CreativeJob.objects.filter(created_at__gte=start, created_at__lt=end)
        basis = ai_pricing.credit_basis()
        credit_usd = basis.usd if basis is not None else None

        def money(credits, cost):
            revenue = (Decimal(credits or 0) * credit_usd) if credit_usd is not None else None
            cost = Decimal(cost or 0)
            return {"revenue_usd": str(revenue.quantize(Decimal("0.01"))) if revenue is not None else None,
                    "cost_usd": str(cost.quantize(Decimal("0.0001"))),
                    "margin_usd": str((revenue - cost).quantize(Decimal("0.01"))) if revenue is not None else None}

        agg = qs.aggregate(
            total=Count("pk"), done=Count("pk", filter=Q(status="done")),
            failed=Count("pk", filter=Q(status="failed")), nsfw=Count("pk", filter=Q(status="nsfw")),
            canceled=Count("pk", filter=Q(status="canceled")), lost=Count("pk", filter=Q(status="lost")),
            open=Count("pk", filter=Q(status__in=JOB_OPEN)),
            credits=Sum("credits_charged", filter=Q(status="done")),
            cost=Sum("cost_usd", filter=Q(status="done")))
        by_tool = []
        rows = {r["tool_slug"]: r for r in qs.values("tool_slug").annotate(
            jobs=Count("pk"), done=Count("pk", filter=Q(status="done")),
            credits=Sum("credits_charged", filter=Q(status="done")),
            cost=Sum("cost_usd", filter=Q(status="done")))}
        for tool in registry.TOOLS:
            r = rows.get(tool.id) or {}
            by_tool.append({"id": tool.id, "name": tool.name, "jobs": int(r.get("jobs") or 0),
                            "done": int(r.get("done") or 0), "credits": int(r.get("credits") or 0),
                            **money(r.get("credits"), r.get("cost"))})
        return Response({
            "from": day_from.isoformat(), "to": day_to.isoformat(),
            "jobs": {k: int(agg.get(k) or 0) for k in ("total", "done", "failed", "nsfw", "canceled",
                                                        "lost", "open")},
            "credits_charged": int(agg.get("credits") or 0),
            "credit_usd": str(credit_usd.quantize(Decimal("0.000001"))) if credit_usd is not None else None,
            **money(agg.get("credits"), agg.get("cost")),
            "by_tool": by_tool,
        })


__all__ = ["CreativeSettingsView", "CreativeLogView", "CreativeSummaryView", "settings_payload"]
