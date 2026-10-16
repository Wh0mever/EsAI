# -*- coding: utf-8 -*-
"""Сборка C: у мультфильма свои модель, качество и длительность.

Выбирать их бот не даёт, но цены обязан брать с сервера под настройки
мультфильма: новые мультфильмы снимаются на Seedance Mini 480p, и цена пресета
(Seedance 2.0 720p) в библиотеке, в ленте и на кнопках была бы враньём. Сцена
без цены — «цена недоступна», а новые поля ответа бот не роняют.
"""
import pytest

import bot.routers.studio as studio
from bot.services.api import ApiError, api
from bot.texts import TEXTS, t
from tests.test_r2_studio import FakeApi, FakeCall, FakeMessage, FakeStore, preset, scene

MINI = "bytedance/seedance-2.0-mini"


# Метка ролика готовой сцены (shot_token сервера): её несут кнопки пересъёмки меню.
SHOT = "5f0c9a1e"


def dock_scene(scene_id, status="draft", credits=35, render=28, duration=5, title="Сцена"):
    """Сцена в ответе сервера сборки C: цены по настройкам мультфильма и новые поля."""
    config = {"video_model": MINI, "model_name": "Seedance Mini", "resolution": "480p",
              "duration": duration, "aspect_ratio": "16:9"}
    row = {"id": scene_id, "order": 0, "status": status,
           "preset": {"id": 3, "title": title, "credits": credits, "duration": duration,
                      "clip": "", "poster": ""},
           "render_credits": render, "duration": None, "config": config,
           "shot": None if status == "draft" else dict(config, credits_planned=credits),
           "credits_spent": 0, "keyframe": "", "video": "", "error": "",
           "shot_token": SHOT if status == "ready" else ""}
    if render is None:
        row["price_unavailable"] = True
    return row


def dock_project(scenes, **extra):
    body = {"id": 1, "title": "Мульт", "status": "draft", "aspect_ratio": "16:9",
            "character": {"id": 5, "name": "Герой"}, "credits_spent": 0,
            "video_model": MINI, "resolution": "480p", "duration": 5,
            "effective": {"video_model": MINI, "model_name": "Seedance Mini", "resolution": "480p",
                          "duration": 5, "aspect_ratio": "16:9", "model_available": True},
            "scenes": scenes}
    body.update(extra)
    return body


def library(*items):
    return {"categories": [], "popular": [], "presets": list(items)}


class DockApi(FakeApi):
    """Витрина отвечает по-разному для мультфильма и без него — как сервер сборки C."""

    async def presets(self, token, aspect_ratio="", project=None, **kw):
        self.calls.append(("presets", project, aspect_ratio))
        if project is not None:
            error = self.data.get("project_presets_error")
            if error is not None:
                raise error
            return self.data.get("project_presets", library())
        return self.data.get("presets", library())

    async def projects(self, token, **kw):
        return list(self.data.get("projects", []))

    async def cartoon_models(self, token, **kw):
        self.calls.append(("cartoon_models",))
        error = self.data.get("models_error")
        if error is not None:
            raise error
        return self.data.get("models", {})

    async def patch_scene(self, token, scene_id, body, **kw):
        self.calls.append(("patch_scene", scene_id, dict(body)))
        error = self.data.get("patch_error")
        if error is not None:
            raise error
        return {"id": scene_id, "preset": {"title": "Сцена"}}

    @property
    def presets_calls(self) -> list[tuple]:
        return [c for c in self.calls if c[0] == "presets"]


@pytest.fixture
def wire(monkeypatch):
    def _wire(api_data: dict | None = None, store_values: dict | None = None):
        fake, store = DockApi(**(api_data or {})), FakeStore(store_values)
        monkeypatch.setattr(studio, "api", fake)
        monkeypatch.setattr(studio, "store", store)
        return fake, store

    return _wire


def _texts(message) -> str:
    return message.texts + "\n" + "\n".join(b.text for b in message.buttons)


def _rows(message) -> list[list]:
    for sent in reversed(message.sent):
        markup = sent.kwargs.get("reply_markup")
        if markup is not None:
            return markup.inline_keyboard
    return []


