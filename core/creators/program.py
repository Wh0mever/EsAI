"""Участие в программе: заявка, одобрение, уровень, блокировка, правка уровней.

Всё, что ТЗ называет ручным, здесь и остаётся ручным: заявку одобряет человек,
уровень при одобрении выбирает человек (значения по умолчанию нет), повышает и
понижает тоже человек. Ни одна функция этого модуля не вызывается автоматически.

Каждое действие администратора пишет строку журнала (audit.AdminActionLog) в
той же транзакции: не записался журнал — откатилось и действие.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.services import _request_ip, log_admin_action

from . import levels
from .errors import MESSAGES, CreatorsError
from .models import Creator, CreatorApplication, CreatorLevel, CreatorWithdrawal
from .notify import emit, emit_to_user

LANGS = ("ru", "en", "kg")
DEFAULT_LANG = "ru"

Q2 = Decimal("0.01")

URL_MAX = 300
OTHER_LINKS_MAX = 5
SAMPLES_MAX = 10
TEXT_MAX = 2000
FOLLOWERS_MAX = 2_000_000_000

# Короткие поля заявки: имя поля -> предельная длина (как в модели).
_SHORT_FIELDS = (("name", 120), ("telegram", 64), ("country", 64))
_LONG_FIELDS = ("occupation", "motivation")
_URL_FIELDS = ("instagram_url", "tiktok_url", "youtube_url")

# Поля уровня, которые правит администратор. Ключ и порядок не меняются:
# по ключу уровень записан в комиссиях и журнале.
LEVEL_FIELDS = ("title", "percent", "min_publications", "min_registrations", "min_paying")
_LEVEL_INT_MAX = 2_000_000_000

# Заявку на вывод закрыла блокировка креатора — так и объясняем, на его языке.
_BLOCK_NOTICE = {
    "ru": MESSAGES["creator_blocked"],
    "en": "The creator account is blocked",
    "kg": "Креатордун аккаунту бөгөттөлгөн",
}


# ---------------------------------------------------------------- помощники

def _text(value) -> str:
    """Строка без краевых пробелов. Нулевой байт Postgres в текст не примет."""
    return str(value).replace("\x00", "").strip()


def _flag(value) -> bool:
    """Булев параметр. Строка "false" из формы не должна стать True."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _reason(value, *, required: bool = False) -> str:
    reason = _text(value or "")
    if required and not reason:
        raise CreatorsError("reason_required")
    return reason


def _pct(percent) -> str:
    """Процент для текста уведомления: 15, а не 15.00; 12.5 остаётся 12.5."""
    return format(Decimal(str(percent)).normalize(), "f")


def _usdt(amount) -> str:
    return str(Decimal(str(amount)).quantize(Q2, rounding=ROUND_DOWN))


def _is_url(value: str) -> bool:
    if not value.lower().startswith(("http://", "https://")):
        return False
    try:
        return bool(urlsplit(value).netloc)
    except ValueError:
        return False


def _locked(creator) -> Creator:
    """Строка креатора под блокировкой (вызывающий уже в transaction.atomic())."""
    pk = getattr(creator, "pk", creator)
    try:
        return Creator.objects.locked(pk)
    except (Creator.DoesNotExist, TypeError, ValueError):
        raise CreatorsError("not_found") from None


def _application_locked(application_id) -> CreatorApplication:
    try:
        # of=("self",): блокируем только заявку, строку пользователя не трогаем.
        return (CreatorApplication.objects.select_for_update(of=("self",))
                .select_related("user").get(pk=application_id))
    except (CreatorApplication.DoesNotExist, TypeError, ValueError):
        raise CreatorsError("not_found") from None


def _sync(stale, fresh, *fields) -> None:
    """Перенести изменённые поля на объект, который передал вызывающий.

    Сервис возвращает свежую строку, но у вызывающего остаётся и старая —
    отдать её в ответе со вчерашним статусом было бы ошибкой.
    """
    if not isinstance(stale, Creator) or stale is fresh:
        return
    for name in fields:
        setattr(stale, name, getattr(fresh, name))


# -------------------------------------------------------------------- заявка

