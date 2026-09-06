"""Что бот помнит о человеке между сообщениями.

Всё важное живёт на сайте: аккаунт, баланс, чаты, мультфильмы. Здесь только
короткая память самого бота — токен, выбранная модель, текущий чат — и она
переживает перезапуск, потому что лежит в Redis, а не в процессе.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from bot.config import settings

# Токен живёт 12 часов, берём с запасом поменьше, чтобы не ловить истёкший.
TOKEN_TTL = 11 * 3600
PREF_TTL = 180 * 24 * 3600
BUSY_TTL = 600


class Store:
    def __init__(self, url: str = ""):
        self._redis = redis.from_url(url or settings.redis_url, decode_responses=True)

    async def aclose(self) -> None:
        await self._redis.aclose()

    # ------------------------------------------------------------ токен ---

    async def get_token(self, telegram_id: int) -> str | None:
        return await self._redis.get(f"bot:jwt:{telegram_id}")

    async def set_token(self, telegram_id: int, token: str) -> None:
        await self._redis.set(f"bot:jwt:{telegram_id}", token, ex=TOKEN_TTL)

    async def drop_token(self, telegram_id: int) -> None:
        await self._redis.delete(f"bot:jwt:{telegram_id}")

    # --------------------------------------------------------- настройки ---

    async def get(self, telegram_id: int, key: str, default: Any = None) -> Any:
        raw = await self._redis.get(f"bot:{key}:{telegram_id}")
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    async def set(self, telegram_id: int, key: str, value: Any, ttl: int = PREF_TTL) -> None:
        await self._redis.set(f"bot:{key}:{telegram_id}", json.dumps(value), ex=ttl)

    async def drop(self, telegram_id: int, key: str) -> None:
        await self._redis.delete(f"bot:{key}:{telegram_id}")

    # --------------------------------------------------------- занятость ---

    async def take_busy(self, telegram_id: int) -> bool:
        """Занять человека одной генерацией: две сразу — путаница и лишние траты."""
        return bool(await self._redis.set(f"bot:busy:{telegram_id}", "1",
                                          ex=BUSY_TTL, nx=True))

    async def free_busy(self, telegram_id: int) -> None:
        await self._redis.delete(f"bot:busy:{telegram_id}")

    async def warned_recently(self, telegram_id: int) -> bool:
        """Предупреждать «ещё отвечаю» не чаще раза в десять секунд."""
        return not bool(await self._redis.set(f"bot:warn:{telegram_id}", "1", ex=10, nx=True))

    # ------------------------------------------------------------ прочее ---

    async def seen_update(self, update_id: int) -> bool:
        """Этот апдейт уже обработан? После перезапуска Telegram шлёт их заново."""
        return not bool(await self._redis.set(f"bot:upd:{update_id}", "1",
                                              ex=86400, nx=True))

    async def acquire_lock(self, name: str, ttl_ms: int = 30000) -> bool:
        return bool(await self._redis.set(f"bot:lock:{name}", "1", px=ttl_ms, nx=True))

    async def refresh_lock(self, name: str, ttl_ms: int = 30000) -> None:
        await self._redis.pexpire(f"bot:lock:{name}", ttl_ms)

    async def release_lock(self, name: str) -> None:
        await self._redis.delete(f"bot:lock:{name}")

    # ---------------------------------------------------- очередь оплат ---

    async def push_pending(self, name: str, item: dict) -> None:
        """Отложить то, что не удалось довести до сервера: подтверждение оплаты."""
        await self._redis.rpush(f"bot:pending:{name}", json.dumps(item))

    async def pop_pending(self, name: str, limit: int = 50) -> list[dict]:
        out = []
        for _ in range(limit):
            raw = await self._redis.lpop(f"bot:pending:{name}")
            if raw is None:
                break
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    async def pending_size(self, name: str) -> int:
        return int(await self._redis.llen(f"bot:pending:{name}") or 0)

    async def once(self, key: str, ttl: int = 86400) -> bool:
        """True, если ключ увиден впервые: защита от повторных апдейтов."""
        return bool(await self._redis.set(f"bot:once:{key}", "1", ex=ttl, nx=True))

    async def cache_file_id(self, url: str, file_id: str) -> None:
        """Телеграм умеет пересылать уже загруженный файл по id — экономим трафик."""
        import hashlib

        key = hashlib.sha1(url.encode()).hexdigest()
        await self._redis.set(f"bot:file:{key}", file_id, ex=30 * 24 * 3600)

    async def get_file_id(self, url: str) -> str | None:
        import hashlib

        key = hashlib.sha1(url.encode()).hexdigest()
        return await self._redis.get(f"bot:file:{key}")


store = Store()
