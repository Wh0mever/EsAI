"""Дни активности пользователей для отчёта «Возвраты» (F29).

Два пути записи в audit.UserActivityDay:
- touch() — живой учёт: middleware зовёт его на авторизованный запрос, а кэш
  пропускает в базу только первый заход человека за местные сутки — иначе
  каждый запрос сайта стал бы ещё и записью в базу;
- sync_from_sources() — восстановление по таблицам, которые уже есть (входы,
  продления сессии, траты, оплаты, созданное). Нужно для истории до выкладки
  и для того, что человек делает мимо сайта (Telegram-бот), — middleware
  этого не видит.

«День» везде — местная дата Бишкека (settings.TIME_ZONE), а не UTC: 18:00 UTC
в Бишкеке уже полночь следующего дня, и по UTC вечерние заходы ушли бы во
вчерашний день.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import TruncDate
from django.utils import timezone

logger = logging.getLogger("audit")

BATCH_SIZE = 2000

# Ключ «сегодня уже записан» содержит дату, поэтому полночь ему не страшна;
# запас нужен, чтобы ключ не истёк чуть раньше конца суток и не погнал
# лишнюю (пусть и безвредную) запись в базу.
_KEY_MARGIN_SECONDS = 3600

# Досинхронизация перед отчётом: последние дни, не чаще раза в 10 минут —
# отчёт открывают несколько сотрудников, а проход по всем источникам не бесплатный.
SYNC_RECENT_FLAG = "act:sync:recent"
SYNC_RECENT_DAYS = 3
SYNC_RECENT_EVERY = 600

# Движения кредитов, которые пишутся в запросе самого человека. Остальные не
# годятся: daily_bonus ночная задача начисляет всем подряд; кадры и сцены
# мультстудии, видео и картинки видеостудии, склейка списываются воркером, когда
# результат готов, а покупка зачисляется по вебхуку или сверке — день такой
# строки бывает следующим (ролик запущен в 23:57, готов в 00:04), и человек
# «вернулся» бы, не заходя. Сам запуск этих действий виден по своим источникам:
# проекты, дубли, генерации, оплаты.
USER_ACTION_REASONS = ("chat", "stt", "transfer_out", "promo")


def local_tz():
    """Пояс сайта (Asia/Bishkek). Не текущий активный: день не должен зависеть от запроса."""
    return timezone.get_default_timezone()


def local_day(when: datetime | None = None) -> date:
    """Местная дата момента when (по умолчанию — сейчас)."""
    return timezone.localtime(when or timezone.now(), local_tz()).date()


def day_start(day: date) -> datetime:
    """Начало местных суток day (aware): граница выборки «с такого-то дня»."""
    return datetime(day.year, day.month, day.day, tzinfo=local_tz())


def touch(user, when: datetime | None = None) -> bool:
    """Отметить, что user был на сайте в местный день момента when.

    Возвращает True, если дошли до базы (ключ дня в кэше был новым).
    Никогда не бросает: учёт — не повод уронить запрос пользователя.
    """
    key = None
    try:
        user_id = getattr(user, "pk", None)
        if not user_id or not getattr(user, "is_authenticated", False):
            return False
        moment = when or timezone.now()
        day = local_day(moment)
        till_midnight = day_start(day + timedelta(days=1)) - timezone.localtime(moment, local_tz())
        timeout = max(60, int(till_midnight.total_seconds())) + _KEY_MARGIN_SECONDS
        candidate = f"act:{user_id}:{day.isoformat()}"
        if not cache.add(candidate, 1, timeout=timeout):
            return False
        key = candidate

        from .models import ActivitySource, UserActivityDay

        # Своя транзакция (или точка сохранения внутри чужой): ошибка записи
        # не должна отравить транзакцию того, кто нас позвал.
        with transaction.atomic():
            UserActivityDay.objects.bulk_create(
                [UserActivityDay(user_id=user_id, day=day, source=ActivitySource.LIVE)],
                ignore_conflicts=True,
            )
        return True
    except Exception as exc:
        logger.warning("activity touch failed (user=%s): %s", getattr(user, "pk", None), exc)
        if key:
            # Ключ уже поставлен, а строки нет: снимаем, чтобы следующий
            # запрос этого человека попробовал ещё раз, а не ждал полуночи.
            try:
                cache.delete(key)
            except Exception:
                pass
        return False


# Источник истории: (имя для отчёта команды, модель, поле времени, поле
# пользователя, доп. фильтр). Модели берём по имени, а не импортом: нет
# приложения/модели/поля — источник пропускается с предупреждением.
SOURCES: tuple[tuple[str, str, str, str, Q | None], ...] = (
    # Регистрация — тоже заход на сайт.
    ("registration", "users.User", "date_joined", "id", None),
    # Вход и каждое продление сессии (refresh-токены ротируются, access живёт
    # 12 ч) — главный сигнал визита до живого учёта.
    ("session", "token_blacklist.OutstandingToken", "created_at", "user", None),
    # Вход через Google/Telegram (сигнал user_logged_in, audit/signals.py). Тем же
    # типом пишется и снятие чужой неподтверждённой почты — это про аккаунт,
    # хозяин которого в тот день не заходил, его не берём.
    ("login", "audit.EventLog", "created_at", "user",
     Q(type="login") & ~Q(message__startswith="unproven_email_detached")),
    ("credits", "plans.TokenTransaction", "created_at", "user", Q(reason__in=USER_ACTION_REASONS)),
    # Человек начал оплату — значит, был на сайте (успех не важен).
    ("payment", "payments.Payment", "created_at", "user", None),
    ("chat", "ai.AiChatSession", "created_at", "user", None),
    ("generation", "ai.GenerationLog", "created_at", "user", None),
    ("answer_feedback", "ai.AiMessageFeedback", "created_at", "user", None),
    ("cartoon_project", "cartoon.CartoonProject", "created_at", "user", None),
    ("cartoon_character", "cartoon.CartoonCharacter", "created_at", "user", None),
    ("vstudio_project", "vstudio.Project", "created_at", "user", None),
    ("vstudio_shot", "vstudio.Shot", "created_at", "user", None),
    ("vstudio_take", "vstudio.Take", "created_at", "user", None),
    ("merge", "merge.MergeProject", "created_at", "user", None),
    ("site_feedback", "users.UserFeedback", "created_at", "user", None),
    ("promo", "plans.PromoActivation", "created_at", "user", None),
)


def _sync_source(label: str, time_field: str, user_field: str, extra: Q | None,
                 since: date | None) -> tuple[int, int]:
    """Перенести дни одного источника. Возвращает (найдено пар, добавлено строк)."""
    from .models import ActivitySource, UserActivityDay

    model = apps.get_model(label)
    # _base_manager: менеджер по умолчанию у модели может что-то прятать,
    # а нам нужен любой след человека.
    qs = model._base_manager.filter(**{f"{time_field}__isnull": False,
                                       f"{user_field}__isnull": False})
    if since is not None:
        qs = qs.filter(**{f"{time_field}__gte": day_start(since)})
    if extra is not None:
        qs = qs.filter(extra)
    # order_by() снимает сортировку модели: с ней DISTINCT считал бы
    # различными пары, отличающиеся лишь полем сортировки.
    pairs = list(
        qs.order_by()
        .annotate(_act_day=TruncDate(time_field, tzinfo=local_tz()))
        .values_list(user_field, "_act_day")
        .distinct()
    )
    if not pairs:
        return 0, 0

    existing = UserActivityDay.objects.all()
    if since is not None:
        # Строка источника с временем от начала дня since даёт день не раньше since.
        existing = existing.filter(day__gte=since)
    before = existing.count()
    UserActivityDay.objects.bulk_create(
        (UserActivityDay(user_id=uid, day=day, source=ActivitySource.HISTORY)
         for uid, day in pairs if uid and day),
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )
    return len(pairs), existing.count() - before


def sync_sources_detailed(since: date | None = None) -> list[dict]:
    """Досинхронизация по каждому источнику: [{source, found, added, error}].

    Каждый источник — в своей точке сохранения: сломанный источник (нет
    таблицы, поля) откатывается один и не валит остальные и запрос админки.
    """
    results = []
    for name, label, time_field, user_field, extra in SOURCES:
        try:
            with transaction.atomic():
                found, added = _sync_source(label, time_field, user_field, extra, since)
        except Exception as exc:
            logger.warning("activity sync: source %s (%s) skipped: %s", name, label, exc)
            results.append({"source": name, "found": 0, "added": 0, "error": str(exc)[:200]})
            continue
        results.append({"source": name, "found": found, "added": added, "error": ""})
    return results


def sync_from_sources(since: date | None = None) -> int:
    """Идемпотентно добавить дни активности из существующих таблиц.

    since — с какого местного дня брать (None — вся история). Возвращает число
    НОВЫХ строк (разница счётчиков до/после — параллельные живые записи
    тоже в неё попадут, для отчёта это не важно).
    """
    return sum(r["added"] for r in sync_sources_detailed(since))


def sync_recent() -> int | None:
    """Перед отчётом: досинхронизировать последние дни, не чаще раза в 10 минут.

    None — пропустили (недавно уже синхронизировали или не вышло).
    """
    try:
        if not cache.add(SYNC_RECENT_FLAG, 1, timeout=SYNC_RECENT_EVERY):
            return None
        return sync_from_sources(local_day() - timedelta(days=SYNC_RECENT_DAYS))
    except Exception as exc:
        logger.warning("activity recent sync failed: %s", exc)
        return None
