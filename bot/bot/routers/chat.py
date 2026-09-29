"""Чат: главное, ради чего человек открывает бота."""
from __future__ import annotations

import asyncio
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import settings
from bot.keyboards.common import paywall
from bot.services.api import ApiError, api
from bot.services.state import store
from bot.services.stream import StreamRenderer
from bot.services.tg_format import CHUNK_LIMIT, esc, esc_attr, split_html, to_html
from bot.texts import register_texts, t

logger = logging.getLogger(__name__)
router = Router(name="chat")

# Кнопка под сообщением живёт вечно, данные ответа — час. Раньше на нажатие
# истёкшей кнопки бот просто молчал, и она выглядела сломанной. Своё имя ключа
# (не из общих): register_texts общие ключи не отдаёт.
register_texts({
    "ru": {"answer_stale": "Этот ответ устарел — бот его больше не помнит. "
                           "Задайте вопрос заново.",
           # Видео-модель, выбранная для чата: отказы ядра по видео — не «не удалось».
           "chat_video_delayed": ("⏳ Видео снимается дольше обычного. Готовый ролик "
                                  "сохранится в истории этого чата на сайте esai.kg — "
                                  "кредиты спишутся только тогда, запускать заново не нужно.\n"
                                  "В боте видео удобнее заказывать через /video: готовый "
                                  "ролик придёт прямо сюда."),
           "chat_video_busy": ("🎬 Одно видео уже снимается — дождитесь его, потом "
                               "запускайте следующее. Кредиты не списаны."),
           "chat_extend_not_owned": ("Продлить можно только своё видео из этого аккаунта. "
                                     "Кредиты не списаны.")},
    "en": {"answer_stale": "This answer is outdated — the bot no longer keeps it. "
                           "Please ask again.",
           "chat_video_delayed": ("⏳ The video is taking longer than usual. The finished clip "
                                  "will be saved in this chat's history on esai.kg — credits "
                                  "will be charged only then, no need to start it again.\n"
                                  "In the bot, videos are easier to order with /video: the "
                                  "finished clip comes right here."),
           "chat_video_busy": ("🎬 A video is already being made — wait for it, then start "
                               "the next one. No credits were charged."),
           "chat_extend_not_owned": ("You can only extend your own video from this account. "
                                     "No credits were charged.")},
    "kg": {"answer_stale": "Бул жооп эскирди — бот аны эстебейт. "
                           "Суроону кайра жазыңыз.",
           "chat_video_delayed": ("⏳ Видео адаттагыдан узагыраак тартылып жатат. Даяр ролик "
                                  "esai.kg сайтындагы ушул чаттын тарыхында сакталат — "
                                  "кредиттер ошондо гана алынат, кайра баштоонун кереги жок.\n"
                                  "Ботто видеону /video аркылуу буйрутма кылуу ыңгайлуу: даяр "
                                  "ролик түз ушул жерге келет."),
           "chat_video_busy": ("🎬 Бир видео тартылып жатат — аны күтүп, анан кийинкисин "
                               "баштаңыз. Кредиттер алынган жок."),
           "chat_extend_not_owned": ("Бул аккаунттагы өзүңүздүн видеоңузду гана узарта аласыз. "
                                     "Кредиттер алынган жок.")},
})

# Коды отказов видео-ветки чата (core/ai/generation.py) → свой честный текст.
# Без этого все они показывались как «не удалось, кредиты не списаны» — а при
# video_delayed ролик потом всё равно приходил и списывался.
VIDEO_ERROR_TEXTS = {
    "video_delayed": "chat_video_delayed",
    "video_in_progress": "chat_video_busy",
    "extend_not_owned": "chat_extend_not_owned",
}


def _session_gone(exc: ApiError) -> bool:
    """Чат удалили на сайте, а его id всё ещё лежит у нас в Redis (TTL 180 дней).

    Бэкенд отвечает {"error": "Session not found"} без error_code — 400 из
    потокового чата и 404 из остальных вью, так что опознать можно только по
    тексту. Без этого человек упирается в «не удалось» на каждое сообщение.
    """
    if exc.status not in (400, 404):
        return False
    parts = (exc.message, exc.payload.get("error"), exc.payload.get("detail"))
    return "session not found" in " ".join(str(p) for p in parts if p).lower()


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


# Сколько живут источники/рассуждения/вопрос конкретного ответа.
ANSWER_TTL = 3600


