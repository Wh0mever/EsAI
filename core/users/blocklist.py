"""Чёрный список: запрет регистрации и входа по домену почты, IP или подсети.

Повод — массовые регистрации с одноразовых ящиков (@jmaie.com и подобные):
такие аккаунты берут приветственный бонус и ежедневные бесплатные кредиты, а
пользы от них нет. Антифрод (users/antifraud.py) от этого не спасает: он лишь
задерживает бонус, но саму регистрацию не останавливает.

Правила ведёт клиент в админке (модель SignupBlock), код их только применяет.

Два уровня:
  * регистрация — всегда запрещена, если правило подошло;
  * вход — запрещён дополнительно, при `block_login` (по умолчанию включено),
    иначе уже заведённые аккаунты продолжали бы пользоваться сервисом.

Проверка идёт на КАЖДЫЙ вход, поэтому активные правила лежат в кэше: их
единицы, а запросов много.
"""
from __future__ import annotations

import ipaddress
import logging

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

CACHE_KEY = "users:signup_blocks:v1"
CACHE_TTL = 60  # правило начинает действовать не позже чем через минуту


def normalize_domain(value: str) -> str:
    """Домен из «@Jmaie.com », «https://jmaie.com/» или «user@jmaie.com»."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]
    if "@" in v:
        v = v.rsplit("@", 1)[1]
    return v.strip(". ")


def email_domain(email: str) -> str:
    e = (email or "").strip().lower()
    return e.rsplit("@", 1)[1].strip(". ") if "@" in e else ""


def _rules() -> list[dict]:
    """Активные правила (из кэша). Список плоских словарей, без ORM-объектов."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        from .models import SignupBlock

        rules = [
            {
                "id": r.id,
                "kind": r.kind,
                "value": (r.value or "").strip().lower(),
                "block_login": bool(r.block_login),
            }
            for r in SignupBlock.objects.filter(is_active=True).only(
                "id", "kind", "value", "block_login"
            )
        ]
    except Exception:
        # Таблицы ещё нет (миграция не прошла) или БД недоступна — блокировки
        # молча выключаются. Ломать вход из-за необязательной функции нельзя.
        logger.exception("blocklist: не удалось прочитать правила")
        rules = []
    cache.set(CACHE_KEY, rules, CACHE_TTL)
    return rules


def invalidate_cache() -> None:
    """Сбросить кэш правил (зовётся из сигналов модели)."""
    try:
        cache.delete(CACHE_KEY)
    except Exception:
        pass


def _domain_matches(rule_value: str, domain: str) -> bool:
    """Правило «jmaie.com» ловит и сам домен, и любой его поддомен.

    Иначе после блокировки владелец одноразовой почты просто выдал бы ящики на
    mail.jmaie.com и всё началось бы заново.
    """
    if not rule_value or not domain:
        return False
    return domain == rule_value or domain.endswith("." + rule_value)


def _ip_matches(kind: str, rule_value: str, ip: str) -> bool:
    if not rule_value or not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return False
    try:
        if kind == "ip":
            return addr == ipaddress.ip_address(rule_value)
        # Подсеть: «91.240.0.0/16». strict=False прощает неточную запись сети.
        return addr in ipaddress.ip_network(rule_value, strict=False)
    except ValueError:
        return False


def find_block(email: str = "", ip: str = "", device: str = "", *, for_login: bool = False):
    """Первое подошедшее правило или None.

    for_login=True — проверяем ВХОД, поэтому учитываем только правила с
    block_login. Для регистрации подходит любое активное правило.
    """
    domain = email_domain(email)
    dev = (device or "").strip().lower()
    for r in _rules():
        if for_login and not r["block_login"]:
            continue
        kind = r["kind"]
        if kind == "domain":
            hit = _domain_matches(r["value"], domain)
        elif kind == "device":
            hit = bool(dev) and dev == r["value"]
        else:
            hit = _ip_matches(kind, r["value"], ip)
        if hit:
            _note_hit(r["id"])
            return r
    return None


def _note_hit(rule_id: int) -> None:
    """Счётчик срабатываний — чтобы в админке было видно, какое правило работает."""
    try:
        from django.db.models import F

        from .models import SignupBlock

        SignupBlock.objects.filter(pk=rule_id).update(
            hits=F("hits") + 1, last_hit_at=timezone.now()
        )
    except Exception:
        pass


# Текст пользователю. Намеренно один и тот же для домена и для IP: подсказывать,
# ЧТО именно заблокировано, значит помогать обходить блокировку.
BLOCK_MESSAGE = (
    "Регистрация с этого адреса недоступна. "
    "Если это ошибка — напишите нам через форму обратной связи."
)
