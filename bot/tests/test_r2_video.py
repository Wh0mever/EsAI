# -*- coding: utf-8 -*-
"""Раунд 2, видео: честная цена, повтор из старого сообщения, упавший каталог,
двойная доставка ролика."""
import asyncio
from types import SimpleNamespace

import pytest

from bot.routers import video
from bot.services.api import ApiError
from bot.texts import t


class FakeStore:
    """Redis-заглушка: те же методы, что зовёт роутер."""

    def __init__(self, data: dict | None = None, token: str | None = None):
        self.data = dict(data or {})
        self.token = token

    async def get(self, chat_id, key, default=None):
        return self.data.get(key, default)

    async def set(self, chat_id, key, value, ttl=None):
        self.data[key] = value

    async def drop(self, chat_id, key):
        self.data.pop(key, None)

    async def get_token(self, chat_id):
        return self.token


class FakeBot:
    def __init__(self):
        self.edits: list[tuple] = []
        self.sent: list[str] = []
        self.videos: list[str] = []
        self.deleted = 0

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append((text, kw))

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)

    async def send_video(self, chat_id, url, **kw):
        self.videos.append(url)

    async def send_chat_action(self, chat_id, action):
        pass

    async def delete_message(self, chat_id, message_id):
        self.deleted += 1


class FakeMessage:
    def __init__(self, chat_id: int = 42):
        self.chat = SimpleNamespace(id=chat_id)
        self.bot = FakeBot()
        self.answers: list[tuple] = []
        self.edited: list[str] = []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))
        return SimpleNamespace(message_id=len(self.answers))

    async def edit_text(self, text, **kw):
        self.edited.append(text)

    async def edit_reply_markup(self, **kw):
        pass


class FakeCall:
    def __init__(self, data: str, message: FakeMessage, log: list | None = None):
        self.data = data
        self.message = message
        self.answered = 0
        # Общий журнал с заглушкой API: по нему видно, что кнопку отпустили
        # ДО сетевого запроса, а не после него.
        self.log = log if log is not None else []

    async def answer(self, *args, **kw):
        self.answered += 1
        self.log.append("answer")


class FakeState:
    def __init__(self):
        self.state = None

    async def set_state(self, state):
        self.state = state

    async def clear(self):
        self.state = None


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(video, "store", fake)
    return fake


def _async(value):
    async def coro():
        return value

    return coro()


def _raiser(exc: Exception):
    async def boom(*a, **kw):
        raise exc

    return boom


def _button_texts(markup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def _callbacks(markup) -> list[str]:
    return [getattr(b, "callback_data", "") for row in markup.inline_keyboard for b in row]


# ------------------------------------------------------ [A] честная цена ---

VEO_PARAMS = {"durations": [5, 10], "default_duration": 5, "aspect_ratios": ["16:9", "9:16"],
              "credits_per_second": 2.5, "price_table": {"720p": {"5": 13, "10": 25}}}


class TestPriceLabel:
    """Цена на кнопке — из таблицы сервера, ровно то, что спишет ядро.

    Тариф модели («кр/с») ценой ролика не является: у видео нижняя граница по
    себестоимости, а в режиме цен «наценка» тариф не участвует вовсе.
    """

    def test_label_is_cheapest_server_price(self):
        assert video._price_label("ru", VEO_PARAMS) == "от 13 кр"
        assert video._price_label("en", VEO_PARAMS) == "from 13 cr"

    def test_no_price_when_server_gave_none(self):
        assert video._price_label("ru", {}) == ""
        assert video._price_label("ru", None) == ""
        assert video._price_label("ru", {"credits_per_second": 4, "price_table": {}}) == ""

    def test_label_matches_cheapest_card(self):
        """«От N» в списке = цена карточки на самой короткой длительности."""
        label = video._price_label("ru", VEO_PARAMS)
        draft = {"duration": 5, "prices": VEO_PARAMS["price_table"]}
        assert label == f"от {video._cost(draft)} кр"

    @pytest.fixture
    def params_api(self, monkeypatch):
        monkeypatch.setattr(video, "api", SimpleNamespace(
            video_params=lambda *a, **kw: _async(dict(VEO_PARAMS))))

    async def test_model_button_shows_server_price(self, store, params_api, monkeypatch):
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async(
            [{"openrouter_id": "veo", "name": "Veo", "category": "video",
              "markup_coefficient": 2.5}]))
        message = FakeMessage()

        await video._pick_model(message, "tok", "ru", 42)

        markup = message.answers[0][1]["reply_markup"]
        assert "Veo · от 13 кр" in _button_texts(markup)

    async def test_button_has_no_dangling_separator_without_price(self, store, monkeypatch):
        """Сервер цены не дал — цену не показываем, но и разделитель не вешаем."""
        monkeypatch.setattr(video, "api", SimpleNamespace(
            video_params=lambda *a, **kw: _async({"durations": [5], "price_table": {}})))
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async(
            [{"openrouter_id": "veo", "name": "Veo", "category": "video",
              "markup_coefficient": 0, "short_label": "быстрая"}]))
        message = FakeMessage()

        await video._pick_model(message, "tok", "ru", 42)

        assert _button_texts(message.answers[0][1]["reply_markup"])[0] == "Veo · быстрая"

    async def test_prompt_invite_shows_server_price(self, store, params_api, monkeypatch):
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async(
            [{"openrouter_id": "veo", "name": "Veo", "category": "video",
              "markup_coefficient": 2.5}]))
        message = FakeMessage()

        await video.pick_model(FakeCall("v:m:0", message), "tok", "ru", FakeState())

        assert "<b>Veo</b> · от 13 кр" in message.answers[0][0]
        assert "кр/с" not in message.answers[0][0]


