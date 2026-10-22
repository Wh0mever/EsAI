# -*- coding: utf-8 -*-
"""Сквозная проверка: настоящий Dispatcher + имитатор Telegram + имитатор сервера."""
import pytest

pytestmark = pytest.mark.usefixtures("no_errors")


async def test_start_shows_menu(h):
    out = await h.say("/start")
    assert out, "на /start бот промолчал"
    text = h.texts(out)
    assert "EsAI" in text or "баланс" in text.lower()
    buttons = [b for r in out for b in r.buttons()]
    assert buttons, "у приветствия нет кнопок"


async def test_start_with_ref_reaches_auth(h):
    await h.say("/start ref_AB12CD34")
    body = h.backend.body_of("/api/bot/auth/telegram/")
    assert body.get("ref") == "AB12CD34"


async def test_plain_text_goes_to_chat(h):
    await h.say("/start")
    out = await h.say("Привет")
    assert h.backend.requests("POST", "/api/ai/chat/"), "текст не дошёл до чата"
    assert "Привет! Чем помочь?" in h.texts(out) or any("Чем помочь" in (r.text or "") for r in h.sim.sent)


async def test_special_chars_in_model_reply_do_not_break_html(h):
    h.backend.chat_reply = "Сравнение: a < b && c > d, <script>alert(1)</script> и 5<3"
    await h.say("/start")
    await h.say("сравни")
    # симулятор бросил бы TelegramBadRequest на битом HTML; сюда дошли — разметка корректна
    assert h.backend.requests("POST", "/api/ai/chat/")


@pytest.mark.parametrize("command", [
    "/help", "/balance", "/topup", "/profile", "/referral", "/promo", "/memory", "/history",
    "/model", "/lang", "/notify", "/terms", "/paysupport", "/transfer", "/new", "/cancel",
    "/image", "/video", "/studio",
])
async def test_every_command_answers(h, command):
    await h.say("/start")
    out = await h.say(command)
    assert out, f"{command}: бот промолчал"
