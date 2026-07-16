"""Celery-задачи приложения users (антифрод v1, ТЗ 4.3 + память пользователя).

process_pending_bonuses — добивает отложенные welcome-бонусы, у которых вышло
окно ожидания (available_at). Beat-расписание уже ссылается на путь
"users.tasks.process_pending_bonuses" (см. core/settings.py).

extract_user_memory — извлекает 0–5 долгоиграющих фактов о пользователе из пары
«user/assistant» дешёвой LLM и складывает их в UserMemory (как у ChatGPT/Anthropic).
"""
from __future__ import annotations

import json
import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from audit.models import PendingBonus
from plans.wallet import grant_welcome_bonus

logger = logging.getLogger(__name__)

_PENDING_BONUS_LOCK = "users:pending_bonus:lock"


@shared_task(
    name="users.tasks.process_pending_bonuses",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=30,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def process_pending_bonuses(self) -> dict:
    """Начислить отложенные welcome-бонусы, у которых наступило available_at.

    Идемпотентно: grant_welcome_bonus не начислит повторно (reason='welcome'),
    а запись переводим в status='approved'. Каждая запись обрабатывается в своём
    try/except, чтобы один битый бонус не валил всю пачку.
    """
    if not cache.add(_PENDING_BONUS_LOCK, "1", timeout=60):
        return {"status": "busy"}
    try:
        now = timezone.now()
        qs = (
            PendingBonus.objects
            .select_related("user")
            .filter(status="pending", available_at__lte=now)
        )

        processed = 0
        failed = 0
        for pb in qs.iterator():
            try:
                if pb.user:
                    grant_welcome_bonus(pb.user)  # идемпотентно
                pb.status = "approved"
                pb.decided_at = now
                pb.save(update_fields=["status", "decided_at"])
                processed += 1
            except Exception as exc:
                failed += 1
                logger.exception(
                    "process_pending_bonuses failed pb=%s user=%s: %s",
                    getattr(pb, "id", None), getattr(pb, "user_id", None), exc,
                )
                continue

        logger.info(
            "process_pending_bonuses done processed=%s failed=%s", processed, failed
        )
        return {
            "processed": processed,
            "failed": failed,
            "ts": int(now.timestamp()),
        }
    finally:
        cache.delete(_PENDING_BONUS_LOCK)


# === Память пользователя: фоновое извлечение фактов из диалога ===

_MEMORY_EXTRACT_SYSTEM = (
    "Ты — модуль долговременной памяти ассистента. Из одной пары сообщений "
    "(пользователь и ответ ассистента) извлеки от 0 до 5 ДОЛГОИГРАЮЩИХ фактов "
    "О ПОЛЬЗОВАТЕЛЕ: имя, профессия/роль, компания, город/страна, язык, устойчивые "
    "предпочтения и привычки, проекты, над которыми он работает, важные личные детали. "
    "Игнорируй разовое, ситуативное и неважное (погода, единичные вопросы, благодарности). "
    "НИКОГДА не сохраняй чувствительное: пароли, коды, номера карт, паспорта, данные о "
    "здоровье. Верни СТРОГО JSON-массив объектов вида "
    '[{"content": "...", "category": "identity|work|preference|project|other", "importance": 1-5}]. '
    "content — короткая формулировка факта от 3-го лица (например: «Пользователя зовут Иван»). "
    "Если фактов нет — верни []. Никакого текста вне JSON."
)


def _parse_facts_json(raw: str) -> list[dict]:
    """Достать JSON-массив фактов из ответа модели (терпимо к обёрткам/```)."""
    text = (raw or "").strip()
    if not text:
        return []
    # Снять markdown-ограждение ```json ... ```
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    # Если модель добавила прелюдию — выдрать первый массив [...].
    if not text.startswith("["):
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    try:
        data = json.loads(text)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


@shared_task(name="users.tasks.extract_user_memory")
def extract_user_memory(user_id: int, user_text: str, assistant_text: str) -> dict:
    """Извлечь долгоиграющие факты о пользователе из пары user/assistant и сохранить.

    Дешёвая модель (settings.MEMORY_EXTRACT_MODEL через OpenRouter) → строгий JSON →
    upsert_memory(source="auto") по каждому факту. Полностью в try/except: задача
    никогда не должна ронять воркер или влиять на чат. Если память выключена — выход.
    """
    try:
        from .models import User
        from .memory import upsert_memory

        user = User.objects.filter(id=user_id).first()
        if not user:
            return {"status": "no_user"}
        if not getattr(user, "memory_enabled", True):
            return {"status": "disabled"}

        user_text = (user_text or "").strip()
        assistant_text = (assistant_text or "").strip()
        if not user_text:
            return {"status": "empty"}

        # Переиспользуем OpenRouter-клиент из чата (ключ/base_url из окружения).
        from ai.handlers import _make_openai_client

        model_name = getattr(settings, "MEMORY_EXTRACT_MODEL", "google/gemini-2.5-flash")
        client = _make_openai_client()

        # Ограничиваем длину входа, чтобы извлечение оставалось дешёвым.
        u = user_text[:4000]
        a = assistant_text[:4000]
        payload = (
            f"СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ:\n{u}\n\n"
            f"ОТВЕТ АССИСТЕНТА:\n{a}"
        )

        completion = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _MEMORY_EXTRACT_SYSTEM},
                {"role": "user", "content": payload},
            ],
            temperature=0,
            max_tokens=400,
        )
        raw = ""
        try:
            raw = completion.choices[0].message.content or ""
        except Exception:
            raw = ""

        facts = _parse_facts_json(raw)
        saved = 0
        for item in facts[:5]:
            content = (item.get("content") or "").strip()
            if not content:
                continue
            category = (item.get("category") or "other").strip().lower()
            try:
                importance = int(item.get("importance") or 1)
            except Exception:
                importance = 1
            importance = max(1, min(5, importance))
            if upsert_memory(user, content, category=category, source="auto", importance=importance):
                saved += 1

        logger.info("extract_user_memory user=%s parsed=%s saved=%s", user_id, len(facts), saved)
        return {"status": "ok", "parsed": len(facts), "saved": saved}
    except Exception as exc:  # noqa: BLE001 — извлечение памяти не должно падать
        logger.warning("extract_user_memory failed user=%s: %s", user_id, exc)
        return {"status": "error", "error": str(exc)}
