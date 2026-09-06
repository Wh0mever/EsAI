"""Чат: главное, ради чего человек открывает бота."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.keyboards.common import answer_actions, main_menu, paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.stream import StreamRenderer
from bot.services.tg_format import split_html, to_html
from bot.texts import t

logger = logging.getLogger(__name__)
router = Router(name="chat")


async def _keep_typing(message: Message, stop: asyncio.Event) -> None:
    """Пока ждём ответ, в шапке чата видно «печатает» — иначе кажется, что бот молчит."""
    while not stop.is_set():
        try:
            await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
        except Exception:
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            continue


def _paywall_text(lang: str, code: str, payload: dict) -> str:
    if code == "premium_locked":
        return t(lang, "paywall_premium")
    if code == "daily_limit_reached":
        return t(lang, "paywall_daily")
    have = payload.get("balance_tokens", payload.get("balance", 0))
    need = payload.get("required", payload.get("required_estimate", "—"))
    return t(lang, "paywall_balance", have=have, need=need)


async def run_chat(message: Message, token: str, lang: str, text: str,
                   *, attachments: list | None = None) -> None:
    """Отправить вопрос и показать ответ по мере его появления."""
    telegram_id = message.from_user.id

    if not await store.take_busy(telegram_id):
        if not await store.warned_recently(telegram_id):
            await message.answer(t(lang, "busy"))
        return

    stop_typing = asyncio.Event()
    typing = asyncio.create_task(_keep_typing(message, stop_typing))
    renderer = StreamRenderer(message, placeholder=t(lang, "thinking"))

    model = await store.get(telegram_id, "model") or settings.default_model
    session_id = await store.get(telegram_id, "session")
    body = {
        "message": text,
        "model": model,
        "mode": "text-chat",
        "lang": lang,
    }
    if session_id:
        body["session_id"] = session_id
    if attachments:
        body["attachments"] = attachments

    sources: list = []
    reasoning = ""
    answer = ""
    done: dict = {}

    try:
        await renderer.start()
        async for frame in api.chat_stream(token, body, lang=lang, telegram_id=telegram_id):
            if frame.get("delta"):
                await renderer.push(frame["delta"])
            elif frame.get("reasoning"):
                reasoning += frame["reasoning"]
            elif frame.get("sources"):
                sources = frame["sources"] or []
            elif frame.get("image_pending"):
                await renderer.push("")
            elif frame.get("error"):
                raise ApiError(200, code=str(frame.get("error_code") or ""),
                               payload=frame, message=str(frame.get("error") or ""))
            if frame.get("done"):
                done = frame
                break
    except ApiError as exc:
        stop_typing.set()
        if exc.is_paywall:
            await renderer.fail(
                _paywall_text(lang, exc.code, exc.payload),
                reply_markup=paywall(lang, settings.site_base_url,
                                     free_model=exc.code == "premium_locked"),
            )
        elif exc.status >= 500 or exc.code == "stream_timeout":
            await renderer.fail(t(lang, "server_down"))
        else:
            await renderer.fail(t(lang, "failed"))
        return
    finally:
        stop_typing.set()
        typing.cancel()
        await store.free_busy(telegram_id)

    payload = done.get("message") or {}
    answer = payload.get("content") or renderer.buffer
    attachments_out = payload.get("attachments") or []

    session = done.get("session") or {}
    if session.get("id"):
        await store.set(telegram_id, "session", session["id"])
    if sources:
        await store.set(telegram_id, "sources", sources[:10], ttl=3600)
    if reasoning:
        await store.set(telegram_id, "reasoning", reasoning[:6000], ttl=3600)
    await store.set(telegram_id, "last_prompt", text, ttl=3600)

    footer = ""
    if done.get("tokens_charged") is not None:
        footer = t(lang, "answer_meta",
                   model=(payload.get("model") or model).split("/")[-1],
                   credits=done.get("tokens_charged", 0),
                   balance=done.get("balance_tokens", "—"))

    await renderer.finish(
        answer,
        reply_markup=answer_actions(lang, has_sources=bool(sources),
                                    has_reasoning=bool(reasoning)),
        footer=footer,
    )

    # Картинки и видео приходят вложениями — отправляем отдельными сообщениями.
    for item in attachments_out:
        url = item.get("url") or ""
        if not url:
            continue
        if not url.startswith("http"):
            url = f"{settings.site_base_url}{url}"
        try:
            if item.get("type") == "image":
                await message.answer_photo(url)
            elif item.get("type") == "video":
                await message.answer_video(url, supports_streaming=True)
        except Exception:
            logger.exception("не удалось отправить вложение %s", url)
            await message.answer(url)


@router.callback_query(F.data == "c:re")
async def retry(call: CallbackQuery, token: str, lang: str) -> None:
    prompt = await store.get(call.from_user.id, "last_prompt")
    await call.answer()
    if not prompt:
        return
    await run_chat(call.message, token, lang, prompt)


@router.callback_query(F.data == "c:cont")
async def continue_answer(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await run_chat(call.message, token, lang, "Продолжи.")


@router.callback_query(F.data == "c:src")
async def show_sources(call: CallbackQuery, lang: str) -> None:
    sources = await store.get(call.from_user.id, "sources") or []
    await call.answer()
    if not sources:
        return
    lines = []
    for index, item in enumerate(sources[:10], 1):
        if isinstance(item, dict):
            title = item.get("title") or item.get("url") or ""
            url = item.get("url") or ""
            lines.append(f"{index}. <a href=\"{url}\">{title}</a>" if url else f"{index}. {title}")
        else:
            lines.append(f"{index}. {item}")
    await call.message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data == "c:rs")
async def show_reasoning(call: CallbackQuery, lang: str) -> None:
    reasoning = await store.get(call.from_user.id, "reasoning") or ""
    await call.answer()
    if not reasoning:
        return
    for part in split_html(to_html(reasoning)):
        await call.message.answer(f"<blockquote expandable>{part}</blockquote>",
                                  parse_mode="HTML")


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, token: str, lang: str) -> None:
    from bot.keyboards.common import MENU_ACTIONS

    text = (message.text or "").strip()
    if not text:
        return
    if text in MENU_ACTIONS:  # нажатие кнопки меню разбирает другой роутер
        return
    await run_chat(message, token, lang, text)
