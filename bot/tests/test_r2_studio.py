# -*- coding: utf-8 -*-
"""Студия, второй раунд: превью, аудитория, зависший мастер, длинные разделы.

Каждый тест держит один разбор: превью из одного элемента не доходило,
детская аудитория не резала сцены, состояние «жду фото» жило вечно, ошибка
провайдера ломала сообщение, длинный код раздела убивал всю клавиатуру, а
пустая очередь досылала бессмысленное «поставил 0».
"""
import time

import pytest
from aiogram.fsm.state import State, StatesGroup

import bot.routers.studio as studio
from bot.services.api import ApiError
from bot.texts import t


# ------------------------------------------------------------- заглушки ---

class FakeBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class Sent:
    def __init__(self, kind: str, text: str, kwargs: dict):
        self.kind = kind
        self.text = text or ""
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"<{self.kind} {self.text!r}>"


class FakeMessage:
    def __init__(self, chat_id: int = 77):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.bot = FakeBot()
        self.sent: list[Sent] = []
        self.photo = None
        self.text = ""

    async def answer(self, text="", **kwargs):
        self.sent.append(Sent("text", text, kwargs))
        return self

    async def answer_photo(self, photo="", caption="", **kwargs):
        self.sent.append(Sent("photo", caption, dict(kwargs, photo=photo)))
        return self

    async def answer_video(self, video="", caption="", **kwargs):
        self.sent.append(Sent("video", caption, dict(kwargs, video=video)))
        return self

    async def answer_media_group(self, media, **kwargs):
        self.sent.append(Sent("media_group", "", {"media": media}))
        return self

    async def delete(self):
        return None

    @property
    def texts(self) -> str:
        return "\n".join(s.text for s in self.sent)

    def kinds(self, kind: str) -> list[Sent]:
        return [s for s in self.sent if s.kind == kind]

    @property
    def buttons(self) -> list:
        """Все кнопки последнего сообщения с клавиатурой."""
        for s in reversed(self.sent):
            markup = s.kwargs.get("reply_markup")
            if markup is not None:
                return [b for row in markup.inline_keyboard for b in row]
        return []


class FakeCall:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answers: list[str] = []

    @property
    def chat(self):
        return self.message.chat

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


class FakeState:
    def __init__(self):
        self.state = None
        self.cleared = False

    async def set_state(self, state):
        self.state = state

    async def get_state(self):
        # aiogram отдаёт строку «Группа:шаг», а не сам объект State.
        return getattr(self.state, "state", self.state)

    async def clear(self):
        self.cleared = True
        self.state = None


class FakeStore:
    def __init__(self, values: dict | None = None):
        self.values = dict(values or {})

    async def get(self, telegram_id, key, default=None):
        return self.values.get(key, default)

    async def set(self, telegram_id, key, value, ttl=0):
        self.values[key] = value

    async def drop(self, telegram_id, key):
        self.values.pop(key, None)


class FakeApi:
    def __init__(self, **data):
        self.data = data
        self.calls: list[tuple] = []

    async def pricing(self, token, **kw):
        return self.data.get("pricing", {"character": 4, "scene_min": 22})

    async def presets(self, token, **kw):
        return self.data.get("presets", {"categories": [], "presets": [], "popular": []})

    async def characters(self, token, **kw):
        return list(self.data.get("characters", []))

    async def keyframes(self, token, char_id, **kw):
        return self.data.get("keyframes", {})

    async def project(self, token, pk, **kw):
        self.calls.append(("project", pk))
        if "project" not in self.data:
            raise ApiError(404, code="not_found")
        return self.data["project"]

    async def create_project(self, token, character_id, title="", **kw):
        self.calls.append(("create_project", character_id))
        return self.data.get("project_new", {"id": 1, "character": {"name": "Герой"}})

    async def character_upload(self, token, name, content, **kw):
        self.calls.append(("character_upload", name))
        return self.data.get("hero", {"id": 9, "name": name})

    async def add_scene(self, token, project_id, preset_id, **kw):
        if isinstance(self.data.get("add_scene"), ApiError):
            raise self.data["add_scene"]
        return self.data.get("scene", {"preset": {"title": "Сцена"}})

    async def balance(self, token, **kw):
        return self.data.get("balance", {"balance_tokens": 0})

    async def render_scene(self, token, scene_id, **kw):
        self.calls.append(("render_scene", scene_id))
        error = self.data.get("render_error")
        if error is not None:
            raise error
        return {"id": scene_id, "preset": {"title": "Сцена"}}

    @property
    def rendered(self) -> list[int]:
        return [c[1] for c in self.calls if c[0] == "render_scene"]

    def did(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None, store_values: dict | None = None):
        api = FakeApi(**(api_data or {}))
        store = FakeStore(store_values)
        monkeypatch.setattr(studio, "api", api)
        monkeypatch.setattr(studio, "store", store)
        return api, store

    return _wire


