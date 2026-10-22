# -*- coding: utf-8 -*-
"""Стенд сам себя проверяет: он обязан ругаться на то, на что ругается Telegram."""
import pytest
from aiogram.exceptions import TelegramBadRequest

from tests.e2e.fakes import HtmlError, validate_html


def test_html_validator_rejects_lone_lt():
    with pytest.raises(HtmlError):
        validate_html("a < b")


def test_html_validator_rejects_unclosed_and_unknown():
    with pytest.raises(HtmlError):
        validate_html("<b>жирный")
    with pytest.raises(HtmlError):
        validate_html("<div>x</div>")
    with pytest.raises(HtmlError):
        validate_html("<b><i>x</b></i>")


def test_html_validator_accepts_escaped():
    assert validate_html("a &lt; b <b>x</b> <a href=\"https://x.y\">l</a>") == "a < b x l"


async def test_simulator_rejects_bad_things(h):
    with pytest.raises(TelegramBadRequest):
        await h.bot.send_message(h.uid, "1 < 2")
    with pytest.raises(TelegramBadRequest):
        await h.bot.send_message(h.uid, "x" * 4100)
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    with pytest.raises(TelegramBadRequest):
        await h.bot.send_message(h.uid, "ok", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="a", callback_data="я" * 40)]]))
    with pytest.raises(TelegramBadRequest):
        await h.bot.send_photo(h.uid, "https://x/y.png", caption="c" * 1100)


async def test_edit_same_text_is_not_modified(h):
    msg = await h.bot.send_message(h.uid, "один")
    await h.bot.edit_message_text("два", chat_id=h.uid, message_id=msg.message_id)
    with pytest.raises(TelegramBadRequest):
        await h.bot.edit_message_text("два", chat_id=h.uid, message_id=msg.message_id)
