import ipaddress
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import AdminActionLog

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


def _request_ip(request):
    """IP запроса: первый адрес из X-Forwarded-For, иначе REMOTE_ADDR, иначе None.

    Считаем здесь, а не через users.antifraud: журнал не должен зависеть от
    антифрода. Мусор в заголовке отбрасываем — Postgres не примет его в поле
    адреса, и действие администратора откатилось бы из-за чужого заголовка.
    """
    meta = getattr(request, "META", None) or {}
    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    for candidate in (forwarded, str(meta.get("REMOTE_ADDR") or "").strip()):
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return None


def log_admin_action(actor, action: str, *, target=None, creator=None, before: dict | None = None,
                     after: dict | None = None, reason: str = "", request=None) -> "AdminActionLog":
    """Записать ручное действие администратора в AdminActionLog.

    В отличие от log_event БРОСАЕТ исключение при любой ошибке: вызывающий
    держит транзакцию, и действие без записи в журнале должно откатиться.

    actor — кто сделал (обязателен, сохранённый пользователь);
    action — код из audit.models.ADMIN_ACTIONS;
    target — объект действия (в журнал идут его тип и pk);
    creator — креатор, к которому относится действие (для фильтра журнала);
    before / after — что изменилось (Decimal и даты сохраняются строками).
    """
    from .models import ADMIN_ACTIONS, AdminActionLog

    if actor is None or not getattr(actor, "pk", None):
        raise ValueError("actor_required")
    action = str(action or "")
    if action not in ADMIN_ACTIONS:
        # Опечатка в коде действия сломала бы сверку журнала с данными.
        raise ValueError("action_unknown")

    target_type, target_id = "", ""
    if target is not None:
        target_type = f"{target._meta.app_label}.{target._meta.model_name}"
        target_id = str(target.pk)

    return AdminActionLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        creator=creator if (creator is not None and getattr(creator, "pk", None)) else None,
        before=json.loads(json.dumps(before or {}, default=str)),
        after=json.loads(json.dumps(after or {}, default=str)),
        reason=str(reason or ""),
        ip=_request_ip(request) if request is not None else None,
    )