def _clean_urls(data, name: str, limit: int, errors: dict) -> list[str]:
    raw = data.get(name)
    if raw in (None, ""):
        return []
    if not isinstance(raw, (list, tuple)):
        errors[name] = "Передайте список ссылок"
        return []
    urls = []
    for item in raw:
        if not isinstance(item, str):
            errors[name] = "Передайте список ссылок"
            return []
        url = _text(item)
        if not url:
            continue
        if len(url) > URL_MAX:
            errors[name] = f"Ссылка не длиннее {URL_MAX} символов"
            return []
        if not _is_url(url):
            errors[name] = "Ссылка должна начинаться с http:// или https://"
            return []
        urls.append(url)
    if len(urls) > limit:
        errors[name] = f"Не больше {limit} ссылок"
        return []
    return urls


def _clean_application(data) -> dict:
    """Проверить и привести поля заявки. Ошибки — все сразу, по именам полей."""
    if not hasattr(data, "get"):
        data = {}
    errors: dict[str, str] = {}
    clean: dict = {}

    def scalar(name: str):
        value = data.get(name)
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, bool)):
            errors[name] = "Некорректное значение"
            return ""
        return _text(value)

    for name, limit in _SHORT_FIELDS:
        value = scalar(name)
        if name in errors:
            continue
        if not value:
            errors[name] = "Заполните это поле"
        elif len(value) > limit:
            errors[name] = f"Не длиннее {limit} символов"
        clean[name] = value

    for name in _LONG_FIELDS:
        value = scalar(name)
        if name in errors:
            continue
        if not value:
            errors[name] = "Заполните это поле"
        elif len(value) > TEXT_MAX:
            errors[name] = f"Не длиннее {TEXT_MAX} символов"
        clean[name] = value

    for name in _URL_FIELDS:
        value = scalar(name)
        if name in errors:
            continue
        if value and len(value) > URL_MAX:
            errors[name] = f"Ссылка не длиннее {URL_MAX} символов"
        elif value and not _is_url(value):
            errors[name] = "Ссылка должна начинаться с http:// или https://"
        clean[name] = value

    clean["other_links"] = _clean_urls(data, "other_links", OTHER_LINKS_MAX, errors)
    clean["samples"] = _clean_urls(data, "samples", SAMPLES_MAX, errors)

    followers = data.get("followers")
    try:
        if isinstance(followers, (bool, float)) or followers is None:
            raise ValueError
        followers = int(str(followers).strip())
        if not 0 <= followers <= FOLLOWERS_MAX:
            raise ValueError
        clean["followers"] = followers
    except (TypeError, ValueError):
        errors["followers"] = "Укажите целое число от 0"

    lang = _text(data.get("lang") or "").lower()
    clean["lang"] = lang if lang in LANGS else DEFAULT_LANG

    if errors:
        raise CreatorsError("validation", fields=errors)
    if not (clean["instagram_url"] or clean["tiktok_url"] or clean["youtube_url"]
            or clean["other_links"]):
        raise CreatorsError("links_required")
    return clean


def submit_application(user, data: dict, *, request=None) -> CreatorApplication:
    """Подать заявку на участие. Одна открытая заявка на человека.

    Отклонённый может подать снова; тот, чью заявку заблокировали, — только
    после того, как главный администратор снимет запрет.
    """
    if not user or not getattr(user, "pk", None):
        raise CreatorsError("no_user")
    clean = _clean_application(data)

    if Creator.objects.filter(user_id=user.pk).exists():
        raise CreatorsError("already_creator")
    statuses = set(CreatorApplication.objects.filter(user_id=user.pk)
                   .values_list("status", flat=True))
    if CreatorApplication.Status.BLOCKED in statuses:
        raise CreatorsError("apply_blocked")
    if CreatorApplication.Status.NEW in statuses:
        raise CreatorsError("application_open")

    try:
        # Своя точка сохранения: вторая заявка из соседнего запроса упрётся в
        # уникальный индекс, и транзакция запроса должна это пережить.
        with transaction.atomic():
            return CreatorApplication.objects.create(
                user=user, status=CreatorApplication.Status.NEW,
                ip=_request_ip(request) if request is not None else None, **clean)
    except IntegrityError:
        raise CreatorsError("application_open") from None


