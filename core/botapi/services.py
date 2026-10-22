"""Бот и сайт — один аккаунт.

Человек, который вошёл на сайте через Telegram, и человек, который написал
боту, — один и тот же: у Telegram один id пользователя на все боты. Поэтому
ищем и создаём ровно то же, что создаёт вход на сайте: SocialAccount
provider=telegram с этим id и пользователя с почтой-заглушкой. Тогда баланс,
чаты и мультфильмы у них общие, и ничего склеивать не приходится.
"""
import logging

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import TelegramChat

logger = logging.getLogger("botapi")

PROVIDER = "telegram"


class TelegramBlocked(Exception):
    """Пользователю закрыт доступ (блок-лист или отключённый аккаунт)."""

    def __init__(self, reason: str = "blocked"):
        super().__init__(reason)
        self.reason = reason


def fallback_email(telegram_id) -> str:
    """Та же почта-заглушка, что делает вход через Telegram на сайте."""
    return f"{PROVIDER}_{telegram_id}@social.esai.local"


def _clean_lang(code: str) -> str:
    code = (code or "").strip().lower()[:5]
    if code.startswith("ky") or code.startswith("kg"):
        return "kg"
    if code.startswith("en"):
        return "en"
    return "ru"


def _fit(field: str, value) -> str:
    """Обрезать строку под реальную длину колонки пользователя.

    В Telegram имя и фамилия бывают до 64 символов, а в User они varchar(30):
    без обрезки Postgres отвечает DataError, аккаунт не заводится, а бот на
    каждое сообщение человека отвечает «сервер не отвечает». Длину берём из
    модели, а не числом: правка модели не должна снова разойтись с этим кодом.
    """
    limit = get_user_model()._meta.get_field(field).max_length
    return str(value or "").strip()[:limit]


def last_deleted_at(telegram_id):
    """Когда этот Telegram в последний раз уходил через /delete (None — не уходил).

    Погашенная заглушка telegram id не хранит: её почта — deleted_<pk>_<ts>,
    а привязка Telegram удалена. След остаётся только в журнале: отвязка
    (linking.forget_telegram) пишет «tg <id> ← user <pk>», а с 05.10 ещё и
    telegram_id в meta. Текст нужен для отвязок, сделанных до 05.10.
    Отвязка аккаунта с настоящей почтой считается тоже: иначе цикл «привязать
    к сайту → /delete → /start» заводил бы заглушку с бонусом снова и снова.
    """
    telegram_id = str(telegram_id or "").strip()
    # Только ASCII-цифры: isdigit() пропускает и «²», и цифры других алфавитов.
    if not (telegram_id.isascii() and telegram_id.isdigit()):
        return None
    try:
        from audit.models import EventLog

        unlinked = (Q(meta__telegram_id=telegram_id, meta__has_key="deactivated")
                    | Q(message__startswith=f"tg {telegram_id} ← user "))
        # Точка сохранения: сбой чтения не должен отравить транзакцию запроса.
        with transaction.atomic():
            return (EventLog.objects.filter(unlinked, type="other")
                    .order_by("-created_at").values_list("created_at", flat=True).first())
    except Exception:
        logger.exception("telegram: журнал отвязок не прочитан")
        return None


def was_deleted_before(telegram_id) -> bool:
    """Этот Telegram уже заводил аккаунт и уходил с него по /delete.

    Нужен, чтобы цикл «/delete → /start» не выдавал приветственный бонус
    заново (см. users.antifraud) и чтобы Creators видели повторную регистрацию.
    """
    return last_deleted_at(telegram_id) is not None


def find_user(telegram_id) -> "object | None":
    account = (SocialAccount.objects
               .select_related("user")
               .filter(provider=PROVIDER, uid=str(telegram_id))
               .first())
    return account.user if account else None


def _check_block(user, telegram_id, request=None) -> None:
    if user is not None and not getattr(user, "is_active", True):
        raise TelegramBlocked("inactive")
    try:
        from users.blocklist import find_block

        email = getattr(user, "email", "") or ""
        if find_block(email=email, ip="", device=f"tg:{telegram_id}", for_login=bool(user)):
            raise TelegramBlocked("blocked")
    except TelegramBlocked:
        raise
    except Exception:
        logger.exception("blocklist: проверка telegram-входа упала")


@transaction.atomic
def _create_user(tg_user: dict, request=None, ref: str = "", promo: str = ""):
    """Завести пользователя ровно так же, как это делает соц-вход на сайте."""
    User = get_user_model()
    telegram_id = str(tg_user["id"])

    user = User(
        email=fallback_email(telegram_id),
        first_name=_fit("first_name", tg_user.get("first_name")),
        last_name=_fit("last_name", tg_user.get("last_name")),
        telegram=_fit("telegram", str(tg_user.get("username") or "").lstrip("@")),
        avatar_url=_fit("avatar_url", tg_user.get("photo_url")),
        is_confirmed=True,
    )
    user.set_unusable_password()
    user.save()
    SocialAccount.objects.create(
        user=user, provider=PROVIDER, uid=telegram_id, extra_data=tg_user)
    return user