# ------------------------------------- [B] «Ещё вариант» из старого поста ---

def _done_job(uid: str = "abc", *, notified: bool = True) -> dict:
    return {"job_id": uid, "status": "done", "notified": notified,
            "result": {"tokens_charged": 13, "balance_tokens": 100, "message": {"attachments": [
                {"type": "video", "url": "/media/clip.mp4", "prompt": "кот в очках",
                 "model": "veo"}]}}}


class TestAgain:
    """Сообщение с кнопкой живёт вечно, черновик в Redis — 7 дней."""

    @pytest.fixture
    def api(self, monkeypatch):
        fake = SimpleNamespace(
            job=lambda *a, **kw: _async(_done_job()),
            video_params=lambda *a, **kw: _async(dict(VEO_PARAMS)),
            balance=lambda *a, **kw: _async({"balance_tokens": 500}),
        )
        monkeypatch.setattr(video, "api", fake)
        return fake

    @pytest.fixture
    def launched(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(video, "launch", lambda m, tok, lang, draft: (
            calls.append(dict(draft)) or _async(None)))
        return calls

    async def test_expired_draft_asks_to_confirm_price(self, store, api, launched, monkeypatch):
        """Параметров запуска ядро не отдаёт — нельзя молча тратить кредиты."""
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async(
            [{"openrouter_id": "veo", "name": "Veo", "category": "video",
              "markup_coefficient": 2.5}]))
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert launched == [], "платная генерация запущена без подтверждения"
        assert message.answers, "человеку не показали вообще ничего"
        text, kw = message.answers[0]
        assert "кот в очках" in text
        assert "v:go" in _callbacks(kw["reply_markup"]), "нет кнопки подтверждения запуска"
        # Черновик сохранён, чтобы кнопка «Сгенерировать» знала, что запускать.
        assert store.data["vid_draft"]["model"] == "veo"
        assert "restored" not in store.data["vid_draft"]

    async def test_retired_model_asks_to_pick_again(self, store, api, launched, monkeypatch):
        """Модели больше нет в каталоге — тариф взять неоткуда.

        Карточка посчитала бы стоимость по нулевому тарифу и предложила запуск
        за «1 кр». Как и «Продлить», отправляем человека выбирать модель.
        """
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async(
            [{"openrouter_id": "other", "name": "Other", "category": "video",
              "markup_coefficient": 3}]))
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert launched == []
        text, kw = message.answers[0]
        assert text == t("ru", "vid_pick_model")
        assert "v:go" not in _callbacks(kw["reply_markup"]), "запуск по выдуманной цене"

    async def test_live_draft_launches_with_original_params(self, store, api, launched):
        """Черновик жив — параметры известны, лишний шаг человеку не нужен."""
        store.data["vjob:abc"] = {"prompt": "кот в очках", "model": "veo", "cps": 2.5,
                                  "duration": 10, "ar": "9:16", "job": "abc"}
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert len(launched) == 1
        assert launched[0]["duration"] == 10, "повтор потерял исходную длительность"
        assert launched[0]["ar"] == "9:16"
        assert launched[0]["extend"] == ""

    async def test_unknown_job_is_reported(self, store, launched, monkeypatch):
        monkeypatch.setattr(video, "api", SimpleNamespace(
            job=_raiser(ApiError(404, message="not found"))))
        message = FakeMessage()

        await video.again(FakeCall("v:re:gone", message), "tok", "ru")

        assert launched == []
        assert [a[0] for a in message.answers] == [t("ru", "vid_no_job")]