def approve_application(application_id, *, actor, level_key: str, request=None) -> Creator:
    """Одобрить заявку: человек становится креатором с уровнем, который выбрал администратор.

    Уровня по умолчанию нет намеренно (ТЗ п.8: «Начальный уровень назначает
    администратор»). Промокод здесь не создаётся — его придумывает сам креатор.
    """
    level_key = _text(level_key or "")
    if not level_key:
        # До любых чтений и записей: без выбранного уровня не делаем ничего.
        raise CreatorsError("validation", fields={"level": "Выберите уровень"})

    with transaction.atomic():
        application = _application_locked(application_id)
        if application.status != CreatorApplication.Status.NEW:
            raise CreatorsError("bad_state")
        if Creator.objects.filter(user_id=application.user_id).exists():
            raise CreatorsError("already_creator")
        level = levels.get_level(level_key)
        if level.key != levels.BASE_LEVEL_KEY and not getattr(actor, "is_superuser", False):
            # Повышенный процент — денежное решение, его принимает главный администратор.
            raise CreatorsError("superuser_required")
        if not application.user.is_active:
            # Отключённый аккаунт (удалён или слит с другим): креатор без входа не нужен.
            raise CreatorsError("no_user")

        try:
            with transaction.atomic():
                creator = Creator.objects.create(
                    user=application.user, application=application, level=level,
                    status=Creator.Status.ACTIVE, display_name=application.name,
                    lang=application.lang if application.lang in LANGS else DEFAULT_LANG)
        except IntegrityError:
            raise CreatorsError("already_creator") from None

        application.status = CreatorApplication.Status.APPROVED
        application.decided_by = actor
        application.decided_at = timezone.now()
        application.save(update_fields=["status", "decided_by", "decided_at"])

        # after.level читает сверка creators_check (I9): уровень креатора должен
        # совпадать с последним решением в журнале.
        log_admin_action(actor, "application.approve", target=application, creator=creator,
                         before={"status": CreatorApplication.Status.NEW.value},
                         after={"status": CreatorApplication.Status.APPROVED.value,
                                "level": level.key},
                         request=request)
        emit(creator, "application_approved", level_title=level.title,
             percent=_pct(level.percent))
    return creator


def reject_application(application_id, *, actor, reason: str = "", block: bool = False,
                       request=None) -> CreatorApplication:
    """Отклонить заявку; block=True — ещё и запретить подавать снова."""
    block = _flag(block)
    if block and not getattr(actor, "is_superuser", False):
        # Бессрочный запрет — решение того же веса, что блокировка креатора.
        raise CreatorsError("superuser_required")
    reason = _reason(reason)

    with transaction.atomic():
        application = _application_locked(application_id)
        if application.status != CreatorApplication.Status.NEW:
            raise CreatorsError("bad_state")
        status = (CreatorApplication.Status.BLOCKED if block
                  else CreatorApplication.Status.REJECTED)
        application.status = status
        application.reject_reason = reason
        application.decided_by = actor
        application.decided_at = timezone.now()
        application.save(update_fields=["status", "reject_reason", "decided_by", "decided_at"])

        log_admin_action(actor, "application.block" if block else "application.reject",
                         target=application,
                         before={"status": CreatorApplication.Status.NEW.value},
                         after={"status": status.value}, reason=reason, request=request)
        # Строки Creator нет, поэтому уведомляем человека напрямую, на языке заявки.
        emit_to_user(application.user, application.lang, "application_rejected", reason=reason)
    return application


def unblock_application(application_id, *, actor, reason: str, request=None) -> CreatorApplication:
    """Снять запрет на подачу заявки: blocked -> rejected, человек может подать снова.

    Единственный способ исправить ошибочное «Заблокировать»: админка Django для
    моделей программы только на чтение.
    """
    reason = _reason(reason, required=True)
    with transaction.atomic():
        application = _application_locked(application_id)
        if application.status != CreatorApplication.Status.BLOCKED:
            raise CreatorsError("bad_state")
        application.status = CreatorApplication.Status.REJECTED
        application.decided_by = actor
        application.decided_at = timezone.now()
        application.save(update_fields=["status", "decided_by", "decided_at"])
        log_admin_action(actor, "application.unblock", target=application,
                         before={"status": CreatorApplication.Status.BLOCKED.value},
                         after={"status": CreatorApplication.Status.REJECTED.value},
                         reason=reason, request=request)
    return application