def _anchor_id(renderer) -> int:
    """Чем помечаем ответ, чтобы кнопки под ним знали, к чему относятся.

    Раньше источники, рассуждения и вопрос лежали в ОДНОМ ключе на человека,
    поэтому кнопка под вчерашним ответом показывала данные свежего, а
    «Повторить» переспрашивало чужой вопрос (и списывало за него деньги).
    Берём id живого сообщения стрима: оно создаётся до генерации, значит id
    известен ещё до сборки клавиатуры, и он уникален внутри чата.
    """
    live = getattr(renderer, "live", None)
    try:
        return int(getattr(live, "message_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _answer_actions(lang: str, anchor: int, *, has_sources: bool = False,
                    has_reasoning: bool = False) -> InlineKeyboardMarkup:
    """Кнопки под ответом с привязкой к нему же.

    Собираем здесь, а не в keyboards/common: callback_data должна нести id
    ответа. Хвост «:{message_id}» — это максимум 12 байт, лимит Telegram в 64
    байта не задевает. Без anchor (стрим не создал сообщения) остаётся старый
    общий вид кнопок — их разберёт запасной путь по общему ключу.
    """
    tail = f":{anchor}" if anchor else ""
    rows = [[
        InlineKeyboardButton(text=t(lang, "btn_retry"), callback_data=f"c:re{tail}"),
        InlineKeyboardButton(text=t(lang, "btn_continue"), callback_data="c:cont"),
    ]]
    extra = []
    if has_sources:
        extra.append(InlineKeyboardButton(text=t(lang, "btn_sources"),
                                          callback_data=f"c:src{tail}"))
    if has_reasoning:
        extra.append(InlineKeyboardButton(text=t(lang, "btn_reasoning"),
                                          callback_data=f"c:rs{tail}"))
    if extra:
        rows.append(extra)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _pressed(prefix: str):
    """Фильтр «нажали эту кнопку»: и новую (с id ответа), и старую (без него)."""
    return (F.data == prefix) | F.data.startswith(f"{prefix}:")


async def _answer_data(call: CallbackQuery, key: str, shared_key: str):
    """Достать данные того ответа, под которым нажали кнопку.

    Если в callback_data есть id — читаем ТОЛЬКО ключ этого ответа: скатиться
    на общий ключ значило бы снова показать чужие источники, а для «Повторить»
    — задать другой вопрос за деньги. Общий ключ остаётся лишь для кнопок,
    отправленных прежней версией бота: у них id в callback_data нет.
    """
    data = getattr(call, "data", None) or ""
    parts = data.split(":")
    anchor = parts[2] if len(parts) > 2 else ""
    if anchor:
        return await store.get(call.from_user.id, f"{key}:{anchor}")
    return await store.get(call.from_user.id, shared_key)


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
                   remember_prompt: bool = True,
                   session_key: str = "session") -> dict | None:
    """Отправить вопрос и показать ответ по мере его появления.

    Возвращает кадр done (или None), чтобы мастера картинок могли дорисовать
    свои кнопки, не дублируя логику стрима.

    session_key — под каким ключом в памяти бота лежит чат этого режима. У
    картинок и видео он свой: иначе рисунки попадали в текстовую переписку и
    раздували её, а каждый следующий вопрос дорожал.
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
    session_id = await store.get(user_id, session_key)
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

    async def pump() -> None:
        """Один проход по потоку; кадры копим в переменных выше."""
        nonlocal sources, reasoning, done
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

    try:
        await renderer.start()
        try:
            await pump()
        except ApiError as exc:
            if not (body.get("session_id") and _session_gone(exc)):
                raise
            # Сессии больше нет: забываем её и начинаем новую. Повтор ровно
            # один — второй такой же отказ уйдёт человеку как обычная ошибка.
            # Денег первая попытка не стоила: бэкенд отвергает запрос до
            # генерации, поэтому повтор не может списать дважды.
            logger.info("чат: сессия %s пропала, начинаю новую для %s",
                        body.get("session_id"), user_id)
            await store.drop(user_id, session_key)
            body.pop("session_id", None)
            sources, reasoning, done = [], "", {}
            await pump()
    except ApiError as exc:
        stop_typing.set()
        # Причина отказа нужна в логе: человеку показываем короткий текст,
        # а разбираться потом приходится по этой строке.
        logger.warning("чат: отказ API для %s — http %s %s %s", user_id, exc.status,
                       exc.code or "-", (exc.message or "")[:200])
        if exc.is_paywall:
            await renderer.fail(
                _paywall_text(lang, exc.code, exc.payload),
                reply_markup=paywall(lang, settings.site_base_url,
                                     free_model=exc.code == "premium_locked"),
            )
        elif exc.code in VIDEO_ERROR_TEXTS:
            await renderer.fail(t(lang, VIDEO_ERROR_TEXTS[exc.code]))
        elif exc.status == 429:
            await renderer.fail(t(lang, "rate_limited"))
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
        await store.set(user_id, session_key, session["id"])

    # Всё, что понадобится кнопкам, кладём дважды: под ключом ЭТОГО ответа (по
    # нему работают новые кнопки) и под старым общим — чтобы кнопки, которые
    # прежняя версия бота уже разослала людям, не онемели.
    anchor = _anchor_id(renderer)
    if sources:
        trimmed = sources[:10]
        await store.set(user_id, "sources", trimmed, ttl=ANSWER_TTL)
        if anchor:
            await store.set(user_id, f"src:{anchor}", trimmed, ttl=ANSWER_TTL)
    if reasoning:
        short = reasoning[:6000]
        await store.set(user_id, "reasoning", short, ttl=ANSWER_TTL)
        if anchor:
            await store.set(user_id, f"rsn:{anchor}", short, ttl=ANSWER_TTL)
    if remember_prompt:
        await store.set(user_id, "last_prompt", text, ttl=ANSWER_TTL)
    if anchor:
        # Вопрос этого ответа пишем ВСЕГДА, даже когда общий ключ трогать
        # нельзя (remember_prompt=False — «Продолжить» и мастер картинок).
        # Ключ адресный, чужие ответы им не перебить, а без него «Повторить»
        # под таким ответом молчало бы: своего вопроса нет, чужой брать нельзя.
        await store.set(user_id, f"pr:{anchor}", text, ttl=ANSWER_TTL)

    footer = ""
    if done.get("tokens_charged") is not None:
        # Модель берём из meta сохранённого сообщения: там имя ТОГО, кто
        # ответил. Бэкенд умеет сам увести «нарисуй …» на image-модель, и
        # подпись с запрошенной моделью врала бы. Поля payload["model"] в
        # AiChatMessageSerializer нет вовсе, так что подпись всегда показывала
        # запрошенную модель.
        meta = payload.get("meta") or {}
        answered_by = meta.get("model") or payload.get("model") or model
        footer = t(lang, "answer_meta",
                   model=str(answered_by).split("/")[-1],
                   credits=done.get("tokens_charged", 0),
                   balance=done.get("balance_tokens", "—"))

    if attachments_out and result_markup is not None:
        # Мастер картинок: кнопки — под самой картинкой, текст сверху короткий.
        await renderer.finish(answer, footer=footer)
        await send_attachments(message, attachments_out, reply_markup=result_markup)
    else:
        await renderer.finish(
            answer,
            reply_markup=_answer_actions(lang, anchor, has_sources=bool(sources),
                                         has_reasoning=bool(reasoning)),
            footer=footer,
        )
        await send_attachments(message, attachments_out)
    return done


@router.callback_query(_pressed("c:re"))
async def retry(call: CallbackQuery, token: str, lang: str) -> None:
    prompt = await _answer_data(call, "pr", "last_prompt")
    if not prompt:
        await call.answer(t(lang, "answer_stale"), show_alert=True)
        return
    await call.answer()
    await run_chat(call.message, token, lang, prompt)


@router.callback_query(F.data == "c:cont")
async def continue_answer(call: CallbackQuery, token: str, lang: str) -> None:
    await call.answer()
    await run_chat(call.message, token, lang, t(lang, "continue_prompt"), remember_prompt=False)


@router.callback_query(_pressed("c:src"))
async def show_sources(call: CallbackQuery, lang: str) -> None:
    sources = await _answer_data(call, "src", "sources") or []
    if not sources:
        await call.answer(t(lang, "answer_stale"), show_alert=True)
        return
    await call.answer()
    lines = []
    for index, item in enumerate(sources[:10], 1):
        # Заголовок и адрес пришли из веб-поиска: «<» в заголовке или «&» в
        # ссылке — и Telegram отвергает сообщение целиком, а в callback-е
        # ошибку глушит middleware, поэтому кнопка кажется мёртвой.
        if isinstance(item, dict):
            # Заголовок режем ДО экранирования: после — можно разрубить «&amp;».
            title = str(item.get("title") or item.get("url") or "")[:200]
            url = item.get("url") or ""
            lines.append(f"{index}. <a href=\"{esc_attr(url)}\">{esc(title)}</a>"
                         if url else f"{index}. {esc(title)}")
        else:
            lines.append(f"{index}. {esc(str(item)[:200])}")
    # Тем же отказом Telegram встречает и переполнение: десять длинных
    # заголовков со ссылками в лимит сообщения не влезают. Режем по строкам —
    # так тег не рвётся пополам и ссылка остаётся ссылкой.
    chunk: list[str] = []
    size = 0
    for line in lines:
        if chunk and size + len(line) + 1 > CHUNK_LIMIT:
            await call.message.answer("\n".join(chunk), parse_mode="HTML")
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        await call.message.answer("\n".join(chunk), parse_mode="HTML")


@router.callback_query(_pressed("c:rs"))
async def show_reasoning(call: CallbackQuery, lang: str) -> None:
    reasoning = await _answer_data(call, "rsn", "reasoning") or ""
    if not reasoning:
        await call.answer(t(lang, "answer_stale"), show_alert=True)
        return
    await call.answer()
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
