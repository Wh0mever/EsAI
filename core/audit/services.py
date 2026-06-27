import logging

logger = logging.getLogger("audit")


def log_event(type, message="", user=None, meta=None, level="info"):
    """Безопасно записать событие в EventLog.

    Никогда не роняет вызывающий код: любые ошибки (БД недоступна, кривой meta,
    некорректный user и т.п.) проглатываются и пишутся в обычный лог.

    Возвращает созданный объект EventLog или None при ошибке.

    Параметры
    ---------
    type: str  — одно из audit.models.EventType (например "login", "payment",
                 "error_openrouter", "model_usage", "token_spend", ...).
    message: str — человекочитаемое описание.
    user: User | None — связанный пользователь (FK, может быть None).
    meta: dict | None — произвольные структурированные данные (JSON-сериализуемые).
    level: str — "info" | "warning" | "error".
    """
    try:
        # Импорт внутри функции, чтобы хелпер можно было импортировать
        # из мест, выполняющихся до полной инициализации приложений.
        from .models import EventLog, EventType, EventLevel

        valid_types = set(EventType.values)
        event_type = type if type in valid_types else EventType.OTHER

        valid_levels = set(EventLevel.values)
        event_level = level if level in valid_levels else EventLevel.INFO

        # user должен быть сохранённым экземпляром модели пользователя.
        user_obj = user if (user is not None and getattr(user, "pk", None)) else None

        return EventLog.objects.create(
            type=event_type,
            user=user_obj,
            message=message or "",
            meta=meta,
            level=event_level,
        )
    except Exception:
        # Логирование не должно ломать бизнес-логику.
        try:
            logger.warning("log_event failed (type=%s)", type, exc_info=True)
        except Exception:
            pass
        return None
