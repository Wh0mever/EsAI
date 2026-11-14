# -*- coding: utf-8 -*-
"""Кто сейчас на сайте: открытые вкладки шлют отметку раз в 45 секунд.

«Онлайн» — вкладки, отметившиеся за последние ONLINE_WINDOW_SEC. Счёт по
посетителям (случайный id в localStorage браузера), а не по вкладкам: три
вкладки одного человека — один онлайн. Вошедших считаем отдельно, по user_id.

Хранение — Redis напрямую (сортированные множества «id → время отметки»),
мимо KEY_PREFIX кэша: ZADD/ZCARD у Django-кэша нет. В тестах, где кэш
LocMem, работает запасной путь через обычный кэш — медленнее, но им пользуется
только тестовый прогон.
"""
from __future__ import annotations

import re
import time

from django.core.cache import cache
from django.utils import timezone
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

ONLINE_WINDOW_SEC = 120
# Раздел сайта, где сейчас человек. Неизвестное — «other».
SECTIONS = ("chat", "video_studio", "studio", "merge", "pricing", "other")
_VID_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")

K_VISITORS = "esai:presence:v"
K_USERS = "esai:presence:u"
K_SECTION = "esai:presence:sec"  # hash: visitor → раздел
K_PEAK = "esai:presence:peak:{date}"


def _redis():
    """Клиент Redis кэша или None (LocMem в тестах)."""
    client = getattr(cache, "_cache", None)
    get_client = getattr(client, "get_client", None)
    if get_client is None:
        return None
    try:
        return get_client(write=True)
    except Exception:
        return None


# ---------------------------------------------------------------- запасной путь (тесты)

def _fallback_touch(vid: str, user_id: int | None, section: str, now: float) -> None:
    data = cache.get("presence:fallback") or {"v": {}, "u": {}, "s": {}}
    data["v"][vid] = now
    data["s"][vid] = section
    if user_id:
        data["u"][str(user_id)] = now
    cache.set("presence:fallback", data, ONLINE_WINDOW_SEC * 10)


def _fallback_snapshot(now: float) -> tuple[list[str], int, dict]:
    data = cache.get("presence:fallback") or {"v": {}, "u": {}, "s": {}}
    edge = now - ONLINE_WINDOW_SEC
    vids = [v for v, t in data["v"].items() if t >= edge]
    users = sum(1 for t in data["u"].values() if t >= edge)
    return vids, users, {v: data["s"].get(v, "other") for v in vids}


# ---------------------------------------------------------------- ядро

def _peak_key() -> str:
    return K_PEAK.format(date=timezone.localdate().isoformat())


def touch(vid: str, user_id: int | None, section: str) -> None:
    now = time.time()
    section = section if section in SECTIONS else "other"
    r = _redis()
    if r is None:
        _fallback_touch(vid, user_id, section, now)
        online = len(_fallback_snapshot(now)[0])
    else:
        edge = now - ONLINE_WINDOW_SEC
        pipe = r.pipeline()
        pipe.zadd(K_VISITORS, {vid: now})
        pipe.hset(K_SECTION, vid, section)
        if user_id:
            pipe.zadd(K_USERS, {str(user_id): now})
        pipe.zremrangebyscore(K_VISITORS, "-inf", edge)
        pipe.zremrangebyscore(K_USERS, "-inf", edge)
        pipe.zcard(K_VISITORS)
        online = int(pipe.execute()[-1])
    # Пик за сутки — чтобы видеть не только «сейчас».
    key = _peak_key()
    if online > int(cache.get(key) or 0):
        cache.set(key, online, 60 * 60 * 48)


def snapshot() -> dict:
    now = time.time()
    r = _redis()
    if r is None:
        vids, users, sections = _fallback_snapshot(now)
    else:
        edge = now - ONLINE_WINDOW_SEC
        pipe = r.pipeline()
        pipe.zrangebyscore(K_VISITORS, edge, "+inf")
        pipe.zcount(K_USERS, edge, "+inf")
        pipe.hgetall(K_SECTION)
        raw_vids, users, raw_sec = pipe.execute()
        vids = [v.decode() if isinstance(v, bytes) else v for v in raw_vids]
        sec_map = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                   for k, v in (raw_sec or {}).items()}
        alive = set(vids)
        stale = [k for k in sec_map if k not in alive]
        if stale:
            r.hdel(K_SECTION, *stale)  # разделы ушедших — чтобы хэш не рос
        sections = {v: sec_map.get(v, "other") for v in vids}
        users = int(users)
    by_section = {s: 0 for s in SECTIONS}
    for s in sections.values():
        by_section[s if s in by_section else "other"] += 1
    online = len(vids)
    return {
        "online": online,
        "users": min(users, online),
        "guests": max(0, online - users),
        "by_section": by_section,
        "peak_today": max(online, int(cache.get(_peak_key()) or 0)),
        "window_sec": ONLINE_WINDOW_SEC,
    }


# ---------------------------------------------------------------- API

class PresencePingView(APIView):
    """POST /api/users/presence/ {"vid": "...", "section": "chat"} — открытая вкладка жива."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "presence"

    def post(self, request):
        vid = str(request.data.get("vid") or "")
        if not _VID_RE.match(vid):
            return Response({"detail": "bad vid"}, status=400)
        user_id = request.user.id if request.user and request.user.is_authenticated else None
        touch(vid, user_id, str(request.data.get("section") or "other"))
        return Response(status=204)