# ------------------------------------------------------------ клиент API ---

class TestApiClient:
    @pytest.fixture
    def seen(self, monkeypatch):
        calls = []

        async def request(method, path, **kw):
            calls.append((method, path, kw.get("params"), kw.get("json_body")))
            return calls[-1][1] == "/api/cartoon/models/" and {"models": []} or {}

        monkeypatch.setattr(api, "request", request)
        return calls

    async def test_library_for_project_sends_only_the_project(self, seen):
        """Формат из памяти бота мог устареть — с project его берёт сервер."""
        await api.presets("tok", aspect_ratio="1:1", project=7, lang="ru")
        await api.presets("tok", aspect_ratio="9:16", lang="ru")
        await api.presets("tok", lang="ru")
        assert [c[2] for c in seen] == [{"project": 7}, {"aspect_ratio": "9:16"}, None]

    async def test_new_project_sends_nothing_new(self, seen):
        """Настройки нового мультфильма ставит сервер (по умолчанию из админки)."""
        await api.create_project("tok", 5, lang="ru")
        assert seen == [("POST", "/api/cartoon/projects/", None, {"character_id": 5})]

    async def test_cartoon_models(self, seen):
        assert await api.cartoon_models("tok", lang="ru") == {"models": []}
        assert seen[-1][:2] == ("GET", "/api/cartoon/models/")

    async def test_cartoon_models_non_dict_is_empty(self, monkeypatch):
        async def request(method, path, **kw):
            return None

        monkeypatch.setattr(api, "request", request)
        assert await api.cartoon_models("tok") == {}


# --------------------------------------------------- библиотека мультфильма ---

