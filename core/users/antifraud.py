"""Антифрод v1 для welcome-бонуса (ТЗ 4.3).

Защита приветственного бонуса (3000 токенов) от массовой накрутки фейками с
одного устройства/IP. Логика:
  - approve → начислить бонус сразу (grant_welcome_bonus);
  - delay   → положить бонус в очередь PendingBonus на ANTIFRAUD_BONUS_PENDING_HOURS
              часов, начислит позже крон users.tasks.process_pending_bonuses;
  - reject  → зарезервировано (пока не используется).

Главная точка входа — maybe_grant_welcome_bonus(user, request). Она заменяет
прямой вызов grant_welcome_bonus в местах регистрации. Антифрод НЕ должен ломать
регистрацию: при любой ошибке делаем фолбэк на обычное начисление.
"""
from __future__ import annotations

import ipaddress
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from audit.models import PendingBonus
from plans.models import TokenTransaction
from plans.wallet import grant_welcome_bonus

logger = logging.getLogger(__name__)


def get_client_ip(request) -> str | None:
    """IP клиента: первый хоп X-Forwarded-For либо REMOTE_ADDR."""
    if request is None:
        return None
    try:
        meta = getattr(request, "META", {}) or {}
        xff = meta.get("HTTP_X_FORWARDED_FOR")
        if xff:
            ip = xff.split(",")[0].strip()
            if ip:
                return ip
        return meta.get("REMOTE_ADDR") or None
    except Exception:
        return None


def ip_subnet(ip) -> str:
    """Префикс подсети: /24 для IPv4, /64 для IPv6. Безопасно к мусору."""
    if not ip:
        return ""
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except (ValueError, Exception):
        return ""
    try:
        if isinstance(addr, ipaddress.IPv4Address):
            net = ipaddress.ip_network(f"{addr}/24", strict=False)
            return str(net)
        # IPv6 → /64
        net = ipaddress.ip_network(f"{addr}/64", strict=False)
        return str(net)
    except Exception:
        return str(ip)


def get_fingerprint(request) -> str:
    """Ключ устройства клиента.

    Порядок: X-Device-Key (его шлёт фронт при входе) → X-Device-Fingerprint
    (историческое имя) → поле fingerprint в теле → cookie esai_device_key.

    Cookie нужна ради соц-входа: там браузер уходит к Google/Telegram и
    возвращается редиректом, заголовок в такой поездке не выживет.
    """
    if request is None:
        return ""
    try:
        meta = getattr(request, "META", {}) or {}
        for header in ("HTTP_X_DEVICE_KEY", "HTTP_X_DEVICE_FINGERPRINT"):
            fp = meta.get(header)
            if fp:
                return str(fp).strip()[:128]
    except Exception:
        pass
    try:
        data = getattr(request, "data", None)
        if data is None:
            data = getattr(request, "POST", None)
        if data is not None:
            fp = data.get("fingerprint") or data.get("device_key")
            if fp:
                return str(fp).strip()[:128]
    except Exception:
        pass
    try:
        fp = (getattr(request, "COOKIES", {}) or {}).get("esai_device_key")
        if fp:
            return str(fp).strip()[:128]
    except Exception:
        pass
    return ""


def record_signup_device(user, request):
    """Создать запись SignupDevice (ip/subnet/ua/fingerprint)."""
    # Импорт здесь, чтобы не плодить циклических импортов на уровне модуля.
    from audit.models import SignupDevice

    ip = get_client_ip(request)
    subnet = ip_subnet(ip)
    user_agent = ""
    try:
        user_agent = (getattr(request, "META", {}) or {}).get("HTTP_USER_AGENT", "") or ""
    except Exception:
        user_agent = ""
    fingerprint = get_fingerprint(request)

    return SignupDevice.objects.create(
        user=user,
        ip=ip,
        subnet=subnet or "",
        user_agent=user_agent,
        fingerprint=fingerprint or "",
    )


