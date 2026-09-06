# -*- coding: utf-8 -*-
"""Студия: экранирование чужих строк, деньги и порядок сцен.

Проверяем ровно те места, где ошибка стоит человеку денег или экрана:
имя героя с «<» ломало ленту, платный герой мог не дойти, «Раньше/Позже»
не переставляли сцены, «Снять все» принимало больше, чем оплачено, а
«Переснять» ставило вторую задачу на ту же сцену.
"""
import time

import pytest

import bot.routers.studio as studio
from bot.services.api import ApiError
from bot.texts import t


# ------------------------------------------------------------- заглушки ---

class FakeBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class Sent:
    """Одно отправленное сообщение — чем оно было и с какими аргументами."""

    def __init__(self, kind: str, text: str, kwargs: dict):
        self.kind = kind
        self.text = text or ""
        self.kwargs = kwargs

    def __repr__(self) -> str:  # чтобы падение теста читалось
        return f"<{self.kind} {self.text!r}>"


class FakeMessage:
    def __init__(self, chat_id: int = 77, photo_fails: bool = False):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.bot = FakeBot()
        self.sent: list[Sent] = []
        self.photo_fails = photo_fails

    async def answer(self, text="", **kwargs):
        self.sent.append(Sent("text", text, kwargs))
        return self

    async def answer_photo(self, photo="", caption="", **kwargs):
        if self.photo_fails:
            raise RuntimeError("can't parse entities")
        self.sent.append(Sent("photo", caption, dict(kwargs, photo=photo)))
        return self

    async def answer_video(self, video="", caption="", **kwargs):
        self.sent.append(Sent("video", caption, dict(kwargs, video=video)))
        return self

    async def answer_document(self, document="", **kwargs):
        self.sent.append(Sent("document", "", dict(kwargs, document=document)))
        return self

    async def answer_media_group(self, media, **kwargs):
        self.sent.append(Sent("media_group", "", {"media": media}))
        return self

    async def delete(self):
        return None

    @property
    def texts(self) -> str:
        return "\n".join(s.text for s in self.sent)


class FakeCall:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answers: list[str] = []

    @property
    def chat(self):
        # _tid() узнаёт настоящий CallbackQuery по типу; подделке хватит чата.
        return self.message.chat

    async def answer(self, text="", **kwargs):
        self.answers.append(text)


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
    """Ровно те ручки студии, которых касаются проверяемые экраны."""

    def __init__(self, **data):
        self.data = data
        self.calls: list[tuple] = []

    async def pricing(self, token, **kw):
        return self.data.get("pricing", {"character": 4, "scene_min": 22})

    async def presets(self, token, **kw):
        return self.data.get("presets", {"categories": [], "presets": [], "popular": []})

    async def characters(self, token, **kw):
        return list(self.data.get("characters", []))

    async def character_generate(self, token, prompt, **kw):
        self.calls.append(("character_generate", prompt))
        return self.data.get("hero", {})

    async def project(self, token, pk, **kw):
        self.calls.append(("project", pk))
        return self.data.get("project", {})

    async def create_project(self, token, character_id, title="", **kw):
        return self.data.get("project", {})

    async def add_scene(self, token, project_id, preset_id, **kw):
        return self.data.get("scene", {})

    async def balance(self, token, **kw):
        self.calls.append(("balance",))
        return self.data.get("balance", {"balance_tokens": 0})

    async def render_scene(self, token, scene_id, **kw):
        self.calls.append(("render_scene", scene_id))
        return {"id": scene_id, "preset": {"title": self.data.get("render_title", "Сцена")}}

    async def patch_scene(self, token, scene_id, body, **kw):
        self.calls.append(("patch_scene", scene_id, dict(body)))
        return {"id": scene_id, "preset": {"title": "Сцена"}}

    @property
    def patches(self) -> list[tuple]:
        return [(c[1], c[2]) for c in self.calls if c[0] == "patch_scene"]

    @property
    def rendered(self) -> list[int]:
        return [c[1] for c in self.calls if c[0] == "render_scene"]