class TestLibraryForProject:
    PROJECT_PRICED = library(dict(preset(1), credits=35, duration=5))
    PRESET_PRICED = library(dict(preset(1), credits=129, duration=5))

    async def test_lines_show_project_price(self, wire):
        wire({"project_presets": self.PROJECT_PRICED, "presets": self.PRESET_PRICED}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        line = t("ru", "st_scene_line", n=1, title="Сцена 1", credits=t("ru", "st_cr", n=35),
                 duration=5, ready="")
        assert line in message.texts
        assert "129" not in message.texts

    async def test_card_shows_project_price_and_duration(self, wire):
        data = library(dict(preset(1), credits=61, duration=10))
        wire({"project_presets": data, "presets": self.PRESET_PRICED}, {"st_project": 1})
        call = FakeCall("st:sc:1", FakeMessage())
        await studio.scene_card(call, "tok", "ru")
        assert f"{t('ru', 'st_cr', n=61)} · 10 с" in call.message.texts

    async def test_null_price_in_project_library(self, wire):
        data = library(dict(preset(1), credits=None, price_unavailable=True))
        wire({"project_presets": data}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "kg", "all", 0)
        assert t("kg", "st_no_price") in message.texts and "None" not in message.texts

    async def test_categories_read_project_before_library(self, wire):
        """Формат и настройки могли смениться на сайте — сначала мультфильм."""
        project = dock_project([], aspect_ratio="1:1")
        fake, store = wire({"project": project, "project_presets": self.PROJECT_PRICED}, {"st_project": 1})
        await studio.show_categories(FakeMessage(), "tok", "ru")
        names = [c[0] for c in fake.calls]
        assert names.index("project") < names.index("presets")
        assert store.values["st_aspect"] == "1:1"
        assert store.values["st_dock"] == f"{MINI}|480p|5"
        assert f"st_presets:p1:1:1:{MINI}|480p|5" in store.values

    async def test_cache_follows_project_settings(self, wire):
        fake, store = wire({"project": dock_project([]), "project_presets": self.PROJECT_PRICED},
                           {"st_project": 1})
        await studio.show_timeline(FakeMessage(), "tok", "ru")
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        assert fake.presets_calls == [("presets", 1, "")]
        # На сайте поставили 720p: старый кэш уже не про этот мультфильм.
        fake.data["project"] = dock_project([], resolution="720p")
        await studio.show_timeline(FakeMessage(), "tok", "ru")
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        assert fake.presets_calls == [("presets", 1, ""), ("presets", 1, "")]

    async def test_deleted_project_falls_back_to_plain_library(self, wire):
        fake, _ = wire({"project_presets_error": ApiError(404, code="not_found"),
                        "presets": self.PRESET_PRICED},
                       {"st_project": 1, "st_aspect": "9:16"})
        message = FakeMessage()
        await studio.show_scenes(message, "tok", "ru", "all", 0)
        assert fake.presets_calls == [("presets", 1, ""), ("presets", None, "9:16")]
        assert "Сцена 1" in message.texts

    async def test_other_errors_still_say_server_down(self, wire):
        wire({"project": dock_project([]), "project_presets_error": ApiError(500)}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_categories(message, "tok", "ru")
        assert t("ru", "server_down") in message.texts

    async def test_no_project_keeps_preset_prices(self, wire):
        fake, _ = wire({"presets": self.PRESET_PRICED})
        await studio.show_scenes(FakeMessage(), "tok", "ru", "all", 0)
        assert fake.presets_calls == [("presets", None, "")]

    async def test_new_project_remembers_its_settings(self, wire):
        _, store = wire({"project_new": dock_project([])})
        call = FakeCall("st:h:5", FakeMessage())
        await studio.pick_hero(call, "tok", "ru")
        assert store.values["st_dock"] == f"{MINI}|480p|5"

    async def test_old_project_without_settings(self, wire):
        """Старый мультфильм (настройки null) — тот же путь, цены по пресету сервер даст сам."""
        project = {"id": 1, "title": "Старый", "aspect_ratio": "16:9", "scenes": [],
                   "character": {"name": "Герой"}}
        _, store = wire({"project": project}, {"st_project": 1})
        await studio.show_timeline(FakeMessage(), "tok", "ru")
        assert store.values["st_dock"] == "||"


# ------------------------------------------------------------------ лента ---

class TestTimelinePrices:
    async def test_unshot_rows_show_what_render_charges(self, wire):
        scenes = [dock_scene(10, "draft", credits=35, render=28),
                  dock_scene(11, "failed", credits=35, render=35),
                  dock_scene(12, "ready", credits=35, render=28)]
        wire({"project": dock_project(scenes)}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        draft = t("ru", "st_tl_line", n=1, icon="▫️", title="Сцена", status=t("ru", "st_status_draft"),
                  credits=t("ru", "st_cr", n=28))
        ready = t("ru", "st_tl_line", n=3, icon="✅", title="Сцена", status=t("ru", "st_status_ready"),
                  credits=t("ru", "st_cr", n=35))
        assert draft in message.texts and ready in message.texts
        # «Снять все» — сумма того, что спишут: 28 + 35.
        assert t("ru", "st_render_all", credits=t("ru", "st_cr", n=63)) in _texts(message)

    async def test_null_price_rows(self, wire):
        scenes = [dock_scene(10, credits=None, render=None), dock_scene(11, credits=35, render=35)]
        wire({"project": dock_project(scenes)}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "en")
        text = _texts(message)
        assert "None" not in text
        assert t("en", "st_render_all", credits=t("en", "st_no_price")) in text

    async def test_new_fields_do_not_break_screens(self, wire):
        odd = dock_scene(10, "ready", duration=12)
        odd.update({"duration": 12, "shot": {"video_model": MINI, "duration": 12, "credits_planned": 61},
                    "config": None})
        project = dock_project([odd], effective=None, adjusted=[
            {"field": "duration", "scene": 10, "from": 20, "to": 15, "message": "Сцена 1: 20 с не снять"}])
        wire({"project": project}, {"st_project": 1})
        message = FakeMessage()
        await studio.show_timeline(message, "tok", "ru")
        assert "Мульт" in message.texts
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        assert call.message.sent


# ------------------------------------------------------------- меню сцены ---

class TestSceneMenuPrices:
    async def test_render_button_uses_render_price(self, wire):
        wire({"project": dock_project([dock_scene(10, credits=35, render=28)])}, {"st_project": 1})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        labels = [b.text for b in call.message.buttons]
        assert t("ru", "st_render", credits=t("ru", "st_cr", n=28)) in labels

    async def test_retry_buttons_show_prices_on_own_rows(self, wire):
        wire({"project": dock_project([dock_scene(10, "ready", credits=35, render=28)])}, {"st_project": 1})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        rows = _rows(call.message)
        # Цена с кнопки едет в callback_data: «Переснять» сверит её на сервере.
        # Хвост — меню готовой сцены и метка её ролика: старая кнопка не переснимет второй раз.
        same = next(r for r in rows if any(b.callback_data == f"st:rt:10:0:28:r{SHOT}" for b in r))
        new = next(r for r in rows if any(b.callback_data == f"st:rt:10:1:35:r{SHOT}" for b in r))
        assert len(same) == 1 and len(new) == 1
        # С тем же кадром — только видео; новый кадр — кадр и видео.
        assert same[0].text == t("ru", "st_retry_same", credits=t("ru", "st_cr", n=28))
        assert new[0].text == t("ru", "st_retry_new", credits=t("ru", "st_cr", n=35))

    async def test_retry_without_price(self, wire):
        wire({"project": dock_project([dock_scene(10, "ready", credits=None, render=None)])},
             {"st_project": 1})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "en")
        labels = [b.text for b in call.message.buttons]
        assert t("en", "st_retry_same", credits=t("en", "st_no_price")) in labels
        assert t("en", "st_retry_new", credits=t("en", "st_no_price")) in labels
        assert not any("None" in label or "{credits}" in label for label in labels)

    async def test_old_server_without_render_credits(self, wire):
        """Старый сервер присылает только preset.credits — цена как раньше."""
        wire({"project": dock_project([scene(10, "failed", credits=30)])}, {"st_project": 1})
        call = FakeCall("st:s:10", FakeMessage())
        await studio.scene_menu(call, "tok", "ru")
        labels = [b.text for b in call.message.buttons]
        price = t("ru", "st_cr", n=30)
        assert t("ru", "st_render", credits=price) in labels
        assert t("ru", "st_retry_same", credits=price) in labels
        assert t("ru", "st_retry_new", credits=price) in labels


# ------------------------------------------------------------- снять все ---

class TestRenderAll:
    async def test_budget_uses_render_price(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, render=28), dock_scene(12, render=35)]
        fake, _ = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 60}}, {"st_project": 1})
        call = FakeCall("st:ra:91", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.rendered == [10, 11]
        assert t("ru", "st_paywall_studio_all", need=91, have=60) in call.message.texts

    async def test_unpriced_scene_is_skipped_and_explained(self, wire):
        scenes = [dock_scene(10, render=28), dock_scene(11, credits=None, render=None),
                  dock_scene(12, render=28)]
        fake, _ = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 200}},
                       {"st_project": 1})
        # Подтверждённая сумма снимаемых (56): сцену без цены пачка пропускает и объясняет.
        call = FakeCall("st:ra:56", FakeMessage())
        await studio.render_all(call, "tok", "ru")
        assert fake.rendered == [10, 12]
        assert t("ru", "st_render_all_done", n=2) in call.message.texts
        assert t("ru", "st_no_price_render") in call.message.texts

    async def test_nothing_priced(self, wire):
        scenes = [dock_scene(10, credits=None, render=None), dock_scene(11, credits=None, render=None)]
        fake, _ = wire({"project": dock_project(scenes), "balance": {"balance_tokens": 200}},
                       {"st_project": 1})
        call = FakeCall("st:ra", FakeMessage())
        await studio.render_all(call, "tok", "kg")
        assert fake.rendered == []
        assert t("kg", "st_no_price_render") in call.message.texts
        assert t("kg", "failed") not in call.message.texts