# --------------------------------------------- [C] упавший каталог моделей ---

class TestCatalogDown:
    """ApiError каталога больше не улетает наружу молча."""

    @pytest.fixture
    def dead_catalog(self, monkeypatch):
        monkeypatch.setattr(video, "_fetch", _raiser(ApiError(500, message="boom")))

    async def test_wizard_start_reports_server_down(self, store, dead_catalog):
        message = FakeMessage()

        await video.start_wizard(message, "tok", "ru", FakeState(), prompt="кот")

        assert [a[0] for a in message.answers] == [t("ru", "server_down")]

    async def test_pick_model_answers_callback_and_reports(self, store, dead_catalog):
        message = FakeMessage()
        call = FakeCall("v:m:0", message)

        await video.pick_model(call, "tok", "ru", FakeState())

        assert call.answered == 1, "callback не закрыт — кнопка «крутится»"
        assert [a[0] for a in message.answers] == [t("ru", "server_down")]

    async def test_again_reports_server_down(self, store, dead_catalog, monkeypatch):
        """У восстановленного черновика нет цены — без каталога её не узнать."""
        monkeypatch.setattr(video, "api", SimpleNamespace(job=lambda *a, **kw: _async(_done_job())))
        launched: list = []
        monkeypatch.setattr(video, "launch", lambda *a, **kw: (
            launched.append(1) or _async(None)))
        message = FakeMessage()
        call = FakeCall("v:re:abc", message)

        await video.again(call, "tok", "ru")

        assert call.answered == 1
        assert launched == [], "запуск вслепую при недоступном каталоге"
        assert [a[0] for a in message.answers] == [t("ru", "server_down")]

    async def test_extend_answers_callback_before_api(self, store, monkeypatch):
        """Ответ на callback — до похода в API, иначе запрос протухает."""
        log: list = []

        async def job(*a, **kw):
            log.append("api")
            raise ApiError(500, message="boom")

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        message = FakeMessage()
        call = FakeCall("v:ext:abc", message, log)

        await video.extend(call, "tok", "ru", FakeState())

        assert log[0] == "answer", "кнопку отпустили только после запроса к API"
        assert [a[0] for a in message.answers] == [t("ru", "vid_no_job")]

    async def test_share_answers_callback_before_api(self, store, monkeypatch):
        log: list = []

        async def job(*a, **kw):
            log.append("api")
            raise ApiError(500, message="boom")

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        message = FakeMessage()
        call = FakeCall("v:sh:abc", message, log)

        await video.share(call, "tok", "ru")

        assert log[0] == "answer"
        assert [a[0] for a in message.answers] == [t("ru", "vid_no_job")]

    async def test_again_answers_callback_before_api(self, store, monkeypatch):
        log: list = []

        async def job(*a, **kw):
            log.append("api")
            raise ApiError(500, message="boom")

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        message = FakeMessage()
        call = FakeCall("v:re:abc", message, log)

        await video.again(call, "tok", "ru")

        assert log[0] == "answer"


# ------------------------------------------- [D] двойная доставка ролика ---

