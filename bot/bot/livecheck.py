"""Проверка связки бот ↔ API на живом сервере: python -m bot.livecheck <telegram_id>

Юнит-тесты подменяют API заглушками и не видят расхождений контрактов
(первый /image на проде упал из-за Accept-заголовка, который DRF отверг с 406).
Этот скрипт делает настоящие вызовы от имени указанного пользователя —
только чтение и бесплатные операции, кредиты не тратятся, если не передать
--chat (один короткий вопрос дешёвой модели).

Запуск на проде:
    docker compose exec bot python -m bot.livecheck 123456789 [--chat]
"""
from __future__ import annotations

import asyncio
import io
import json
import struct
import sys
import wave

from bot.services.api import ApiError, api

OK, NO = "✅", "❌"


def _wav_silence(seconds: float = 1.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"".join(struct.pack("<h", 0) for _ in range(int(8000 * seconds))))
    return buffer.getvalue()


async def _call(report: list, label: str, coro, *, expect_error: str = ""):
    try:
        result = await coro
        shown = {**result, "access": "<скрыт>"} if isinstance(result, dict) and "access" in result else result
        preview = json.dumps(shown, ensure_ascii=False, default=str)[:110]
        report.append((True, label, preview))
        return result
    except ApiError as exc:
        good = bool(expect_error) and (exc.code == expect_error or str(exc.status) == expect_error)
        report.append((good, label, f"http {exc.status} {exc.code} {exc.message[:80]}"))
    except Exception as exc:  # noqa: BLE001
        report.append((False, label, f"{type(exc).__name__}: {str(exc)[:100]}"))
    return None


async def run(telegram_id: int, with_chat: bool) -> int:
    try:
        return await _run(telegram_id, with_chat)
    finally:
        await api.aclose()


async def _run(telegram_id: int, with_chat: bool) -> int:
    report: list = []
    auth = await _call(report, "вход по telegram id", api.auth_telegram(
        {"id": telegram_id, "first_name": "livecheck"}, chat_id=telegram_id))
    if not auth:
        _print(report)
        return 1
    token = auth["access"]
    kw = dict(lang="ru", telegram_id=telegram_id)

    await _call(report, "баланс", api.balance(token, **kw))
    models = await _call(report, "модели", api.models(token, **kw)) or []
    await _call(report, "пакеты", api.packages(token, **kw))
    await _call(report, "пакеты: на что хватит", api.packages_value(token, **kw))
    await _call(report, "история операций", api.transactions(token, **kw))
    await _call(report, "чаты", api.sessions(token, **kw))
    video = next((m for m in models if m.get("category") == "video"), None)
    if video:
        await _call(report, f"параметры видео {video['openrouter_id']}",
                    api.video_params(token, video["openrouter_id"], **kw))
    await _call(report, "очередь видео: отказ на текстовой модели",
                api.create_job(token, {"kind": "video", "message": "x",
                                       "model": "google/gemini-2.5-flash"}, **kw),
                expect_error="bad_model")
    await _call(report, "студия: сцены", api.presets(token, **kw))
    await _call(report, "студия: цены", api.pricing(token, **kw))
    heroes = await _call(report, "студия: герои", api.characters(token, **kw)) or []
    await _call(report, "студия: мои мультфильмы", api.projects(token, **kw))
    if heroes:
        await _call(report, "студия: кадры героя", api.keyframes(token, heroes[0]["id"], **kw))
    await _call(report, "профиль", api.profile(token, **kw))
    await _call(report, "уведомления сайта", api.notifications(token, **kw))
    await _call(report, "память", api.memory(token, **kw))
    await _call(report, "переводы", api.transfers(token, **kw))
    await _call(report, "настройки уведомлений (служебная подпись)", api.set_prefs(telegram_id))
    await _call(report, "блог", api.blog("ru"))
    await _call(report, "Stars: статус несуществующего счёта",
                api.request("POST", "/api/bot/stars/status/", service=True,
                            json_body={"payload": "i1.livecheck"}), expect_error="not_found")
    await _call(report, "голос: тишина бесплатна",
                api.transcribe(token, _wav_silence(), "audio/wav", **kw))
    if with_chat:
        frames = 0
        try:
            async for frame in api.chat_stream(token, {"message": "Ответь одним словом: привет",
                                                       "model": "google/gemini-2.5-flash",
                                                       "mode": "text-chat", "lang": "ru"},
                                               lang="ru", telegram_id=telegram_id):
                frames += 1
                if frame.get("done"):
                    report.append((True, "чат (поток)", f"кадров {frames}, списано {frame.get('tokens_charged')}"))
                    break
        except ApiError as exc:
            report.append((False, "чат (поток)", f"http {exc.status} {exc.code} {exc.message[:80]}"))
    _print(report)
    return 0 if all(ok for ok, _, _ in report) else 1


def _print(report: list) -> None:
    for ok, label, detail in report:
        print(f"{OK if ok else NO} {label} — {detail}")
    bad = [label for ok, label, _ in report if not ok]
    print("\nИтог:", "всё отвечает" if not bad else f"проблемы: {', '.join(bad)}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args or not args[0].isdigit():
        print("Использование: python -m bot.livecheck <telegram_id> [--chat]")
        return 2
    return asyncio.run(run(int(args[0]), "--chat" in sys.argv))


if __name__ == "__main__":
    raise SystemExit(main())