def preset(pk, audience="adults", category="city", title=None):
    return {"id": pk, "slug": f"p{pk}", "title": title or f"Сцена {pk}", "subtitle": "",
            "preview_poster": "", "preview_video": "", "duration": 5, "credits": 30,
            "category": category, "audience": audience, "is_pick": False}


def hero(pk, image="/media/h.png"):
    return {"id": pk, "name": f"Герой {pk}", "image": image, "is_mine": False}


def scene(scene_id, status="draft", credits=30):
    return {"id": scene_id, "order": 0, "status": status,
            "preset": {"title": "Сцена", "credits": credits}}


# ------------------------------------------------- [A] превью из одного ---

class TestMediaGroupSize:
    """Telegram берёт группу из 2–10 элементов; одиночку он отвергает."""

    async def test_single_goes_as_photo(self):
        message = FakeMessage()
        await studio._send_media_group(message, ["/media/a.png"])
        assert message.kinds("photo") and not message.kinds("media_group")

    async def test_pair_still_goes_as_group(self):
        message = FakeMessage()
        await studio._send_media_group(message, ["/media/a.png", "/media/b.png"])
        groups = message.kinds("media_group")
        assert len(groups) == 1 and len(groups[0].kwargs["media"]) == 2

    async def test_more_than_ten_is_split(self):
        message = FakeMessage()
        await studio._send_media_group(message, [f"/media/{i}.png" for i in range(12)])
        groups = message.kinds("media_group")
        assert [len(g.kwargs["media"]) for g in groups] == [10, 2]

    async def test_eleventh_alone_goes_as_photo(self):
        """Хвост из одного элемента — снова не группа, а обычное фото."""
        message = FakeMessage()
        await studio._send_media_group(message, [f"/media/{i}.png" for i in range(11)])
        assert [len(g.kwargs["media"]) for g in message.kinds("media_group")] == [10]
        assert len(message.kinds("photo")) == 1

    async def test_last_page_of_heroes_shows_preview(self, wire):
        """Тот самый случай: на последней странице остался один герой."""
        wire({"characters": [hero(i) for i in range(9)]})
        message = FakeMessage()
        await studio.show_heroes(message, "tok", "ru", 1)
        assert message.kinds("photo"), "превью последней страницы пропало"


# ------------------------------------------------- [B] аудитория сцен ---

DATA = {"categories": [{"slug": "city", "title": "Город", "emoji": "🏙"}],
        "presets": [preset(1, "kids"), preset(2, "adults"), preset(3, "adults")],
        "popular": []}