def decide_welcome_bonus(user, request) -> str:
    """Решение по бонусу: "approve" либо "delay".

    CGNAT-safe: НЕ задерживаем по IP/подсети — в Кыргызстане мобильные операторы
    массово на CGNAT, за одним IP сидят сотни реальных юзеров, и задержка по IP
    бьёт по легитимным (плохой первый опыт). Фарм welcome к тому же бессмыслен
    экономически (бонус тратится только на ×1-модели, ~$0.0015/аккаунт).

    Задержка ТОЛЬКО при сильном сигнале мультиаккаунта — совпадении реального
    device-fingerprint у >= ANTIFRAUD_SIGNUPS_PER_IP_24H разных юзеров за 24ч.
    Пока fingerprint не собирается с фронта (пусто) → всегда approve. Слепок
    IP/UA при этом всё равно пишется (record_signup_device) для мониторинга/v2.
    """
    from audit.models import SignupDevice

    threshold = int(getattr(settings, "ANTIFRAUD_SIGNUPS_PER_IP_24H", 3) or 3)
    fingerprint = get_fingerprint(request)

    # Нет надёжного отпечатка устройства — не по чему судить о мультиаккаунте,
    # одобряем сразу (IP/подсеть НЕ используем как триггер — см. CGNAT выше).
    if not fingerprint:
        return "approve"

    since = timezone.now() - timedelta(hours=24)
    distinct_users = (
        SignupDevice.objects
        .filter(fingerprint=fingerprint, created_at__gte=since)
        .values_list("user_id", flat=True)
        .distinct()
    )
    count = len({uid for uid in distinct_users if uid is not None})

    if count >= threshold:
        return "delay"
    return "approve"


def _welcome_already_handled(user) -> bool:
    """True, если welcome уже начислен или уже стоит в очереди PendingBonus."""
    try:
        if TokenTransaction.objects.filter(user=user, reason="welcome").exists():
            return True
    except Exception:
        pass
    try:
        if PendingBonus.objects.filter(user=user, reason="welcome").exists():
            return True
    except Exception:
        pass
    return False


def maybe_grant_welcome_bonus(user, request) -> dict:
    """Главная точка входа антифрода (замена прямого grant_welcome_bonus).

    Возвращает dict со статусом: already / approved / pending. При любой ошибке
    делает фолбэк на обычное начисление (антифрод не должен ломать регистрацию).
    """
    if not user or not getattr(user, "pk", None):
        return {"status": "skipped"}

    amount = int(getattr(settings, "WELCOME_BONUS_TOKENS", 3000) or 0)
    try:
        from adminapi.runtime import get_runtime

        amount = int(get_runtime("WELCOME_BONUS_TOKENS", amount))
    except Exception:
        pass

    # Приветственный бонус отключён (клиент убрал его в пользу ежедневных).
    # Тогда сразу выдаём дневную норму, иначе человек регистрируется и сидит с
    # нулём до ночного прогона начислений — то есть до суток без сервиса.
    if amount <= 0:
        try:
            record_signup_device(user, request)
        except Exception:
            pass
        try:
            from django.conf import settings as dj_settings
            from adminapi.runtime import get_runtime as _rt
            from plans.wallet import set_balance_to

            target = int(_rt("DAILY_RETENTION_TARGET",
                             getattr(dj_settings, "DAILY_RETENTION_TARGET", 0) or 0))
            if target > 0 and int(getattr(user, "token_balance", 0) or 0) < target:
                set_balance_to(user, target, reason="daily_bonus",
                               meta={"task": "signup_initial"})
                return {"status": "daily_granted", "amount": target}
        except Exception:
            logger.exception("выдача дневной нормы при регистрации не удалась")
        return {"status": "no_welcome_bonus"}

    try:
        # Слепок устройства фиксируем всегда (нужен и для оценки следующих).
        record_signup_device(user, request)

        # Идемпотентность: уже начислено или уже в очереди — выходим.
        if _welcome_already_handled(user):
            return {"status": "already"}

        decision = decide_welcome_bonus(user, request)

        if decision == "delay":
            hours = int(getattr(settings, "ANTIFRAUD_BONUS_PENDING_HOURS", 24) or 24)
            ip = get_client_ip(request)
            # Идемпотентность: уникальный ключ (user, reason='welcome'). get_or_create
            # гарантирует, что повторный вызов/гонка не создаст дубль PendingBonus —
            # не полагаемся только на блокировку строки.
            _, was_created = PendingBonus.objects.get_or_create(
                user=user,
                reason="welcome",
                defaults={
                    "amount": amount,
                    "status": "pending",
                    "available_at": timezone.now() + timedelta(hours=hours),
                    "ip": ip,
                    "meta": {
                        "subnet": ip_subnet(ip),
                        "fingerprint": get_fingerprint(request),
                        "source": "signup",
                    },
                },
            )
            if not was_created:
                # Уже стоял в очереди — повтор ничего не плодит.
                return {"status": "already"}
            logger.info("welcome_bonus delayed user=%s ip=%s", user.pk, ip)
            return {"status": "pending"}

        # approve
        grant_welcome_bonus(user)  # идемпотентно по reason='welcome'
        return {"status": "approved", "amount": amount}
    except Exception as exc:
        logger.exception("antifraud welcome bonus failed user=%s: %s", getattr(user, "pk", None), exc)
        # Фолбэк: не лишаем легитимного пользователя бонуса из-за нашей ошибки.
        try:
            grant_welcome_bonus(user)
        except Exception:
            pass
        return {"status": "approved", "fallback": True}