# ------------------------------------------------------- отказ «цены нет» ---

PRICE_REFUSAL = ApiError(503, code="price_unavailable", message="Цена модели сейчас недоступна, попробуйте позже")


class TestPriceRefusal:
    async def test_render_refusal_in_person_language(self, wire):
        wire({"render_error": PRICE_REFUSAL}, {"st_project": 1})
        call = FakeCall("st:r:10:35", FakeMessage())
        await studio.render(call, "tok", "en")
        assert call.message.texts == t("en", "st_no_price_render")

    async def test_retry_refusal(self, wire):
        wire({"project": dock_project([dock_scene(10, "ready")]), "patch_error": PRICE_REFUSAL},
             {"st_project": 1})
        call = FakeCall(f"st:rt:10:0:28:r{SHOT}", FakeMessage())
        await studio.retry_scene(call, "tok", "kg")
        assert call.message.texts == t("kg", "st_no_price_render")

    def test_other_errors_unchanged(self):
        assert studio._fail("ru", ApiError(400, message="<b>x")) == "&lt;b&gt;x"
        assert studio._fail("ru", ApiError(500)) == t("ru", "failed")


# -------------------------------------------------------- вход в студию ---

MODELS = {
    "defaults": {"video_model": MINI, "resolution": "480p", "duration": 5, "source": "settings"},
    "models": [{"id": MINI, "price": {"table": {"480p": {"4": 29, "5": 35}, "720p": {"5": 68}}},
                "price_from": 29}],
}
PRICING = {"character": 7, "scene_min": 129}


