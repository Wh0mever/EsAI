"""Уведомления видеостудии: «видео готово» или «не получилось» (§6.6).

Человек может закрыть вкладку сразу после «Создать» — ролик снимается минуты,
а результат всё равно дойдёт. Чтобы он узнал об этом, после выдачи или сбоя
уходят веб-пуш на телефон и запись в колокольчике сайта.

Когда НЕ шлём:
- дубль моложе 60 секунд — человек почти наверняка ещё смотрит на карточку;
- в кэше есть vstudio:seen:<user_id> — страница студии открыта и опрашивает
  дубли (GET takes/?ids= ставит ключ на 30 с): карточка сама покажет итог,
  а пуш поверх открытой вкладки только раздражает;
- отмена в очереди — это действие самого человека.

Тексты только по-русски, как весь бэкенд. Любой сбой здесь глотается: выдача
уже закоммичена, уведомление — вежливость, а не часть денег.

Отправляет отдельная задача vstudio.tasks.notify_take (конвейер ставит её через
wanted()): у pywebpush нет таймаута по умолчанию, и зависший push-сервис не
должен держать ни sweep (страховку с лимитом 50 с), ни слот выдачи.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import TAKE_DONE, TAKE_FAILED, TAKE_LOST, CHARGE_RELEASED, Take

logger = logging.getLogger(__name__)

# Моложе этого дубль не уведомляем: человек ещё на странице.
MIN_AGE = timedelta(seconds=60)
# Сколько живёт отметка «страница открыта» после опроса takes/?ids=.
SEEN_TTL_S = 30
NOTIFY_STATUSES = (TAKE_DONE, TAKE_FAILED, TAKE_LOST)
SNIPPET_CHARS = 60
BODY_CHARS = 180

TITLES = {
    (Take.KIND_VIDEO, TAKE_DONE): "Видео готово",
    (Take.KIND_VIDEO, TAKE_FAILED): "Видео не получилось",
    (Take.KIND_VIDEO, TAKE_LOST): "Видео не получилось",
    (Take.KIND_IMAGE, TAKE_DONE): "Картинка готова",
    (Take.KIND_IMAGE, TAKE_FAILED): "Картинка не получилась",
    (Take.KIND_IMAGE, TAKE_LOST): "Картинка не получилась",
}
BODY_DONE = "Откройте видеостудию, чтобы посмотреть."
BODY_FREE = "Довезли бесплатно — кредиты не списаны."
BODY_FAILED = "Кредиты не списаны."
BODY_LOST = "Не удалось подтвердить запуск — кредиты не списаны, мы проверим вручную."


def seen_key(user_id) -> str:
    return f"vstudio:seen:{user_id}"


def mark_seen(user_id) -> None:
    """Страница студии открыта: пуши по готовым дублям пока не нужны.

    Для BE-9: зовётся из каждого GET takes/?ids= (TTL 30 с).
    """
    if not user_id:
        return
    try:
        cache.set(seen_key(user_id), 1, SEEN_TTL_S)
    except Exception:
        logger.debug("vstudio: отметка seen не записалась user=%s", user_id, exc_info=True)


def is_seen(user_id) -> bool:
    try:
        return bool(cache.get(seen_key(user_id)))
    except Exception:
        # Кэш недоступен — лучше лишний пуш, чем потерянный результат.
        return False


def take_url(take) -> str:
    """Ссылка на карточку: /video-studio/<project_uid>?take=<take_uid> (FE-1)."""
    project = getattr(take, "project", None)
    project_uid = getattr(project, "uid", "") if project is not None else ""
    if not project_uid:
        return "/video-studio"
    return f"/video-studio/{project_uid}?take={take.uid}"


def _snippet(take) -> str:
    shot = getattr(take, "shot", None)
    text = " ".join(str(getattr(shot, "prompt_text", "") or "").split())
    if not text:
        return ""
    return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1].rstrip() + "…"


def texts(take) -> tuple[str, str]:
    """(заголовок, текст) уведомления по итогу дубля."""
    kind = take.kind if take.kind in (Take.KIND_VIDEO, Take.KIND_IMAGE) else Take.KIND_VIDEO
    title = TITLES.get((kind, take.status), TITLES[(kind, TAKE_FAILED)])
    if take.status == TAKE_DONE:
        # lost → done через «Довезти» остаётся released: человек не заплатил.
        tail = BODY_FREE if take.charge_state == CHARGE_RELEASED else BODY_DONE
        snippet = _snippet(take)
        body = f"«{snippet}». {tail}" if snippet else tail
    elif take.status == TAKE_LOST:
        body = str(take.error or "").strip() or BODY_LOST
    else:
        body = str(take.error or "").strip() or BODY_FAILED
        if "не списан" not in body:
            body = f"{body} {BODY_FAILED}"
    if len(body) > BODY_CHARS:
        body = body[: BODY_CHARS - 1].rstrip() + "…"
    return title, body


def should_notify(take, *, now=None) -> bool:
    if take is None or take.status not in NOTIFY_STATUSES:
        return False
    now = now or timezone.now()
    created = getattr(take, "created_at", None)
    if created is not None and now - created < MIN_AGE:
        return False
    return not is_seen(take.user_id)


def notify_take(take, *, now=None) -> bool:
    """Пуш и запись в колокольчике по итогу дубля. True — уведомление ушло.

    Зовётся после коммита done, failed или lost. Никогда не бросает.
    """
    try:
        if not should_notify(take, now=now):
            return False
        title, body = texts(take)
        url = take_url(take)
        user = take.user
    except Exception:
        logger.exception("vstudio: уведомление не собралось take=%s", getattr(take, "uid", "?"))
        return False
    try:
        from users.models import Notification

        note = Notification.objects.create(title=title, body=body)
        note.add_recipients([user])
    except Exception:
        logger.exception("vstudio: уведомление не записалось take=%s", take.uid)
    try:
        from users.webpush import notify_user

        notify_user(user, title, body, url=url)
    except Exception:
        logger.warning("vstudio: пуш не ушёл take=%s", take.uid, exc_info=True)
    logger.info("vstudio notify take=%s status=%s", take.uid, take.status)
    return True


def wanted(take_id, *, now=None) -> bool:
    """Стоит ли ставить задачу уведомления: итог, возраст и «страница не открыта».

    Дешёвая проверка до постановки: молодые дубли и открытая вкладка — это
    почти все запуски, для них задачу не ставим вовсе. Задача проверит ещё раз.
    """
    try:
        row = Take.objects.filter(pk=take_id).values("status", "created_at", "user_id").first()
    except Exception:
        return False
    if not row:
        return False
    return should_notify(Take(status=row["status"], created_at=row["created_at"],
                              user_id=row["user_id"]), now=now)


def notify_take_id(take_id, *, now=None) -> bool:
    """То же по pk: свежая строка с проектом, запросом и пользователем."""
    try:
        take = (Take.objects.select_related("user", "project", "shot")
                .filter(pk=take_id).first())
    except Exception:
        logger.exception("vstudio: дубль для уведомления не прочитался id=%s", take_id)
        return False
    return notify_take(take, now=now) if take is not None else False


__all__ = ["notify_take", "notify_take_id", "wanted", "mark_seen", "is_seen", "seen_key",
           "take_url", "texts", "should_notify", "SEEN_TTL_S", "MIN_AGE"]
