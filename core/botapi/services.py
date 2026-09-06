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
from django.db import transaction
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
        first_name=(tg_user.get("first_name") or "")[:150],
        last_name=(tg_user.get("last_name") or "")[:150],
        telegram=(tg_user.get("username") or "").lstrip("@")[:30],
        avatar_url=(tg_user.get("photo_url") or "")[:512],
        is_confirmed=True,
    )
    user.set_unusable_password()
    user.save()
    SocialAccount.objects.create(
        user=user, provider=PROVIDER, uid=telegram_id, extra_data=tg_user)
    return user


def _after_signup(user, request, ref: str = "", promo: str = "") -> None:
    """Всё, что сайт делает новому пользователю: план, бонус, реферер, промокод."""
    try:
        from users.services import activate_free_plan_for_user

        if not getattr(user, "free_plan_activated", False):
            activate_free_plan_for_user(user)
    except Exception:
        logger.exception("telegram signup: активация бесплатного плана")
    try:
        from users.antifraud import maybe_grant_welcome_bonus

        maybe_grant_welcome_bonus(user, request)
    except Exception:
        logger.exception("telegram signup: приветственный бонус")
    if ref:
        try:
            from users.services import maybe_link_referrer

            maybe_link_referrer(request, user, code=ref)
        except Exception:
            logger.exception("telegram signup: привязка реферера")
    if promo:
        try:
            from users.services import activate_promo

            activate_promo(user, promo)
        except Exception:
            logger.exception("telegram signup: промокод")


def _sync_profile(user, tg_user: dict) -> None:
    """Подтянуть свежие имя, @username и аватар — они в Telegram меняются."""
    fields = []
    username = (tg_user.get("username") or "").lstrip("@")[:30]
    if username and getattr(user, "telegram", "") != username:
        user.telegram = username
        fields.append("telegram")
    avatar = (tg_user.get("photo_url") or "")[:512]
    if avatar and getattr(user, "avatar_url", "") != avatar:
        user.avatar_url = avatar
        fields.append("avatar_url")
    first = (tg_user.get("first_name") or "")[:150]
    if first and not (user.first_name or "").strip():
        user.first_name = first
        fields.append("first_name")
    if fields:
        try:
            user.save(update_fields=fields)
        except Exception:
            logger.exception("telegram: обновление профиля")


def authenticate_telegram_user(tg_user: dict, *, request=None, chat_id=None,
                               source: str = TelegramChat.SOURCE_BOT,
                               ref: str = "", promo: str = "") -> tuple:
    """Найти или создать пользователя по данным Telegram.

    Возвращает (user, created). Кидает TelegramBlocked, если вход закрыт.
    """
    telegram_id = str(tg_user.get("id") or "").strip()
    if not telegram_id.isdigit():
        raise ValueError("bad_telegram_user")

    user = find_user(telegram_id)
    _check_block(user, telegram_id, request)

    created = False
    if user is None:
        user = _create_user(tg_user, request=request, ref=ref, promo=promo)
        created = True
        _after_signup(user, request, ref=ref, promo=promo)
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
    chat, _ = TelegramChat.objects.update_or_create(
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
    # Язык ставим только при создании: человек мог сменить его в боте руками.
    if created or not chat.lang:
        chat.lang = lang
        chat.save(update_fields=["lang"])
    return user, created


def mark_blocked(telegram_id) -> None:
    TelegramChat.objects.filter(telegram_id=int(telegram_id)).update(
        is_blocked=True, blocked_at=timezone.now())
