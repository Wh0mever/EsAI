# -*- coding: utf-8 -*-
"""Цены в боте — только с сервера (оба режима цен, F2 «Цены и наценка»).

Видео: «от N кр» и цена карточки — из таблицы ai/video-params, тариф модели
ценой не считается; нет таблицы — нет цены и нет кнопки запуска. Тариф 0 не
значит «модели нет». Картинка FLUX: цена сервера главнее коэффициента.
"""
from types import SimpleNamespace

import pytest

from bot.routers import models, video
from bot.texts import t
from tests.test_r2_video import (FakeCall, FakeMessage, FakeState, FakeStore, _async,
                                 _button_texts, _callbacks)

SEEDANCE = {"id": 5, "openrouter_id": "bytedance/seedance-2.0", "name": "Seedance 2.0",
            "category": "video", "markup_coefficient": 0}
TABLE = {"480p": {"5": 54, "10": 108}, "720p": {"5": 122, "10": 244}}
PARAMS = {"durations": [5, 10], "default_duration": 5, "resolutions": ["480p", "720p"],
          "default_resolution": "720p", "aspect_ratios": ["16:9", "1:1"], "credits_per_second": 0,
          "price_table": TABLE,
          "price_table_by_aspect": {"1:1": {"480p": {"5": 31, "10": 62}, "720p": {"5": 69, "10": 138}},
                                    "16:9": TABLE}}


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(video, "store", fake)
    return fake


def _api(monkeypatch, params, calls: list | None = None, balance: int = 500):
    async def video_params(token, model, **kw):
        if calls is not None:
            calls.append(model)
        return dict(params)

    fake = SimpleNamespace(video_params=video_params,
                           balance=lambda *a, **kw: _async({"balance_tokens": balance}))
    monkeypatch.setattr(video, "api", fake)
    return fake


# ------------------------------------------------------------ формулы ---

class TestPriceFrom:
    def test_cheapest_cell_of_all_tables(self):
        assert models.price_from(PARAMS) == 31
        assert models.price_from({"price_table": TABLE}) == 54

    def test_nothing_from_server_is_no_price(self):
        assert models.price_from({}) is None
        assert models.price_from(None) is None
        assert models.price_from({"credits_per_second": 32, "price_table": {}}) is None
        assert models.price_from({"price_table": {"720p": {"5": 0, "10": "abc"}}}) is None


class TestModelPrices:
    def test_video_label_needs_server_price(self):
        assert models._price(SEEDANCE) == ""
        assert models._price(SEEDANCE, 31) == "от 31 кр"

    def test_flux_server_price_wins_over_coefficient(self):
        flux = {"category": "image", "openrouter_id": "black-forest-labs/flux.2-klein-4b",
                "markup_coefficient": 2, "credits_per_image": 3}
        assert models.image_credits(flux) == 3
        assert models._price(flux) == "3 кр"
        # Старый сервер без поля — legacy-формула, как и списание у него.
        assert models.image_credits({**flux, "credits_per_image": None}) == 2

    def test_token_billed_image_ignores_flux_field(self):
        nano = {"category": "image", "openrouter_id": "google/gemini-2.5-flash-image",
                "markup_coefficient": 4, "credits_per_image": 99}
        assert models.image_credits(nano) == 6

    def test_text_price_unchanged(self):
        assert models._price({"category": "chat", "markup_coefficient": 17}) == "17 кр/1000"


# ------------------------------------------------- список моделей /model ---

class TestModelsList:
    async def test_video_group_shows_price_from_table(self, store, monkeypatch):
        calls: list = []
        _api(monkeypatch, PARAMS, calls)
        monkeypatch.setattr(models, "_fetch", lambda *a, **kw: _async([SEEDANCE]))
        edited = {}

        async def edit_text(text, **kw):
            edited.update(text=text, markup=kw["reply_markup"])

        call = SimpleNamespace(data="m:g:video:0", from_user=SimpleNamespace(id=42),
                               message=SimpleNamespace(edit_text=edit_text),
                               answer=lambda *a, **kw: _async(None))

        await models.open_group(call, "tok", "ru")

        assert "Seedance 2.0 🎬 · от 31 кр" in _button_texts(edited["markup"])
        assert "за секунду" not in edited["text"]
        assert calls == ["bytedance/seedance-2.0"]

    async def test_locked_video_is_not_priced(self, store, monkeypatch):
        calls: list = []
        _api(monkeypatch, PARAMS, calls)
        prices = await models.video_prices("tok", "ru", 42, [{**SEEDANCE, "locked": True}])
        assert prices == {} and calls == []

    async def test_picked_video_model_card_shows_price(self, store, monkeypatch):
        _api(monkeypatch, PARAMS)
        monkeypatch.setattr(models, "_fetch", lambda *a, **kw: _async([SEEDANCE]))

        async def store_set(*a, **kw):
            return None

        monkeypatch.setattr(models.store, "set", store_set)
        edited = {}

        async def edit_text(text, **kw):
            edited["text"] = text

        call = SimpleNamespace(data="m:s:5", from_user=SimpleNamespace(id=42),
                               message=SimpleNamespace(edit_text=edit_text),
                               answer=lambda *a, **kw: _async(None))

        await models.pick_model(call, "tok", "ru")

        assert "Цена: от 31 кр" in edited["text"]


