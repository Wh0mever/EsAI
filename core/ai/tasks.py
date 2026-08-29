from __future__ import annotations

# Music and image generation Celery tasks were removed for the text-only ESAI build.
# This module is intentionally kept so existing imports of `core.celery.app` and
# Celery autodiscovery remain valid.

import logging
import math

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from core.celery import app  # noqa: F401

logger = logging.getLogger(__name__)


# === Rolling-резюме контекста диалога ====================================
#
# Цель: пользователь может вести очень длинные чаты (сотни/тысячи сообщений),
# а модель не теряет важные факты, принятые решения и общий контекст — при этом
# без заметного роста стоимости и времени ответа.
#
# Как: в модель уходит [system] + [резюме старой части] + [свежие сообщения по
# токен-бюджету] (см. ai.handlers._build_openai_messages). Эта фоновая задача
# инкрементально сворачивает в резюме то, что вышло за «свежее окно». Запускается
# ПОСЛЕ ответа (как extract_user_memory) → на скорость ответа не влияет; считает
# дешёвой моделью (CONTEXT_SUMMARY_MODEL) → стоимость незаметна, а на длинных
# чатах запрос даже дешевле (вместо сотни сообщений — компактное резюме).

_SUMMARY_SYSTEM = (
    "Ты — модуль сжатия контекста диалога. Тебе дают ТЕКУЩЕЕ резюме (может быть "
    "пустым) и НОВЫЕ сообщения, которые выходят из активного окна диалога. "
    "Верни ОБНОВЛЁННОЕ резюме, в котором СОХРАНЕНЫ все важные ФАКТЫ, ПРИНЯТЫЕ "
    "РЕШЕНИЯ, договорённости, имена, числа, требования, термины и общий контекст. "
    "Опускай болтовню, приветствия, повторы и сиюминутные детали. Пиши кратко и "
    "по делу, тезисами, НА ЯЗЫКЕ ДИАЛОГА. Ничего не выдумывай. Не добавляй "
    "пояснений о том, что это резюме. Верни ТОЛЬКО текст обновлённого резюме, "
    "уложись примерно в {limit} символов."
)

_SUMMARY_LOCK = "ai:summary:lock:{sid}"
# Каждое сообщение в payload суммаризации обрезаем, чтобы вход оставался дешёвым.
_PER_MESSAGE_CHARS = 1500


def _select_recent_window_rows(rows, budget):
    """Свежие сообщения, влезающие в token-бюджет (от новых к старым). Всегда ≥1.

    Должна совпадать по логике с ai.handlers._select_recent_window, чтобы задача и
    сборщик контекста одинаково определяли границу «свежего окна».
    """
    kept = []
    used = 0
    for m in reversed(rows):
        t = max(1, math.ceil(len((m.content or "")) / 3))
        if kept and used + t > budget:
            break
        kept.append(m)
        used += t
    kept.reverse()
    return kept


def _render_messages(rows) -> str:
    lines = []
    for m in rows:
        role = "Пользователь" if m.role == "user" else ("Ассистент" if m.role == "assistant" else m.role)
        text = (m.content or "").strip()
        if not text:
            continue
        lines.append(f"{role}: {text[:_PER_MESSAGE_CHARS]}")
    return "\n".join(lines)