# ------------------------------------------------------------------ креатор

def set_lang(creator, lang: str) -> Creator:
    """Язык уведомлений. Меняет сам креатор, в журнал не пишется."""
    lang = _text(lang or "").lower()
    if lang not in LANGS:
        raise CreatorsError("validation", fields={"lang": "Выберите язык: ru, en или kg"})
    Creator.objects.filter(pk=creator.pk).update(lang=lang)
    creator.lang = lang
    return creator


def set_level(creator, level_key: str, *, actor, reason: str = "", request=None) -> Creator:
    """Сменить уровень (вверх или вниз). Процент меняется только для будущих комиссий.

    Автоматически не вызывается никогда: «условия выполнены» — подсказка
    администратору, а не команда.
    """
    reason = _reason(reason)
    with transaction.atomic():
        fresh = _locked(creator)
        level = levels.get_level(level_key)
        old = fresh.level
        if level.pk == old.pk:
            raise CreatorsError("bad_state")
        fresh.level = level
        # Уведомление «условия выполнены» относится к прежнему уровню: с нового
        # отсчёт начинается заново.
        fresh.next_level_notified = ""
        fresh.save(update_fields=["level", "next_level_notified", "updated_at"])
        log_admin_action(actor, "creator.level_change", target=fresh, creator=fresh,
                         before={"level": old.key, "percent": str(old.percent)},
                         after={"level": level.key, "percent": str(level.percent)},
                         reason=reason, request=request)
        emit(fresh, "level_changed", level_title=level.title, percent=_pct(level.percent),
             old_title=old.title)
    _sync(creator, fresh, "level", "next_level_notified", "updated_at")
    return fresh


def block(creator, *, actor, reason: str, request=None) -> Creator:
    """Заблокировать креатора.

    Баланс замораживается, новые комиссии копятся придержанными, доступ к
    платным моделям пропадает, код перестаёт привязывать новых людей — всё это
    читает статус. Здесь же, под той же блокировкой строки, закрывается
    заявка на вывод в работе: иначе одобренную заявку заблокированного
    креатора оплатил бы оператор, не заглянувший в профиль.
    """
    reason = _reason(reason, required=True)
    with transaction.atomic():
        fresh = _locked(creator)
        if fresh.status != Creator.Status.ACTIVE:
            raise CreatorsError("bad_state")
        now = timezone.now()
        fresh.status = Creator.Status.BLOCKED
        fresh.blocked_at = now
        fresh.blocked_reason = reason
        fresh.save(update_fields=["status", "blocked_at", "blocked_reason", "updated_at"])
        log_admin_action(actor, "creator.block", target=fresh, creator=fresh,
                         before={"status": Creator.Status.ACTIVE.value},
                         after={"status": Creator.Status.BLOCKED.value},
                         reason=reason, request=request)

        # Тот же переход, что withdrawals.reject, записанный напрямую: модуль
        # выводов принадлежит другой части программы. Открытая заявка одна
        # (частичный уникальный индекс), цикл — на случай данных, созданных в обход.
        open_statuses = [CreatorWithdrawal.Status.REVIEW, CreatorWithdrawal.Status.APPROVED]
        for withdrawal in (CreatorWithdrawal.objects.select_for_update()
                           .filter(creator_id=fresh.pk, status__in=open_statuses)
                           .order_by("pk")):
            before = {"status": withdrawal.status}
            withdrawal.status = CreatorWithdrawal.Status.REJECTED
            withdrawal.rejected_by = actor
            withdrawal.rejected_at = now
            withdrawal.reject_reason = "creator_blocked"
            withdrawal.save(update_fields=["status", "rejected_by", "rejected_at",
                                           "reject_reason"])
            log_admin_action(actor, "withdrawal.reject", target=withdrawal, creator=fresh,
                             before=before,
                             after={"status": CreatorWithdrawal.Status.REJECTED.value,
                                    "via": "creator.block"},
                             reason=reason, request=request)
            emit(fresh, "payout_rejected", amount_usdt=_usdt(withdrawal.amount_usdt),
                 reason=_BLOCK_NOTICE.get(fresh.lang, _BLOCK_NOTICE[DEFAULT_LANG]))
    _sync(creator, fresh, "status", "blocked_at", "blocked_reason", "updated_at")
    return fresh


