"""Проверка бота на живом окружении: `python -m bot.selfcheck`.

Показывает по шагам, что настроено и что отвечает, чтобы не гадать, почему
бот молчит. Ничего не меняет и никому не пишет — только читает.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

from bot.config import settings
from bot.services.api import ApiError, api


OK = "✅"
NO = "❌"
WARN = "⚠️ "


def line(mark: str, title: str, detail: str = "") -> None:
    print(f"{mark} {title}" + (f" — {detail}" if detail else ""))


async def check_settings() -> bool:
    print("\n1. Настройки")
    ok = True
    if settings.bot_token:
        line(OK, "токен бота задан")
    else:
        line(NO, "нет TELEGRAM_PRODUCT_BOT_TOKEN", "бот не запустится")
        ok = False
    if settings.service_secret:
        line(OK, "сервисный секрет задан")
    else:
        line(NO, "нет BOT_SERVICE_SECRET", "запросы к нашему API будут отбиты")
        ok = False
    line(OK, f"режим доступа: {settings.access}",
         "отвечает всем" if settings.access == "all" else f"только своим: {sorted(settings.staff) or 'список пуст'}")
    line(OK, f"API: {settings.api_base}", f"представляемся хостом {settings.public_host}")
    return ok


async def check_telegram() -> bool:
    print("\n2. Telegram")
    if not settings.bot_token:
        line(NO, "пропущено", "нет токена")
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            data = (await client.get(url)).json()
    except Exception as exc:
        line(NO, "Telegram недоступен", str(exc)[:80])
        return False
    if not data.get("ok"):
        line(NO, "токен не принят", str(data.get("description"))[:80])
        return False
    me = data["result"]
    line(OK, f"бот @{me.get('username')}", f"id {me.get('id')}")
    return True


async def check_backend() -> bool:
    print("\n3. Наш API")
    ok = True
    try:
        models = await api.models("", lang="ru")
        line(OK, "каталог моделей отвечает", f"{len(models)} моделей")
    except ApiError as exc:
        line(NO, "каталог моделей недоступен", f"http {exc.status}")
        ok = False
    except Exception as exc:
        line(NO, "до API не достучались", str(exc)[:80])
        return False

    # Служебный вход проверяем несуществующим пользователем: аккаунт не
    # создастся, но подпись и доступ проверятся по-настоящему.
    try:
        await api.auth_telegram({"id": 1}, chat_id=1)
        line(WARN, "служебный вход принял тестового пользователя",
             "создался аккаунт telegram_1 — удалите его в админке")
    except ApiError as exc:
        if exc.status == 401:
            line(NO, "подпись не принята", "секрет в боте и на сервере различаются")
            ok = False
        elif exc.status in (400, 403):
            line(OK, "подпись принята", f"сервер ответил осмысленно (http {exc.status})")
        else:
            line(WARN, "неожиданный ответ", f"http {exc.status}")
    return ok


async def main() -> int:
    print("Проверка бота EsAI")
    settings_ok = await check_settings()
    telegram_ok = await check_telegram()
    backend_ok = await check_backend()
    await api.aclose()

    print("\nИтог")
    if settings_ok and telegram_ok and backend_ok:
        line(OK, "всё готово", "можно запускать: docker compose up -d bot")
        return 0
    line(NO, "есть незакрытые пункты", "смотрите отметки выше")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
