"""Сбор бизнес-метрик для дашборда админки (ТЗ 7.1 + доп.5).

Все запросы read-only. Где данные приблизительные — поля помечены
ключом-суффиксом и флагом is_estimate, чтобы шаблон показал «оценка».
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone


# Условная ставка стоимости OpenRouter за 1 токен (USD). Это ОЦЕНКА:
# в моделях нет реальной per-token цены (есть только markup_coefficient),
# поэтому расход считаем как total_tokens * ставка. Переопределяется env-ом
# AUDIT_OPENROUTER_USD_PER_TOKEN.
def _openrouter_usd_per_token() -> Decimal:
    try:
        raw = getattr(settings, "AUDIT_OPENROUTER_USD_PER_TOKEN", None)
        if raw is None:
            # ~ $0.5 / 1M токенов как грубое усреднение дешёвых моделей.
            return Decimal("0.0000005")
        return Decimal(str(raw))
    except Exception:
        return Decimal("0.0000005")


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def collect_dashboard_metrics() -> dict:
    """Вернуть словарь метрик. Никогда не бросает исключение наружу —
    при ошибке отдельной секции возвращает безопасные нули/None."""
    User = get_user_model()
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now - timedelta(days=30)
    day_ago = now - timedelta(hours=24)

    data: dict = {
        "generated_at": now,
        "estimates": {},  # имя метрики -> текст пояснения
    }

    # ---- Пользователи ----
    try:
        data["users_total"] = User.objects.count()
        data["users_today"] = User.objects.filter(date_joined__gte=today_start).count()
        data["users_month"] = User.objects.filter(date_joined__gte=month_start).count()
    except Exception:
        data["users_total"] = data["users_today"] = data["users_month"] = 0

    # ---- Активность (чат) ----
    try:
        from ai.models import AiChatMessage

        data["messages_total"] = AiChatMessage.objects.count()
        data["user_requests_total"] = AiChatMessage.objects.filter(role="user").count()
        data["active_users_24h"] = (
            AiChatMessage.objects.filter(created_at__gte=day_ago)
            .values("session__user")
            .distinct()
            .count()
        )
        data["active_users_30d"] = (
            AiChatMessage.objects.filter(created_at__gte=month_start)
            .values("session__user")
            .distinct()
            .count()
        )
    except Exception:
        data["messages_total"] = data["user_requests_total"] = 0
        data["active_users_24h"] = data["active_users_30d"] = 0

    # ---- Оплаты ----
    try:
        from payments.models import Payment

        paid_qs = Payment.objects.filter(success=True)
        data["payments_success_count"] = paid_qs.count()
        revenue = paid_qs.aggregate(s=Sum("amount"))["s"] or Decimal("0")
        data["revenue_total"] = revenue
        if data["payments_success_count"] > 0:
            data["avg_check"] = (revenue / data["payments_success_count"]).quantize(Decimal("0.01"))
        else:
            data["avg_check"] = Decimal("0.00")
        # Примечание: суммируем amount в исходных валютах платежей (USD/RUB/KGS)
        # без приведения к одной валюте — пометим как смешанную сумму.
        data["estimates"]["revenue_total"] = (
            "Сумма amount успешных платежей без приведения к единой валюте "
            "(могут смешиваться USD/RUB/KGS)."
        )
    except Exception:
        data["payments_success_count"] = 0
        data["revenue_total"] = Decimal("0")
        data["avg_check"] = Decimal("0.00")

    # ---- Токены ----
    try:
        from plans.models import TokenTransaction

        spent = (
            TokenTransaction.objects.filter(reason="chat", delta__lt=0)
            .aggregate(s=Sum("delta"))["s"]
            or 0
        )
        # delta отрицательная => списано = abs
        data["tokens_spent"] = abs(_safe_int(spent))
        credited = (
            TokenTransaction.objects.filter(reason="purchase", delta__gt=0)
            .aggregate(s=Sum("delta"))["s"]
            or 0
        )
        data["tokens_purchased"] = _safe_int(credited)
    except Exception:
        data["tokens_spent"] = data["tokens_purchased"] = 0

    # ---- Популярные модели + запросы по модели (из AiChatMessage.meta -> model) ----
    # meta хранит model на сообщениях ассистента; считаем в Python, т.к.
    # извлечение JSON-ключа разнится по БД, а тут надёжнее и переносимо.
    try:
        from ai.models import AiChatMessage

        model_counter: dict[str, int] = {}
        total_tokens_sum = 0
        latencies: list[float] = []
        qs = (
            AiChatMessage.objects.exclude(meta__isnull=True)
            .values_list("meta", flat=True)
            .iterator(chunk_size=2000)
        )
        for meta in qs:
            if not isinstance(meta, dict):
                continue
            model = meta.get("model")
            if model:
                key = str(model)
                model_counter[key] = model_counter.get(key, 0) + 1
            tt = meta.get("total_tokens")
            if isinstance(tt, (int, float)):
                total_tokens_sum += int(tt)
            lat = meta.get("latency")
            if isinstance(lat, (int, float)):
                latencies.append(float(lat))

        top_models = sorted(model_counter.items(), key=lambda kv: kv[1], reverse=True)
        data["top_models"] = top_models[:10]
        data["total_tokens_sum"] = total_tokens_sum
        if latencies:
            data["avg_latency"] = round(sum(latencies) / len(latencies), 3)
        else:
            data["avg_latency"] = None  # N/A — latency может отсутствовать в meta
    except Exception:
        data["top_models"] = []
        data["total_tokens_sum"] = 0
        data["avg_latency"] = None

    # ---- Расход OpenRouter / прибыль (ОЦЕНКА) ----
    try:
        rate = _openrouter_usd_per_token()
        cost_estimate = (Decimal(data.get("total_tokens_sum", 0)) * rate).quantize(Decimal("0.01"))
        data["openrouter_cost_estimate_usd"] = cost_estimate
        data["openrouter_rate_used"] = rate
        # Прибыль = выручка − расход(оценка). Выручка может быть в смешанной
        # валюте — поэтому прибыль тоже ОЦЕНКА.
        data["profit_estimate"] = (Decimal(data.get("revenue_total", 0)) - cost_estimate)
        data["estimates"]["openrouter_cost_estimate_usd"] = (
            f"Оценка: sum(total_tokens из meta) × {rate} USD/токен. "
            "Реальной per-token цены в БД нет."
        )
        data["estimates"]["profit_estimate"] = (
            "Оценка: выручка − оценочный расход OpenRouter. "
            "Валюта выручки может быть смешанной."
        )
    except Exception:
        data["openrouter_cost_estimate_usd"] = Decimal("0.00")
        data["openrouter_rate_used"] = _openrouter_usd_per_token()
        data["profit_estimate"] = Decimal("0.00")

    # ---- Ошибки OpenRouter + среднее время ответа из EventLog ----
    try:
        from .models import EventLog

        data["errors_openrouter"] = EventLog.objects.filter(type="error_openrouter").count()
        data["errors_server"] = EventLog.objects.filter(type="error_server").count()
        data["errors_freedompay"] = EventLog.objects.filter(type="error_freedompay").count()
    except Exception:
        data["errors_openrouter"] = data["errors_server"] = data["errors_freedompay"] = 0

    return data
