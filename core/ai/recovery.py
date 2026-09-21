"""Довоз оплаченных, но не выданных роликов.

Случай 21.09.2026: провайдер принял запрос, снял видео и взял $1.17, а человек
увидел «не удалось запустить генерацию» и ушёл ни с чем. Вся генерация жила
внутри одного соединения с браузером: стоило ему оборваться (телефон заснул,
ответ задержался, вкладку закрыли) — и готовый ролик оставался у провайдера
невостребованным.

Теперь каждая отправка записана в журнал (GenerationLog) вместе с адресом
опроса. Эта задача раз в несколько минут проходит по записям, которые провайдер
принял, а мы так и не выдали, и доводит дело до конца: скачивает ролик, кладёт
его в тот же чат, списывает кредиты и пишет человеку уведомление.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from . import genlog
from .models import AiChatMessage, AiChatSession, GenerationLog

logger = logging.getLogger(__name__)

# Живая генерация отмечается в журнале раз в полминуты. Молчит дольше — значит
# соединение с человеком оборвалось и довозить ролик предстоит нам.
STALE_AFTER = timedelta(minutes=3)
# Провайдер хранит результат недолго; старше — уже не спасти, только в разбор.
GIVE_UP_AFTER = timedelta(hours=6)


def _claim(row: GenerationLog) -> bool:
    """Забрать запись себе: вторая копия задачи или живой поток её не тронут."""
    return bool(GenerationLog.objects.filter(
        pk=row.pk, status=GenerationLog.STATUS_SUBMITTED, updated_at=row.updated_at,
    ).update(updated_at=timezone.now()))


def _session_for(row: GenerationLog):
    """Чат, куда класть ролик: прежний, а если его удалили — новый."""
    if row.session_id and AiChatSession.objects.filter(pk=row.session_id).exists():
        return row.session
    if not row.user_id:
        return None
    return AiChatSession.objects.create(user=row.user, title="Видео")


def _charge(user, amount: int, meta: dict) -> int:
    """Списать за довезённый ролик; не хватает — списать сколько есть."""
    from plans.wallet import InsufficientTokens, charge_tokens

    if amount <= 0:
        return 0
    try:
        charge_tokens(user, amount, "chat", meta=meta)
        return amount
    except InsufficientTokens as exc:
        if exc.balance > 0:
            try:
                charge_tokens(user, exc.balance, "chat", meta={**meta, "partial": True,
                                                                "required": amount})
                return int(exc.balance)
            except InsufficientTokens:
                return 0
        return 0


def _notify(user, session) -> None:
    try:
        from users.models import Notification

        note = Notification.objects.create(
            title="Ваше видео готово",
            body="Оно снималось дольше обычного и уже лежит в чате.")
        note.add_recipients([user])
    except Exception:
        logger.exception("довоз ролика: уведомление не создалось")
    try:
        from users.webpush import notify_user

        notify_user(user, "Ваше видео готово", "Оно уже в чате EsAI",
                    url=f"/chat/{getattr(session, 'uid', '')}" if session else "/")
    except Exception:
        logger.debug("довоз ролика: пуш не ушёл", exc_info=True)


def deliver(row: GenerationLog) -> str:
    """Довезти один ролик. Возвращает итог: delivered|pending|failed|lost|skipped."""
    from .handlers import _openrouter_config

    entry = genlog.Entry(row)
    cfg = _openrouter_config()
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}
    try:
        poll = requests.get(row.polling_url, headers=headers, timeout=(10, 30)).json() or {}
    except Exception as exc:  # noqa: BLE001
        entry.stage("recover_poll_failed", str(exc)[:200])
        return "pending"
    status = str((poll or {}).get("status") or "").lower()

    if status in ("failed", "error", "canceled"):
        entry.failed(str(poll.get("error") or f"провайдер вернул {status}")[:500])
        return "failed"
    if status != "completed":
        if timezone.now() - row.created_at > GIVE_UP_AFTER:
            entry.lost(f"провайдер так и не отдал результат (статус «{status or 'нет'}»)")
            return "lost"
        entry.stage("recover_waiting", status or "нет статуса")
        return "pending"

    urls = poll.get("unsigned_urls") or []
    if not urls:
        entry.lost("провайдер сообщил о готовности, но ссылки на ролик нет")
        return "lost"
    try:
        dl = requests.get(str(urls[0]), headers=headers, timeout=(10, 120))
        if not (200 <= dl.status_code < 300) or not dl.content:
            raise RuntimeError(f"http {dl.status_code}")
        raw = dl.content
    except Exception as exc:  # noqa: BLE001
        entry.stage("recover_download_failed", str(exc)[:200])
        if timezone.now() - row.created_at > GIVE_UP_AFTER:
            entry.lost(f"ролик готов, но не скачивается: {exc}")
            return "lost"
        return "pending"

    cost = (poll.get("usage") or {}).get("cost") if isinstance(poll.get("usage"), dict) else None
    if not row.user_id:
        entry.lost("ролик готов, но пользователя уже нет")
        return "lost"

    path = default_storage.save(f"ai_videos/{uuid.uuid4().hex}.mp4", ContentFile(raw))
    url = default_storage.url(path)
    entry.stage("saved", url)
    session = _session_for(row)
    with transaction.atomic():
        message = AiChatMessage.objects.create(
            session=session, role="assistant",
            content="Готово — видео сгенерировано 🎬 (снималось дольше обычного)",
            attachments=[{"type": "video", "url": url, "name": "esai-video.mp4",
                          "prompt": (row.prompt or "")[:2000], "model": row.model}],
            meta={"model": row.model, "endpoint": "video", "video": True, "recovered": True,
                  "provider_cost_usd": cost})
        charged = _charge(row.user, int(row.credits_planned or 0), {
            "session_id": session.pk if session else None, "message_id": message.pk,
            "model": row.model, "video": True, "recovered": True, "generation_log": row.pk,
            "provider_cost_usd": cost})
    entry.delivered(credits=charged, cost=cost, result_url=url, message=message, recovered=True)
    _notify(row.user, session)
    return "delivered"


def recover_open_videos(limit: int = 20) -> dict:
    """Пройти по ролям, которые провайдер принял, а мы не выдали."""
    now = timezone.now()
    rows = list(GenerationLog.objects.filter(
        kind=GenerationLog.KIND_VIDEO, status=GenerationLog.STATUS_SUBMITTED,
        source__in=(GenerationLog.SOURCE_CHAT, GenerationLog.SOURCE_BOT),
        updated_at__lt=now - STALE_AFTER,
    ).exclude(polling_url="").select_related("user", "session").order_by("id")[:limit])
    outcome: dict = {}
    for row in rows:
        if not _claim(row):
            continue
        row.refresh_from_db()
        try:
            result = deliver(row)
        except Exception:
            logger.exception("довоз ролика %s упал", row.pk)
            result = "error"
        outcome[result] = outcome.get(result, 0) + 1
    # Отправки, на которые так и не пришёл ответ: исход неизвестен — в разбор.
    stuck = GenerationLog.objects.filter(
        status=GenerationLog.STATUS_SUBMITTING, updated_at__lt=now - timedelta(minutes=15))
    for row in stuck[:50]:
        genlog.Entry(row).lost("запрос ушёл провайдеру, ответа не дождались")
        outcome["lost"] = outcome.get("lost", 0) + 1
    return outcome