# ----------------------------------------------------- карточка ролика ---

class TestCard:
    async def test_card_price_from_table_and_aspect(self, store, monkeypatch):
        _api(monkeypatch, PARAMS)
        message = FakeMessage()
        draft = {"prompt": "кот", "model": SEEDANCE["openrouter_id"], "model_name": "Seedance 2.0",
                 "known": True, "duration": 5, "res": "480p", "ar": "1:1"}

        await video._show_card(message, "tok", "ru", 42, draft)

        text, kw = message.answers[0]
        assert "<b>31 кр</b>" in text
        assert "v:go" in _callbacks(kw["reply_markup"])
        assert store.data["vid_draft"]["shown_cost"] == 31

    async def test_no_table_no_launch_button(self, store, monkeypatch):
        """Режим «наценка» без себестоимости: сервер дал пустую таблицу."""
        _api(monkeypatch, {**PARAMS, "price_table": {}, "price_table_by_aspect": {}})
        message = FakeMessage()
        draft = {"prompt": "кот", "model": "m", "model_name": "M", "known": True}

        await video._show_card(message, "tok", "ru", 42, draft)

        text, kw = message.answers[0]
        callbacks = _callbacks(kw["reply_markup"])
        assert "v:go" not in callbacks and "b:topup" not in callbacks
        assert "v:rf" in callbacks
        assert "недоступна" in text
        assert store.data["vid_draft"]["shown_cost"] is None

    async def test_failed_params_are_not_cached(self, store, monkeypatch):
        from bot.services.api import ApiError

        async def boom(*a, **kw):
            raise ApiError(502, message="bad gateway")

        monkeypatch.setattr(video, "api", SimpleNamespace(video_params=boom))
        assert await video._params("tok", "ru", 42, "m") == {}
        assert "vparams:m" not in store.data

    async def test_refresh_asks_server_again(self, store, monkeypatch):
        calls: list = []
        _api(monkeypatch, PARAMS, calls)
        store.data["vparams:m"] = {"price_table": {}}
        store.data["vid_draft"] = {"prompt": "кот", "model": "m", "known": True, "duration": 5,
                                   "res": "720p", "ar": "16:9"}
        message = FakeMessage()

        await video.refresh_price(FakeCall("v:rf", message), "tok", "ru")

        assert calls == ["m"]
        assert "<b>122 кр</b>" in message.edited[0]


# ------------------------------------------------- сверка цены при запуске ---