def unblock(creator, *, actor, reason: str = "", request=None) -> Creator:
    """Разблокировать креатора.

    Придержанные комиссии остаются придержанными, пока администратор не
    выпустит или не аннулирует каждую; отклонённая заявка на вывод не
    оживает — креатор подаёт новую.
    """
    reason = _reason(reason)
    with transaction.atomic():
        fresh = _locked(creator)
        if fresh.status != Creator.Status.BLOCKED:
            raise CreatorsError("bad_state")
        before = {"status": Creator.Status.BLOCKED.value, "blocked_at": fresh.blocked_at,
                  "blocked_reason": fresh.blocked_reason}
        fresh.status = Creator.Status.ACTIVE
        fresh.blocked_at = None
        fresh.blocked_reason = ""
        fresh.save(update_fields=["status", "blocked_at", "blocked_reason", "updated_at"])
        log_admin_action(actor, "creator.unblock", target=fresh, creator=fresh, before=before,
                         after={"status": Creator.Status.ACTIVE.value},
                         reason=reason, request=request)
    _sync(creator, fresh, "status", "blocked_at", "blocked_reason", "updated_at")
    return fresh


# -------------------------------------------------------------------- уровни

def _level_percent(value) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CreatorsError("percent_invalid")
    try:
        percent = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise CreatorsError("percent_invalid") from None
    # Сначала границы: у огромного числа quantize сам бросил бы исключение.
    if not percent.is_finite() or not Decimal("0") < percent <= levels.MAX_PERCENT:
        raise CreatorsError("percent_invalid")
    if percent != percent.quantize(Q2):
        # Третий знак после запятой база округлила бы молча.
        raise CreatorsError("percent_invalid")
    return percent.quantize(Q2)


def _clean_level_changes(changes) -> dict:
    if not hasattr(changes, "items"):
        raise CreatorsError("validation", fields={"changes": "Нечего менять"})
    errors: dict[str, str] = {}
    clean: dict = {}
    for name, value in changes.items():
        if name == "reason":
            # Причина — не поле уровня; её часто присылают в том же теле запроса.
            continue
        if name not in LEVEL_FIELDS:
            errors[str(name)] = "Это поле менять нельзя"
        elif name == "percent":
            clean[name] = _level_percent(value)
        elif name == "title":
            title = _text(value) if isinstance(value, str) else ""
            if not title:
                errors[name] = "Заполните это поле"
            elif len(title) > 64:
                errors[name] = "Не длиннее 64 символов"
            clean[name] = title
        else:
            try:
                if isinstance(value, (bool, float)) or value is None:
                    raise ValueError
                number = int(str(value).strip())
                if not 0 <= number <= _LEVEL_INT_MAX:
                    raise ValueError
                clean[name] = number
            except (TypeError, ValueError):
                errors[name] = "Укажите целое число от 0"
    if errors:
        raise CreatorsError("validation", fields=errors)
    if not clean:
        raise CreatorsError("validation", fields={"changes": "Нечего менять"})
    return clean


def edit_level(level_key: str, changes: dict, *, actor, reason: str = "",
               request=None) -> CreatorLevel:
    """Изменить название, процент или пороги уровня.

    Уже начисленные комиссии не меняются: процент в них — слепок на момент
    начисления. Новый процент действует со следующей оплаты.
    """
    clean = _clean_level_changes(changes)
    reason = _reason(reason or (changes.get("reason") if hasattr(changes, "get") else ""))
    with transaction.atomic():
        level = CreatorLevel.objects.select_for_update().filter(
            key=_text(level_key or "")).first()
        if level is None:
            raise CreatorsError("level_unknown")
        before, after = {}, {}
        for name, value in clean.items():
            old = getattr(level, name)
            if old != value:
                before[name], after[name] = old, value
                setattr(level, name, value)
        if not after:
            # Прислали те же значения — менять и записывать в журнал нечего.
            return level
        level.save(update_fields=[*after, "updated_at"])
        log_admin_action(actor, "level.edit", target=level, before=before, after=after,
                         reason=reason, request=request)
    return level