class TestIntroPrice:
    async def test_from_price_of_a_new_project(self, wire):
        wire({"models": MODELS, "pricing": PRICING})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "ru")
        assert message.sent[0].text == t("ru", "st_intro", character=7, scene_min=35)

    async def test_preset_fallback_keeps_old_number(self, wire):
        models = dict(MODELS, defaults=dict(MODELS["defaults"], source="preset"))
        wire({"models": models, "pricing": PRICING})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "en")
        assert message.sent[0].text == t("en", "st_intro", character=7, scene_min=129)

    async def test_unpriced_default_model_keeps_old_number(self, wire):
        models = dict(MODELS, models=[{"id": MINI, "price_from": None, "price_unavailable": True}])
        wire({"models": models, "pricing": PRICING})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "ru")
        assert message.sent[0].text == t("ru", "st_intro", character=7, scene_min=129)

    async def test_failure_is_not_remembered(self, wire):
        fake, store = wire({"models_error": ApiError(500), "models": MODELS, "pricing": PRICING})
        message = FakeMessage()
        await studio.show_intro(message, "tok", "ru")
        assert message.sent[0].text == t("ru", "st_intro", character=7, scene_min=129)
        assert "st_scene_from" not in store.values
        fake.data.pop("models_error")
        message = FakeMessage()
        await studio.show_intro(message, "tok", "ru")
        assert message.sent[0].text == t("ru", "st_intro", character=7, scene_min=35)

    async def test_answer_is_cached(self, wire):
        fake, _ = wire({"models": MODELS, "pricing": PRICING})
        await studio.show_intro(FakeMessage(), "tok", "ru")
        await studio.show_intro(FakeMessage(), "tok", "ru")
        assert [c for c in fake.calls if c[0] == "cartoon_models"] == [("cartoon_models",)]

    @pytest.mark.parametrize("models", [
        {},
        {"defaults": None, "models": None},
        {"defaults": dict(MODELS["defaults"], video_model="other"), "models": MODELS["models"]},
        {"defaults": dict(MODELS["defaults"], duration=7), "models": MODELS["models"]},
        {"defaults": MODELS["defaults"], "models": [{"id": MINI, "price": {"table": {"480p": {"5": 0}}}}]},
        {"defaults": MODELS["defaults"], "models": ["мусор", None]},
    ])
    def test_odd_answers_give_no_price(self, models):
        assert studio._default_scene_price(models) is None


# --------------------------------------------------------------- тексты ---

class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_translated(self, lang):
        assert TEXTS[lang].get("st_no_price_render")
        for key in ("st_retry_same", "st_retry_new"):
            label = t(lang, key, credits=t(lang, "st_cr", n=28))
            assert "28" in label and "{credits}" not in label