class TestDoubleDelivery:
    """Ядро ставит done ДО отправки, а отметку — ПОСЛЕ ответа Telegram."""

    @pytest.fixture(autouse=True)
    def _fast(self, monkeypatch):
        monkeypatch.setattr(video, "POLL_INTERVAL", 0)
        monkeypatch.setattr(video, "POLL_MAX_SECONDS", 5)
        monkeypatch.setattr(video, "NOTIFY_GRACE", 0)

    def _api(self, monkeypatch, answers: list, calls: list):
        async def job(token, uid, **kw):
            calls.append(token)
            return answers[min(len(calls) - 1, len(answers) - 1)]

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))

    async def test_slow_core_send_is_not_duplicated(self, store, monkeypatch):
        """Большой ролик Telegram качает минутами — отметка приходит с запозданием."""
        calls: list = []
        self._api(monkeypatch, [_done_job(notified=False), _done_job(notified=False),
                                _done_job(notified=True)], calls)
        monkeypatch.setattr(video, "NOTIFY_ATTEMPTS", 3)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.videos == [], "человек получил вторую копию ролика"
        assert bot.sent == []
        assert len(calls) == 4, "задача перечитана не столько раз, сколько ждали"

    async def test_withdrawn_mark_brings_delivery_back_to_bot(self, store, monkeypatch):
        """Ядро пометило доставку, но Telegram отказал — и отметка снялась.

        Ядро ставит отметку ДО обращения к Telegram и снимает её при отказе
        (core/ai/tasks.py::_notify_job_result). Отметку бот видит почти всегда:
        она появляется через миллисекунды после статуса done, а отказ Telegram —
        только через десятки секунд. Выйти по первой отметке значит оставить
        человека без ролика, за который уже списаны кредиты.
        """
        calls: list = []
        self._api(monkeypatch, [_done_job(notified=True), _done_job(notified=True),
                                _done_job(notified=False)], calls)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert len(bot.videos) == 1, "ядро не отправило, и бот не подстраховал — ролик пропал"
        assert len(calls) < video.NOTIFY_ATTEMPTS, "снятую отметку заметили не сразу"

    async def test_kept_mark_never_leads_to_second_copy(self, store, monkeypatch):
        """Отметка держится всё окно — ядро доставило, слать нечего."""
        calls: list = []
        self._api(monkeypatch, [_done_job(notified=True)], calls)
        monkeypatch.setattr(video, "NOTIFY_ATTEMPTS", 3)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.videos == [] and bot.sent == []

    async def test_core_silent_gets_backstop(self, store, monkeypatch):
        """Ядро так и не отчиталось за всё окно — шлём сами, но ровно один раз."""
        calls: list = []
        self._api(monkeypatch, [_done_job(notified=False)], calls)
        monkeypatch.setattr(video, "NOTIFY_ATTEMPTS", 3)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert len(bot.videos) == 1 and bot.videos[0].endswith("/media/clip.mp4")
        assert len(calls) == 4, "перед своей отправкой задачу перечитали не все разы"

    async def test_nobody_else_sends_delivers_at_once(self, store, monkeypatch):
        """notify != telegram — ядро слать не собиралось, ждать нечего."""
        calls: list = []
        self._api(monkeypatch, [_done_job(notified=False)], calls)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru", notify="")

        assert len(bot.videos) == 1
        assert len(calls) == 1, "лишнее ожидание отметки, которую никто не поставит"

    async def test_network_hiccup_is_not_a_reason_to_send(self, store, monkeypatch):
        """401/5xx при перечитывании не значит, что ядро не отправило ролик."""
        calls: list = []

        async def job(token, uid, **kw):
            calls.append(token)
            if len(calls) == 1:
                return _done_job(notified=False)
            if len(calls) == 2:
                raise ApiError(500, message="boom")
            return _done_job(notified=True)

        monkeypatch.setattr(video, "api", SimpleNamespace(job=job))
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.videos == [] and bot.sent == []

    async def test_canceled_job_is_not_delivered(self, store, monkeypatch):
        calls: list = []
        self._api(monkeypatch, [{"job_id": "abc", "status": "canceled"}], calls)
        bot = FakeBot()

        await video._watch(bot, 42, 7, "abc", "tok", "ru")

        assert bot.videos == []
        assert bot.sent == [t("ru", "vid_canceled")]

    async def test_launch_tells_watcher_who_delivers(self, store, monkeypatch):
        seen: dict = {}

        def watch(*args, **kw):
            seen.update(kw)
            return _async(None)

        monkeypatch.setattr(video, "_watch", watch)
        monkeypatch.setattr(video, "api", SimpleNamespace(
            create_job=lambda *a, **kw: _async({"job_id": "abc"})))
        message = FakeMessage()

        await video.launch(message, "tok", "ru", {"prompt": "кот", "model": "veo", "duration": 5})
        await asyncio.sleep(0)  # даём фоновой заглушке завершиться

        assert seen.get("notify") == "telegram"