class TestSceneAudience:
    """Ребёнку — детские сцены; бэкенд отдаёт audience у каждого пресета."""

    async def test_kids_do_not_see_adult_scenes(self, wire):
        wire({"presets": DATA}, {"st_audience": "kids"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert "Сцена 1" in message.texts
        assert "Сцена 2" not in message.texts and "Сцена 3" not in message.texts

    async def test_all_audience_sees_everything(self, wire):
        wire({"presets": DATA}, {"st_audience": "all"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert "Сцена 1" in message.texts and "Сцена 3" in message.texts

    async def test_universal_scene_stays_for_kids(self, wire):
        data = dict(DATA, presets=[preset(2, "adults"), preset(4, "")])
        wire({"presets": data}, {"st_audience": "kids"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert "Сцена 4" in message.texts and "Сцена 2" not in message.texts

    async def test_empty_after_filter_offers_to_switch(self, wire):
        wire({"presets": dict(DATA, presets=[preset(2, "adults")])}, {"st_audience": "kids"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert t("ru", "st_empty_audience") in message.texts
        assert any(b.callback_data.startswith("st:audoff:") for b in message.buttons)

    async def test_empty_section_says_plain_empty(self, wire):
        """Пусто не из-за фильтра — не надо винить аудиторию."""
        wire({"presets": dict(DATA, presets=[])}, {"st_audience": "kids"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert t("ru", "st_empty_scenes") in message.texts

    async def test_switch_button_drops_the_filter(self, wire):
        api, store = wire({"presets": dict(DATA, presets=[preset(2, "adults")])},
                          {"st_audience": "kids"})
        call = FakeCall("st:audoff:all", FakeMessage())
        await studio.scenes_any_audience(call, "tok", "ru")
        assert store.values["st_audience"] == "all"
        assert "Сцена 2" in call.message.texts


# --------------------------------------------- [C] мастер «жду фото» ---

class TestHeroPhotoWizard:
    """Состояние без выхода и без срока превращало случайное фото в героя."""

    async def test_text_instead_of_photo_is_answered(self, wire):
        wire({}, {"st_wizard_at": int(time.time())})
        message = FakeMessage()
        message.text = "а можно словами?"
        state = FakeState()
        await studio.hero_photo_text(message, "ru", state)
        assert t("ru", "st_wait_photo") in message.texts
        assert not state.cleared, "живой мастер сбрасывать нельзя"
        assert any(b.callback_data == "st:wx" for b in message.buttons)

    async def test_cancel_button_clears_the_state(self, wire):
        api, store = wire({}, {"st_wizard_at": int(time.time())})
        state = FakeState()
        await state.set_state(studio.StudioWizard.hero_photo)
        await studio.hero_upload_cancel(FakeCall("st:wx", FakeMessage()), "ru", state)
        assert state.cleared and "st_wizard_at" not in store.values

    async def test_cancel_does_not_break_another_wizard(self, wire):
        """Кнопка живёт в старом сообщении: она не должна рвать чужой мастер."""
        api, store = wire({}, {"st_wizard_at": int(time.time())})
        state = FakeState()
        await state.set_state(_Foreign.prompt)
        await studio.hero_upload_cancel(FakeCall("st:wx", FakeMessage()), "ru", state)
        assert not state.cleared, "чужое состояние отмена героя не трогает"
        assert state.state is _Foreign.prompt

    async def test_entry_marks_the_moment(self, wire):
        api, store = wire()
        state = FakeState()
        await studio.hero_upload(FakeCall("st:hu", FakeMessage()), "ru", state)
        assert store.values.get("st_wizard_at")
        assert state.state == studio.StudioWizard.hero_photo

    async def test_yesterday_photo_does_not_become_a_hero(self, wire, monkeypatch):
        """Главное: фото через сутки не создаёт ни героя, ни проект."""
        api, store = wire({}, {"st_wizard_at": int(time.time()) - 26 * 3600})
        monkeypatch.setattr("bot.routers.media.download", _never_called)
        message = FakeMessage()
        message.photo = [type("P", (), {"file_id": "f", "file_size": 10})()]
        state = FakeState()
        await studio.hero_photo(message, "tok", "ru", state)
        assert not api.did("character_upload") and not api.did("create_project")
        assert state.cleared and t("ru", "st_wizard_expired") in message.texts

    async def test_state_without_mark_is_treated_as_stale(self, wire, monkeypatch):
        api, store = wire({}, {})
        monkeypatch.setattr("bot.routers.media.download", _never_called)
        message = FakeMessage()
        message.photo = [type("P", (), {"file_id": "f", "file_size": 10})()]
        await studio.hero_photo(message, "tok", "ru", FakeState())
        assert not api.did("character_upload")

    async def test_fresh_photo_still_makes_a_hero(self, wire, monkeypatch):
        api, store = wire({"presets": DATA}, {"st_wizard_at": int(time.time())})
        monkeypatch.setattr("bot.routers.media.download", _gives_bytes)
        message = FakeMessage()
        message.photo = [type("P", (), {"file_id": "f", "file_size": 10})()]
        message.caption = "Кот"
        await studio.hero_photo(message, "tok", "ru", FakeState())
        assert api.did("character_upload") and api.did("create_project")
        assert "st_wizard_at" not in store.values


class _Foreign(StatesGroup):
    """Любой другой мастер бота: человек ушёл из студии и ждёт там ввода."""

    prompt = State()


async def _never_called(message, file_id, file_size, lang):
    raise AssertionError("просроченный мастер не должен качать фото")


async def _gives_bytes(message, file_id, file_size, lang):
    return b"jpeg"


# ------------------------------------------ [D] ошибка бэкенда в HTML ---

RAW = '<html><body>502 Bad Gateway</body></html>'


class TestBackendErrorEscaped:
    """Сырой ответ провайдера не должен ломать сообщение целиком."""

    async def test_add_scene_error(self, wire):
        wire({"add_scene": ApiError(502, message=RAW)}, {"st_project": 1})
        call = FakeCall("st:add:3", FakeMessage())
        await studio.add_scene(call, "tok", "ru")
        assert "&lt;html&gt;" in call.message.texts and RAW not in call.message.texts

    async def test_render_error(self, wire):
        wire({"render_error": ApiError(502, message=RAW)}, {"st_project": 1})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert "&lt;html&gt;" in call.message.texts and RAW not in call.message.texts

    async def test_empty_message_falls_back(self, wire):
        wire({"render_error": ApiError(500)}, {"st_project": 1})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert t("ru", "failed") in call.message.texts


# --------------------------------------------- [E] длинный код раздела ---

LONG = "prikljuchenija-v-dzhungljah-s-govorjashchimi-zhivotnymi-i-drakonami-dlja-detej-2026"


class TestCategoryCallbackLength:
    """Slug до 90 символов не влезает в 64 байта callback_data."""

    DATA = {"categories": [{"slug": LONG, "title": "Джунгли", "emoji": "🌴"},
                           {"slug": "city", "title": "Город", "emoji": "🏙"}],
            "presets": [preset(1, "adults", LONG), preset(2, "adults", "city")],
            "popular": []}

    async def test_every_callback_fits_the_limit(self, wire):
        wire({"presets": self.DATA})
        message = FakeMessage()
        await studio.show_categories(message, "tok", "ru")
        long_ones = [b.callback_data for b in message.buttons
                     if len(b.callback_data.encode()) > 64]
        assert not long_ones, f"Telegram отвергнет всю клавиатуру: {long_ones}"

    async def test_code_still_opens_the_right_section(self, wire):
        wire({"presets": self.DATA})
        message = FakeMessage()
        await studio.show_categories(message, "tok", "ru")
        code = next(b.callback_data for b in message.buttons
                    if b.callback_data.startswith("st:cat:c"))
        call = FakeCall(code, FakeMessage())
        await studio.scenes(call, "tok", "ru")
        assert "Сцена 1" in call.message.texts and "Сцена 2" not in call.message.texts

    async def test_page_buttons_keep_the_code(self, wire):
        data = dict(self.DATA, presets=[preset(i, "adults", LONG) for i in range(1, 11)])
        api, store = wire({"presets": data}, {"st_cats": [LONG, "city"]})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "c0", 0)
        nav = [b.callback_data for b in message.buttons if b.text == "▶"]
        assert nav and len(nav[0].encode()) <= 64

    async def test_old_button_with_raw_slug_still_works(self, wire):
        """Кнопки в уже отправленных сообщениях не должны умереть."""
        wire({"presets": self.DATA})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "city", 0)
        assert "Сцена 2" in message.texts

    async def test_forgotten_list_falls_back_to_all(self, wire):
        wire({"presets": self.DATA})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "c0", 0)
        assert "Сцена 1" in message.texts and "Сцена 2" in message.texts

    async def test_long_code_never_builds_a_broken_keyboard(self, wire):
        """Даже сырой длинный slug из старой кнопки не должен убить экран."""
        wire({"presets": self.DATA}, {"st_audience": "kids"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", LONG, 0)
        too_long = [b.callback_data for b in message.buttons
                    if len(b.callback_data.encode()) > 64]
        assert not too_long, too_long


# -------------------------------------------------- [F] пустая очередь ---

class TestRenderAllEmptyQueue:
    """После пейвола «поставил в очередь: 0» — издевательство."""

    async def test_no_zero_message_after_paywall(self, wire):
        wire({"project": {"id": 1, "scenes": [scene(10, credits=90)]},
              "balance": {"balance_tokens": 5}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert t("ru", "st_render_all_done", n=0) not in call.message.texts
        assert "5" in call.message.texts, "пейвол человек увидеть обязан"

    async def test_partial_queue_is_reported(self, wire):
        wire({"project": {"id": 1, "scenes": [scene(10, credits=30), scene(11, credits=30)]},
              "balance": {"balance_tokens": 30}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert t("ru", "st_render_all_done", n=1) in call.message.texts

    async def test_nothing_to_render_is_not_a_failure(self, wire):
        """Второе нажатие старой кнопки: снимать нечего — но это не сбой."""
        wire({"project": {"id": 1, "scenes": [scene(10, status="rendering", credits=30)]},
              "balance": {"balance_tokens": 1000}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert t("ru", "failed") not in call.message.texts
        assert t("ru", "st_render_all_done", n=0) not in call.message.texts

    async def test_silent_failure_is_still_reported(self, wire):
        """Денег хватает, но сервер отказал — молчать нельзя."""
        wire({"project": {"id": 1, "scenes": [scene(10, credits=10)]},
              "balance": {"balance_tokens": 1000},
              "render_error": ApiError(500)}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert t("ru", "failed") in call.message.texts
        assert t("ru", "st_render_all_done", n=0) not in call.message.texts