@pytest.fixture
def wire(monkeypatch):
    """Подменить сеть и память бота; вернуть (api, store)."""

    def _wire(api_data: dict | None = None, store_values: dict | None = None):
        api = FakeApi(**(api_data or {}))
        store = FakeStore(store_values)
        monkeypatch.setattr(studio, "api", api)
        monkeypatch.setattr(studio, "store", store)
        return api, store

    return _wire


def project_with(scenes, title="Мультфильм", hero="Герой"):
    return {"id": 1, "title": title, "status": "draft", "credits_spent": 0,
            "character": {"id": 5, "name": hero}, "scenes": scenes}


def scene(scene_id, order=0, status="draft", credits=30, title="Сцена"):
    return {"id": scene_id, "order": order, "status": status,
            "preset": {"title": title, "credits": credits}}


# ---------------------------------------------------------- [A] экраны ---

BREAKER = "Кот <3 & <b>жирный"
BROKEN = "Кот &lt;3 &amp; &lt;b&gt;жирный"


class TestEscaping:
    """Герой «Кот <3» не должен ломать ни один экран студии."""

    async def test_hero_list(self, wire):
        wire({"characters": [{"id": 1, "name": BREAKER, "image": "", "is_mine": True}]})
        message = FakeMessage()
        await studio.show_heroes(message, "tok", "ru", 0)
        assert BROKEN in message.texts and BREAKER not in message.texts

    async def test_project_started(self, wire):
        wire({"project": project_with([], hero=BREAKER)})
        call = FakeCall("st:h:5", FakeMessage())
        await studio.pick_hero(call, "tok", "ru")
        assert BROKEN in call.message.texts and BREAKER not in call.message.texts

    async def test_timeline_title_hero_and_scene(self, wire):
        wire({"project": project_with([scene(10, title=BREAKER)], title=BREAKER, hero=BREAKER)},
             {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        assert message.texts.count(BROKEN) == 3
        assert BREAKER not in message.texts

    async def test_scene_menu_title_and_error(self, wire):
        broken_scene = scene(10, status="failed")
        broken_scene["error"] = BREAKER
        wire({"project": project_with([broken_scene])}, {"st_project": 1})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert BREAKER not in call.message.texts
        assert "&lt;3" in call.message.texts

    async def test_delete_confirm(self, wire):
        wire({"project": project_with([], title=BREAKER)}, {"st_project": 1})
        call = FakeCall("st:del", FakeMessage())
        await studio.delete_confirm(call, "tok", "ru")
        assert BROKEN in call.message.texts and BREAKER not in call.message.texts

    async def test_added_message_escaped_but_toast_is_plain(self, wire):
        """Всплывашку Telegram не разбирает — там экранирование только мешало бы."""
        wire({"scene": {"id": 10, "preset": {"title": BREAKER}}}, {"st_project": 1})
        call = FakeCall("st:add:3", FakeMessage())
        await studio.add_scene(call, "tok", "ru")
        assert BROKEN in call.message.texts and BREAKER not in call.message.texts
        assert BREAKER in call.answers[0]

    async def test_rendering_caption(self, wire):
        wire({"render_title": BREAKER}, {"st_project": 1})
        call = FakeCall("st:r:10", FakeMessage())
        await studio.render(call, "tok", "ru")
        assert BREAKER not in call.message.texts and "&lt;3" in call.message.texts


# ------------------------------------------- [B] платный герой доезжает ---

class TestPaidHeroAlwaysArrives:
    HERO = {"id": 9, "name": BREAKER, "image": "/media/hero.png"}

    class _State:
        async def clear(self):
            return None

    @staticmethod
    def _fresh():
        """Мастер только что открыт: без отметки рисование считается забытым."""
        return {"st_wizard_at": int(time.time())}

    async def test_caption_is_escaped(self, wire):
        wire({"hero": self.HERO}, self._fresh())
        message = FakeMessage()
        message.text = "нарисуй кота"
        await studio.hero_prompt(message, "tok", "ru", self._State())
        photo = [s for s in message.sent if s.kind == "photo"]
        assert photo and BROKEN in photo[0].text and BREAKER not in photo[0].text

    async def test_fallback_when_photo_rejected(self, wire):
        """Кредиты уже списаны — молча потерять результат нельзя."""
        wire({"hero": self.HERO}, self._fresh())
        message = FakeMessage(photo_fails=True)
        message.text = "нарисуй кота"
        await studio.hero_prompt(message, "tok", "ru", self._State())
        last = message.sent[-1]
        assert last.kind == "text"
        assert "/media/hero.png" in last.text
        assert last.kwargs.get("parse_mode") is None
        # Запасной вариант идёт без разметки, поэтому имя в нём как есть.
        assert BREAKER in last.text
        assert t("ru", "failed") not in message.texts


class TestPaidHeroWizardExpires:
    """Рисование героя стоит кредиты: забытый со вчера мастер не должен
    превращать обычную фразу в списание."""

    class _State:
        def __init__(self):
            self.cleared = False

        async def clear(self):
            self.cleared = True

    async def test_stale_wizard_does_not_draw(self, wire):
        api, _ = wire({"hero": TestPaidHeroAlwaysArrives.HERO},
                      {"st_wizard_at": int(time.time()) - studio.WIZARD_TTL - 60})
        message = FakeMessage()
        message.text = "просто мысль вслух"
        state = self._State()
        await studio.hero_prompt(message, "tok", "ru", state)
        drawn = [c for c in api.calls if c[0] == "character_generate"]
        assert drawn == [], "забытый мастер нарисовал героя за деньги"
        assert state.cleared
        assert t("ru", "st_wizard_expired") in message.texts

    async def test_no_mark_means_stale(self, wire):
        api, _ = wire({"hero": TestPaidHeroAlwaysArrives.HERO}, {})
        message = FakeMessage()
        message.text = "кот в шляпе"
        await studio.hero_prompt(message, "tok", "ru", self._State())
        assert [c for c in api.calls if c[0] == "character_generate"] == []


# ------------------------------------------------ [C] порядок сцен ---

def lane_after(api, scenes) -> list[int]:
    """Какой человек увидит ленту: применяем PATCH и сортируем как бэкенд."""
    orders = {s["id"]: s["order"] for s in scenes}
    for scene_id, body in api.patches:
        orders[scene_id] = body["order"]
    return sorted(orders, key=lambda scene_id: (orders[scene_id], scene_id))


class TestMoveScene:
    async def test_down_swaps_with_neighbour(self, wire):
        api, _ = wire({"project": project_with([scene(10, 0), scene(11, 1), scene(12, 2)])},
                      {"st_project": 1})
        await studio.move_scene(FakeCall("st:dn:10", FakeMessage()), "tok", "ru")
        assert api.patches == [(10, {"order": 1}), (11, {"order": 0})]

    async def test_up_swaps_with_neighbour(self, wire):
        api, _ = wire({"project": project_with([scene(10, 0), scene(11, 1), scene(12, 2)])},
                      {"st_project": 1})
        await studio.move_scene(FakeCall("st:up:12", FakeMessage()), "tok", "ru")
        assert api.patches == [(12, {"order": 1}), (11, {"order": 2})]

    async def test_equal_orders_still_reorder(self, wire):
        """При равных order обмен значениями ничего не менял — раздаём позиции."""
        scenes = [scene(10, 0), scene(11, 0)]
        api, _ = wire({"project": project_with(scenes)}, {"st_project": 1})
        await studio.move_scene(FakeCall("st:dn:10", FakeMessage()), "tok", "ru")
        assert lane_after(api, scenes) == [11, 10]

    async def test_equal_orders_do_not_drag_the_others(self, wire):
        """Старый баг копил одинаковые order; двигаться должна ОДНА пара."""
        scenes = [scene(10, 0), scene(11, 0), scene(12, 0), scene(13, 0)]
        api, _ = wire({"project": project_with(scenes)}, {"st_project": 1})
        await studio.move_scene(FakeCall("st:dn:11", FakeMessage()), "tok", "ru")
        assert lane_after(api, scenes) == [10, 12, 11, 13]

    async def test_edges_do_nothing(self, wire):
        api, _ = wire({"project": project_with([scene(10, 0), scene(11, 1)])}, {"st_project": 1})
        await studio.move_scene(FakeCall("st:up:10", FakeMessage()), "tok", "ru")
        await studio.move_scene(FakeCall("st:dn:11", FakeMessage()), "tok", "ru")
        assert api.patches == []


# ------------------------------------- [D] «снять все» в пределах денег ---

class TestRenderAllWithinBalance:
    PENDING = [scene(10, 0, credits=30), scene(11, 1, credits=30), scene(12, 2, credits=30)]

    async def test_queues_only_what_is_paid_for(self, wire):
        api, _ = wire({"project": project_with(list(self.PENDING)),
                       "balance": {"balance_tokens": 50}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert api.rendered == [10]
        assert t("ru", "st_render_all_done", n=1) in call.message.texts

    async def test_shows_studio_paywall_with_topup(self, wire):
        api, _ = wire({"project": project_with(list(self.PENDING)),
                       "balance": {"balance_tokens": 50}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        paywall = [s for s in call.message.sent
                   if t("ru", "st_paywall_studio_all", need=90, have=50) == s.text]
        assert paywall, call.message.sent
        buttons = [b for row in paywall[0].kwargs["reply_markup"].inline_keyboard for b in row]
        assert [b.callback_data for b in buttons] == ["b:topup"]
        # 90 — цена ВСЕХ трёх сцен: пейвол одной сцены соврал бы про цену.
        assert t("ru", "st_paywall_studio", need=90, have=50) not in call.message.texts

    async def test_enough_money_queues_everything(self, wire):
        api, _ = wire({"project": project_with(list(self.PENDING)),
                       "balance": {"balance_tokens": 200}}, {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert api.rendered == [10, 11, 12]
        assert t("ru", "st_paywall_studio_all", need=90, have=200) not in call.message.texts

    async def test_unknown_balance_does_not_cut_the_queue(self, wire):
        """Сетевая осечка на балансе — не повод молча урезать очередь."""
        api, _ = wire({"project": project_with(list(self.PENDING))}, {"st_project": 1})

        async def boom(*args, **kwargs):
            raise ApiError(500)

        api.balance = boom
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert api.rendered == [10, 11, 12]


# ------------------------------------------- [E] один «Переснять» подряд ---

class TestRetryIsNotDoubled:
    @pytest.mark.parametrize("status", ["new", "keyframe", "video"])
    async def test_busy_scene_is_not_queued_again(self, wire, status):
        api, _ = wire({"project": project_with([scene(10, 0, status=status)])}, {"st_project": 1})
        call = FakeCall("st:rt:10:0", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert api.patches == []
        assert t("ru", "st_already_rendering", title="Сцена") in call.message.texts

    @pytest.mark.parametrize("status", ["ready", "failed"])
    async def test_finished_scene_can_be_retried(self, wire, status):
        api, _ = wire({"project": project_with([scene(10, 0, status=status)])}, {"st_project": 1})
        call = FakeCall("st:rt:10:1", FakeMessage())
        await studio.retry_scene(call, "tok", "ru")
        assert api.patches == [(10, {"retry": True, "new_keyframe": True})]


# ------------------------------------------------------------ переводы ---

class TestNewTextsTranslated:
    @pytest.mark.parametrize("key", ["st_hero_ready", "st_already_rendering",
                                     "st_paywall_studio_all"])
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_three_languages(self, lang, key):
        from bot.texts import TEXTS

        assert TEXTS[lang].get(key), f"{lang}.{key}"