def _after_signup(user, request, ref: str = "", promo: str = "", *,
                  welcome: bool = True) -> None:
    """Всё, что сайт делает новому пользователю: план, бонус, реферер, промокод.

    welcome=False — человек уже получал приветственный бонус на прежнем
    аккаунте (погасил его по /delete и вернулся): бонус второй раз не даём.

    Каждый шаг — в своей точке сохранения: запрос идёт в общей транзакции
    (ATOMIC_REQUESTS), и проглоченная здесь ошибка БД иначе отравила бы её —
    запись чата упала бы, аккаунт откатился бы целиком, и так на каждом /start.
    """
    try:
        from users.services import activate_free_plan_for_user

        if not getattr(user, "free_plan_activated", False):
            with transaction.atomic():
                activate_free_plan_for_user(user)
    except Exception:
        logger.exception("telegram signup: активация бесплатного плана")
    try:
        from users.antifraud import maybe_grant_welcome_bonus

        with transaction.atomic():
            maybe_grant_welcome_bonus(user, request, allow_welcome=welcome)
    except Exception:
        logger.exception("telegram signup: приветственный бонус")
    if ref:
        try:
            from users.services import maybe_link_referrer

            with transaction.atomic():
                maybe_link_referrer(request, user, code=ref)
        except Exception:
            logger.exception("telegram signup: привязка реферера")
    if promo:
        try:
            from users.services import activate_promo

            with transaction.atomic():
                activate_promo(user, promo)
        except Exception:
            logger.exception("telegram signup: промокод")


def _sync_profile(user, tg_user: dict) -> None:
    """Подтянуть свежие имя, @username и аватар — они в Telegram меняются."""
    fields = []
    username = _fit("telegram", str(tg_user.get("username") or "").lstrip("@"))
    if username and getattr(user, "telegram", "") != username:
        user.telegram = username
        fields.append("telegram")
    avatar = _fit("avatar_url", tg_user.get("photo_url"))
    if avatar and getattr(user, "avatar_url", "") != avatar:
        user.avatar_url = avatar
        fields.append("avatar_url")
    first = _fit("first_name", tg_user.get("first_name"))
    if first and not (user.first_name or "").strip():
        user.first_name = first
        fields.append("first_name")
    if fields:
        try:
            # Точка сохранения: запрос идёт в общей транзакции (ATOMIC_REQUESTS), и
            # ошибка БД без неё отравила бы её — следующий запрос упал бы уже
            # необработанным.
            with transaction.atomic():
                user.save(update_fields=fields)
        except Exception:
            logger.exception("telegram: обновление профиля")


def authenticate_telegram_user(tg_user: dict, **kwargs) -> tuple:
    """Найти или создать пользователя по данным Telegram.

    Возвращает (user, created). Кидает TelegramBlocked, если вход закрыт.
    Версия с флагом «чат создан» — authenticate_telegram.
    """
    user, created, _chat_created = authenticate_telegram(tg_user, **kwargs)
    return user, created


def authenticate_telegram(tg_user: dict, *, request=None, chat_id=None,
                          source: str = TelegramChat.SOURCE_BOT,
                          ref: str = "", promo: str = "") -> tuple:
    """То же, что authenticate_telegram_user, плюс третий элемент — chat_created.

    chat_created отличается от created: сайтовый аккаунт, впервые пришедший в
    бота, не «создан», но чат с ним новый, и языка ему никто ещё не выбирал.
    """
    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id.isdigit():
        raise ValueError("bad_telegram_user")

    user = find_user(telegram_id)
    _check_block(user, telegram_id, request)

    created = False
    if user is None:
        # Возвращающемуся после /delete приветственный бонус повторно не даём.
        repeat = was_deleted_before(telegram_id)
        try:
            user = _create_user(tg_user, request=request, ref=ref, promo=promo)
            created = True
        except IntegrityError:
            # Два апдейта нового человека пришли разом (aiogram обрабатывает их
            # параллельно): второй упёрся в уникальную почту. Аккаунт уже есть —
            # берём его, а не отвечаем 500.
            user = find_user(telegram_id)
            if user is None:
                raise
        if created:
            _after_signup(user, request, ref=ref, promo=promo, welcome=not repeat)
        else:
            _sync_profile(user, tg_user)
    else:
        _sync_profile(user, tg_user)
        # Промокод существующему пользователю активируем отдельно — как на сайте.
        if promo:
            try:
                from users.services import activate_promo

                activate_promo(user, promo)
            except Exception:
                pass

    lang = _clean_lang(tg_user.get("language_code"))
    chat, chat_created = TelegramChat.objects.update_or_create(
        telegram_id=int(telegram_id),
        defaults={
            "user": user,
            "chat_id": int(chat_id or telegram_id),
            "username": (tg_user.get("username") or "").lstrip("@")[:64],
            "source": source,
            "is_blocked": False,
            "blocked_at": None,
        },
    )
    # Язык ставим только при создании ЧАТА, а не пользователя: у человека с
    # готовым сайтовым аккаунтом чат новый, и без этого он навсегда остался бы
    # на русском (default модели), хотя телефон у него английский или кыргызский.
    # Дальше язык не трогаем: человек мог сменить его в боте руками.
    if chat_created or not chat.lang:
        chat.lang = lang
        chat.save(update_fields=["lang"])
    return user, created, chat_created


def mark_blocked(telegram_id) -> None:
    TelegramChat.objects.filter(telegram_id=int(telegram_id)).update(
        is_blocked=True, blocked_at=timezone.now())
