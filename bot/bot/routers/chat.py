"""Чат: главное, ради чего человек открывает бота."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import settings
from bot.keyboards.common import answer_actions, paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.stream import StreamRenderer
from bot.services.tg_format import split_html, to_html
from bot.texts import t

logger = logging.getLogger(__name__)
router = Router(name="chat")


async def _keep_typing(message: Message, stop: asyncio.Event,
                       action: ChatAction = ChatAction.TYPING) -> None:
    """Пока ждём ответ, в шапке чата видно «печатает» — иначе кажется, что бот молчит."""
    while not stop.is_set():
        try:
            await message.bot.send_chat_action(message.chat.id, action)
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


async def show_paywall(message: Message, lang: str, exc: ApiError) -> None:
    """Один экран на все отказы по деньгам — тот же текст, что на сайте."""
    await message.answer(
        _paywall_text(lang, exc.code, exc.payload), parse_mode="HTML",
        reply_markup=paywall(lang, settings.site_base_url,
                             free_model=exc.code == "premium_locked"))


def site_url(url: str) -> str:
    if url and not url.startswith("http"):
        return f"{settings.site_base_url}{url}"
    return url


async def send_attachments(message: Message, attachments: list, *,
                           reply_markup: InlineKeyboardMarkup | None = None,
                           caption: str = "") -> None:
    """Картинки и видео приходят вложениями — отправляем отдельными сообщениями."""
    for index, item in enumerate(attachments):
        url = site_url(item.get("url") or "")
        if not url:
            continue
        last = index == len(attachments) - 1
        markup = reply_markup if last else None
        try:
            if item.get("type") == "image":
                await message.answer_photo(url, caption=caption or None, reply_markup=markup)
            elif item.get("type") == "video":
                await message.answer_video(url, supports_streaming=True,
                                           caption=caption or None, reply_markup=markup)
            else:
                await message.answer(url, reply_markup=markup)
        except Exception:
            logger.exception("не удалось отправить вложение %s", url)
            await message.answer(url, reply_markup=markup)


async def run_chat(message: Message, token: str, lang: str, text: str, *,
                   attachments: list | None = None, model: str | None = None,
                   extra: dict | None = None, placeholder: str = "",
                   result_markup: InlineKeyboardMarkup | None = None,
                   remember_prompt: bool = True) -> dict | None:
    """Отправить вопрос и показать ответ по мере его появления.

    Возвращает кадр done (или None), чтобы мастера картинок могли дорисовать
    свои кнопки, не дублируя логику стрима.
    """
    telegram_id = message.chat.id if message.chat else message.from_user.id
    user_id = message.from_user.id if not message.from_user.is_bot else telegram_id

    if not await store.take_busy(user_id):
        if not await store.warned_recently(user_id):
            await message.answer(t(lang, "busy"))
        return None

    stop_typing = asyncio.Event()
    typing = asyncio.create_task(_keep_typing(message, stop_typing))
    renderer = StreamRenderer(message, placeholder=placeholder or t(lang, "thinking"))

    model = model or await store.get(user_id, "model") or settings.default_model
    session_id = await store.get(user_id, "session")
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
    if extra:
        body.update(extra)

    sources: list = []
    reasoning = ""
    done: dict = {}

    try:
        await renderer.start()
        async for frame in api.chat_stream(token, body, lang=lang, telegram_id=user_id):
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
        return None
    finally:
        stop_typing.set()
        typing.cancel()
        await store.free_busy(user_id)

    payload = done.get("message") or {}
    answer = payload.get("content") or renderer.buffer
    attachments_out = payload.get("attachments") or []

    session = done.get("session") or {}
    if session.get("id"):
        await store.set(user_id, "session", session["id"])
    if sources:
        await store.set(user_id, "sources", sources[:10], ttl=3600)
    if reasoning:
        await store.set(user_id, "reasoning", reasoning[:6000], ttl=3600)
    if remember_prompt:
        await store.set(user_id, "last_prompt", text, ttl=3600)

    footer = ""
    if done.get("tokens_charged") is not None:
        footer = t(lang, "answer_meta",
                   model=(payload.get("model") or model).split("/")[-1],
                   credits=done.get("tokens_charged", 0),
                   balance=done.get("balance_tokens", "—"))

    if attachments_out and result_markup is not None:
        # Мастер картинок: кнопки — под самой картинкой, текст сверху короткий.
        await renderer.finish(answer, footer=footer)
        await send_attachments(message, attachments_out, reply_markup=result_markup)
    else:
        await renderer.finish(
            answer,
            reply_markup=answer_actions(lang, has_sources=bool(sources),
                                        has_reasoning=bool(reasoning)),
            footer=footer,
        )
        await send_attachments(message, attachments_out)
    return done


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
    await run_chat(call.message, token, lang, t(lang, "continue_prompt"), remember_prompt=False)


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
    prefill = await store.get(message.from_user.id, "prefill")
    if prefill:
        await store.drop(message.from_user.id, "prefill")
        if not text.lower().startswith(prefill.lower()[:12]):
            text = f"{prefill} {text}"
    await run_chat(message, token, lang, text)