@shared_task(name="ai.tasks.summarize_session_context")
def summarize_session_context(session_id: int) -> dict:
    """Инкрементально свернуть «состарившуюся» часть диалога в context_summary.

    Полностью в try/except: задача никогда не должна ронять воркер или влиять на
    чат. Идемпотентна и защищена per-session локом от гонок.
    """
    try:
        if not getattr(settings, "CONTEXT_SUMMARY_ENABLED", True):
            return {"status": "disabled"}

        from .models import AiChatSession

        lock_key = _SUMMARY_LOCK.format(sid=session_id)
        if not cache.add(lock_key, "1", timeout=120):
            return {"status": "busy"}
        try:
            session = AiChatSession.objects.filter(id=session_id).first()
            if not session:
                return {"status": "no_session"}

            budget = int(getattr(settings, "CONTEXT_HISTORY_TOKEN_BUDGET", 8000) or 8000)
            max_chars = int(getattr(settings, "CONTEXT_SUMMARY_MAX_CHARS", 4000) or 4000)

            upto = session.summary_upto_message_id or 0
            # Несвёрнутый «хвост» (id > upto). Сворачиваем, только когда он перерос
            # бюджет окна: самые старые сообщения хвоста уходят в резюме, а в
            # дословном окне остаётся ровно бюджет (см. _build_openai_messages).
            # Хвост ограничен CONTEXT_SUMMARY_MAX_TAIL_ROWS (берём самые СТАРЫЕ —
            # ascending order + срез), иначе при отставании задачи он мог бы расти
            # без предела и разово выжечь контекстное окно модели суммаризации;
            # при большом backlog он рассасывается за несколько прогонов подряд.
            max_tail_rows = int(getattr(settings, "CONTEXT_SUMMARY_MAX_TAIL_ROWS", 500) or 500)
            tail = list(
                session.messages.only("id", "role", "content", "created_at")
                .filter(id__gt=upto).order_by("created_at")[:max_tail_rows]
            )
            kept = _select_recent_window_rows(tail, budget)
            new_old = tail[: len(tail) - len(kept)]
            if not new_old:
                return {"status": "nothing_new", "tail": len(tail)}

            from ai.handlers import _make_openai_client

            model_name = getattr(settings, "CONTEXT_SUMMARY_MODEL", "google/gemini-2.5-flash")
            client = _make_openai_client()

            existing = (session.context_summary or "").strip()
            payload = (
                f"ТЕКУЩЕЕ РЕЗЮМЕ (может быть пустым):\n{existing or '(пусто)'}\n\n"
                f"НОВЫЕ СООБЩЕНИЯ, которые нужно влить в резюме:\n{_render_messages(new_old)}"
            )

            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM.format(limit=max_chars)},
                    {"role": "user", "content": payload},
                ],
                temperature=0,
                max_tokens=1200,
            )
            try:
                updated = (completion.choices[0].message.content or "").strip()
            except Exception:
                updated = ""

            if not updated:
                return {"status": "empty_result"}

            # Граница берётся как max(id), а не new_old[-1].id: устойчиво к
            # совпадающим created_at (порядок по времени мог бы не совпасть с id).
            boundary = max(m.id for m in new_old)
            session.context_summary = updated[:max_chars]
            session.summary_upto_message_id = boundary
            session.save(update_fields=["context_summary", "summary_upto_message_id", "updated_at"])

            logger.info(
                "summarize_session_context session=%s folded=%s upto=%s len=%s",
                session_id, len(new_old), boundary, len(session.context_summary),
            )
            return {"status": "ok", "folded": len(new_old), "summary_len": len(session.context_summary)}
        finally:
            cache.delete(lock_key)
    except Exception as exc:  # noqa: BLE001 — суммаризация не должна падать
        logger.warning("summarize_session_context failed session=%s: %s", session_id, exc)
        return {"status": "error", "error": str(exc)}


@shared_task(name="ai.tasks.openrouter_autoswitch")
def openrouter_autoswitch() -> dict:
    """Обновить балансы аккаунтов OpenRouter и включить запасной, если пора.

    Зачем. На единственном ключе кончались деньги, и сайт вставал целиком, пока
    человек не заметит и не пополнит. Теперь, если у рабочего аккаунта остаток
    упал ниже порога, а запасной с деньгами есть, система переключается сама.

    Переключаемся только на аккаунты, помеченные запасными: молча увести
    расходы на чужой ключ, который завели «на потом», нельзя. Ручной выбор
    рабочего аккаунта это не отменяет — он просто станет отправной точкой для
    следующего автопереключения.
    """
    from django.utils import timezone as _tz

    from adminapi.openrouter import refresh
    from adminapi.runtime import get_runtime

    from .models import OpenRouterAccount

    accounts = list(OpenRouterAccount.objects.all())
    if not accounts:
        return {"status": "no_accounts"}
    for a in accounts:
        refresh(a)

    try:
        floor = float(get_runtime("openrouter_auto_switch_below", 2) or 0)
    except (TypeError, ValueError):
        floor = 2.0

    active = next((a for a in accounts if a.is_active), None)
    if not active:
        return {"status": "no_active"}
    # Ошибка ключа — тоже повод уйти на запасной: аккаунт мог быть отключён.
    drained = active.last_error or (active.balance_usd is not None
                                    and active.balance_usd <= floor)
    if not drained:
        return {"status": "ok", "active": active.title, "balance": active.balance_usd}

    spare = [a for a in accounts
             if a.auto_switch and not a.is_active and not a.last_error
             and (a.balance_usd or 0) > floor]
    if not spare:
        logger.warning("OpenRouter: на «%s» осталось %s, запасного нет",
                       active.title, active.balance_usd)
        return {"status": "no_spare", "active": active.title,
                "balance": active.balance_usd}

    # Берём самый полный: переключаться дважды за час незачем.
    spare.sort(key=lambda a: a.balance_usd or 0, reverse=True)
    winner = spare[0]
    winner.is_active = True
    winner.auto_switched_at = _tz.now()
    winner.save(update_fields=["is_active", "auto_switched_at"])
    logger.warning("OpenRouter: переключился с «%s» ($%s) на «%s» ($%s)",
                   active.title, active.balance_usd, winner.title, winner.balance_usd)
    return {"status": "switched", "from": active.title, "to": winner.title,
            "balance": winner.balance_usd}
