"""Переходы по ссылке креатора.

Одно устройство — один переход в день (уникальный индекс): обновление страницы
и накрутка с одного телефона счётчик не поднимают. Ключ устройства присылает
сам браузер, поэтому поверх него есть потолок переходов с одного адреса в день.
Обе функции зовутся из чужих путей (публичный адрес, регистрация) и никогда не
бросают исключений.
"""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import flags
from .models import CreatorClick

logger = logging.getLogger("creators")

DEVICE_KEY_MAX = 64
# Сколько переходов к одному креатору за день принимаем с одного IP. Ключ
# устройства подделывается одной строкой, и без потолка один адрес накручивал
# бы «Переходы» десятками тысяч в день. Запас оставлен под мобильных
# операторов: за одним адресом сидит много настоящих людей.
IP_DAILY_CAP = 20


def _request_ip(request) -> str:
    meta = getattr(request, "META", None) or {}
    forwarded = str(meta.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or str(meta.get("REMOTE_ADDR") or "").strip()


def _device_key(request) -> str:
    """Ключ устройства: заголовок, иначе тело запроса, иначе cookie."""
    meta = getattr(request, "META", None) or {}
    key = str(meta.get("HTTP_X_DEVICE_KEY") or "").strip()
    if not key:
        try:
            data = getattr(request, "data", None) or {}
            key = str(data.get("device_key") or "").strip()
        except Exception:  # noqa: BLE001 — тело может быть не словарём
            key = ""
    if not key:
        try:
            key = str(request.COOKIES.get("esai_device_key") or "").strip()
        except Exception:  # noqa: BLE001
            key = ""
    return key[:DEVICE_KEY_MAX]


def _write(creator, device_key: str, code: str, ip_hash: str) -> bool:
    """True — записан новый переход; False — такой сегодня уже был."""
    day = timezone.localdate()
    # Своя точка сохранения: проигранная гонка двух запросов не ломает транзакцию запроса.
    with transaction.atomic():
        if ip_hash and (CreatorClick.objects
                        .filter(creator=creator, day=day, ip_hash=ip_hash)
                        .exclude(device_key=device_key).count() >= IP_DAILY_CAP):
            return False
        _, created = CreatorClick.objects.get_or_create(
            creator=creator, device_key=device_key, day=day,
            defaults={"code": code, "ip_hash": ip_hash})
    return bool(created)


def _telegram_uid(user_pk) -> str:
    from allauth.socialaccount.models import SocialAccount

    return str(SocialAccount.objects.filter(user_id=user_pk, provider="telegram")
               .values_list("uid", flat=True).first() or "")


def record(raw_code, request) -> bool:
    """Переход на сайт по ?ref=CODE. True — записан новый переход."""
    try:
        if flags.is_off():
            return False
        from .attribution import creator_code

        row = creator_code(raw_code)
        if row is None or not flags.creator_usable(row.creator):
            return False
        user = getattr(request, "user", None)
        if (user is not None and getattr(user, "is_authenticated", False)
                and user.pk == row.creator.user_id):
            # Креатор открыл собственную ссылку — это не переход.
            return False
        ip = _request_ip(request)
        device_key = _device_key(request)
        # В базе лежит только хеш с секретом: сам адрес посетителя не храним.
        ip_hash = (hashlib.sha256((settings.SECRET_KEY + ip).encode()).hexdigest()
                   if ip else "")
        if not device_key:
            if not ip_hash:
                return False
            device_key = "ip:" + ip_hash[:40]
        return _write(row.creator, device_key, row.code, ip_hash)
    except Exception:  # noqa: BLE001 — в том числе IntegrityError проигранной гонки
        logger.warning("creators.clicks: переход не записан", exc_info=True)
        return False


def record_bot(code_row, user) -> bool:
    """Приход через t.me/<бот>?start=ref_CODE.

    Сайт такого прихода не видит, и без этой строки «Переходов» было бы
    меньше, чем «Регистраций». Считается один раз — на первом /start, который
    создал аккаунт.
    """
    try:
        if flags.is_off():
            return False
        creator = code_row.creator
        if not flags.creator_usable(creator):
            return False
        user_pk = getattr(user, "pk", None)
        if not user_pk or user_pk == creator.user_id:
            return False
        # Ключ — сам Telegram, а не строка пользователя: цикл «/delete -> /start
        # по ссылке» каждый раз заводит нового пользователя, но приход тот же.
        telegram_uid = _telegram_uid(user_pk)
        device_key = f"tg:{telegram_uid}" if telegram_uid else f"user:{user_pk}"
        return _write(creator, device_key, code_row.code, "")
    except Exception:  # noqa: BLE001
        logger.warning("creators.clicks: приход из бота не записан", exc_info=True)
        return False