class TestGoChecksPrice:
    @pytest.fixture
    def launched(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(video, "launch", lambda m, tok, lang, draft: (
            calls.append(dict(draft)) or _async(None)))
        return calls

    def _draft(self, store, shown):
        store.data["vid_draft"] = {"prompt": "кот", "model": "m", "model_name": "M", "known": True,
                                   "duration": 5, "res": "720p", "ar": "16:9", "shown_cost": shown}

    async def test_same_price_launches(self, store, launched, monkeypatch):
        _api(monkeypatch, PARAMS)
        self._draft(store, 122)

        await video.go(FakeCall("v:go", FakeMessage()), "tok", "ru")

        assert len(launched) == 1

    async def test_changed_price_shows_card_again(self, store, launched, monkeypatch):
        """Карточка висела с ценой 145, а сейчас ролик стоит 122 — не запускаем молча."""
        _api(monkeypatch, PARAMS)
        self._draft(store, 145)
        message = FakeMessage()

        await video.go(FakeCall("v:go", message), "tok", "ru")

        assert launched == []
        assert "<b>122 кр</b>" in message.edited[0]
        assert t("ru", "vid_price_changed") in message.edited[0]

    async def test_price_gone_does_not_launch(self, store, launched, monkeypatch):
        _api(monkeypatch, {**PARAMS, "price_table": {}, "price_table_by_aspect": {}})
        self._draft(store, 122)
        message = FakeMessage()

        await video.go(FakeCall("v:go", message), "tok", "ru")

        assert launched == []
        assert "недоступна" in message.edited[0]
        assert t("ru", "vid_price_changed") not in message.edited[0]


# ----------------------------------------- тариф 0 — не «модели нет» ---

class TestZeroTariffIsNotMissingModel:
    @pytest.fixture
    def launched(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(video, "launch", lambda m, tok, lang, draft: (
            calls.append(dict(draft)) or _async(None)))
        return calls

    async def test_pick_marks_model_known(self, store, monkeypatch):
        _api(monkeypatch, PARAMS)
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async([SEEDANCE]))

        await video.pick_model(FakeCall("v:m:0", FakeMessage()), "tok", "ru", FakeState())

        assert store.data["vid_draft"]["known"] is True
        assert "cps" not in store.data["vid_draft"]

    async def test_again_restored_seedance_shows_card(self, store, launched, monkeypatch):
        """Seedance с тарифом 0: раньше «Ещё вариант» отправлял выбирать модель."""
        _api(monkeypatch, PARAMS)
        video_api = video.api
        monkeypatch.setattr(video, "api", SimpleNamespace(
            video_params=video_api.video_params, balance=video_api.balance,
            job=lambda *a, **kw: _async({"result": {"message": {"attachments": [
                {"type": "video", "url": "/media/c.mp4", "prompt": "кот",
                 "model": SEEDANCE["openrouter_id"]}]}}})))
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async([SEEDANCE]))
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert launched == []
        text, kw = message.answers[0]
        assert text != t("ru", "vid_pick_model")
        assert "v:go" in _callbacks(kw["reply_markup"])

    async def test_again_old_live_draft_with_zero_cps_launches(self, store, launched, monkeypatch):
        """Черновик до правки: cps 0, признака known нет — модель ищем в каталоге."""
        _api(monkeypatch, PARAMS)
        monkeypatch.setattr(video, "_fetch", lambda *a, **kw: _async([SEEDANCE]))
        store.data["vjob:abc"] = {"prompt": "кот", "model": SEEDANCE["openrouter_id"], "cps": 0,
                                  "duration": 10, "res": "720p", "ar": "9:16", "job": "abc"}

        await video.again(FakeCall("v:re:abc", FakeMessage()), "tok", "ru")

        assert len(launched) == 1 and launched[0]["duration"] == 10


class TestAgainChecksPrice:
    """«Ещё вариант» живого черновика повторяет молча только по прежней цене."""

    @pytest.fixture
    def launched(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(video, "launch", lambda m, tok, lang, draft: (
            calls.append(dict(draft)) or _async(None)))
        return calls

    def _job(self, store, shown):
        store.data["vjob:abc"] = {"prompt": "кот", "model": "m", "model_name": "M", "known": True,
                                  "duration": 5, "res": "720p", "ar": "16:9", "job": "abc",
                                  "shown_cost": shown}

    async def test_same_price_repeats(self, store, launched, monkeypatch):
        _api(monkeypatch, PARAMS)
        self._job(store, 122)

        await video.again(FakeCall("v:re:abc", FakeMessage()), "tok", "ru")

        assert len(launched) == 1

    async def test_new_price_shows_card(self, store, launched, monkeypatch):
        _api(monkeypatch, PARAMS)
        self._job(store, 145)
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert launched == []
        text, kw = message.answers[0]
        assert "<b>122 кр</b>" in text and t("ru", "vid_price_changed") in text
        assert "v:go" in _callbacks(kw["reply_markup"])

    async def test_price_gone_shows_card_without_launch(self, store, launched, monkeypatch):
        _api(monkeypatch, {**PARAMS, "price_table": {}, "price_table_by_aspect": {}})
        self._job(store, 122)
        message = FakeMessage()

        await video.again(FakeCall("v:re:abc", message), "tok", "ru")

        assert launched == []
        assert "v:go" not in _callbacks(message.answers[0][1]["reply_markup"])

    async def test_extend_known_zero_tariff_shows_card(self, store, monkeypatch):
        _api(monkeypatch, PARAMS)
        store.data["vjob:abc"] = {"prompt": "кот", "model": SEEDANCE["openrouter_id"],
                                  "model_name": "Seedance 2.0", "known": True, "cps": 0,
                                  "url": "/media/c.mp4", "duration": 5, "ar": "16:9"}
        message = FakeMessage()

        await video.extend(FakeCall("v:ext:abc", message), "tok", "ru", FakeState())

        text, _ = message.answers[0]
        assert text != t("ru", "vid_pick_model")
        assert store.data["vid_draft"]["extend"] == "/media/c.mp4"
