# -*- coding: utf-8 -*-
"""Логика экранов: разбор ссылок, группировка моделей, действия с файлами."""
import pytest

from bot.keyboards.common import MENU_ACTIONS, main_menu, quick_prompts
from bot.routers.models import GROUPS, _badges, _in_group, _price
from bot.routers.start import _parse_payload
from bot.texts import quick_prompt, t


class TestDeepLinks:
    """Ссылка-приглашение и промокод приходят в /start одной строкой."""

    def test_referral(self):
        assert _parse_payload("ref_AB12CD34") == ("AB12CD34", "")

    def test_promo(self):
        assert _parse_payload("promo_WELCOME") == ("", "WELCOME")

    def test_empty(self):
        assert _parse_payload("") == ("", "")

    @pytest.mark.parametrize("payload", [
        "ref_", "ref_!!!", "promo_", "ref_" + "x" * 40, "мусор", "ref AB12",
    ])
    def test_garbage_is_ignored(self, payload):
        """Чужую строку в ссылке не должно принимать за код."""
        assert _parse_payload(payload) == ("", "")


class TestModelGroups:
    def test_free_group(self):
        assert _in_group({"is_free": True}, "free")
        assert not _in_group({"is_free": False}, "free")

    def test_recommended_group(self):
        assert _in_group({"recommended": True}, "recommended")

    def test_category_group(self):
        assert _in_group({"category": "video"}, "video")
        assert not _in_group({"category": "chat"}, "video")

    def test_group_order_matches_site(self):
        keys = [k for k, _ in GROUPS]
        assert keys[:3] == ["free", "recommended", "chat"]
        assert "video" in keys and "image" in keys

    def test_badges(self):
        assert "👁" in _badges({"supports_vision": True})
        assert "🎬" in _badges({"category": "video"})
        assert "🖼" in _badges({"category": "image"})
        assert _badges({}) == ""

    def test_price_units_differ_by_kind(self):
        """У видео цена за ролик, у картинок за штуку — путать нельзя.

        У картинок «за штуку» ещё и считается по-разному: плоско по коэффициенту
        только у FLUX, у остальных — токенной формулой бэкенда (см.
        models.image_credits и tests/test_fix_image.py). У видео — только «от N»
        из таблицы цен сервера: тариф модели ценой ролика не является.
        """
        assert _price({"category": "video", "markup_coefficient": 4}) == ""
        assert _price({"category": "video", "markup_coefficient": 0}, 122) == "от 122 кр"
        assert _price({"category": "image", "markup_coefficient": 4,
                       "openrouter_id": "black-forest-labs/flux.2-pro"}) == "4 кр"
        assert _price({"category": "image", "markup_coefficient": 4,
                       "openrouter_id": "google/gemini-2.5-flash-image"}) == "≈6 кр"
        assert "1000" in _price({"category": "chat", "markup_coefficient": 5})

    def test_price_empty_without_coefficient(self):
        assert _price({"category": "chat"}) == ""


class TestTexts:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_key_screens_translated(self, lang):
        for key in ("welcome", "balance", "help", "paywall_balance", "busy", "failed"):
            assert t(lang, key), f"нет текста {key} для {lang}"

    def test_unknown_language_falls_back(self):
        assert t("fr", "busy") == t("ru", "busy")

    def test_placeholders_filled(self):
        text = t("ru", "balance", balance=100, tier="бесплатный")
        assert "100" in text and "{balance}" not in text

    def test_missing_placeholder_does_not_crash(self):
        assert t("ru", "balance")  # без аргументов — просто вернёт шаблон

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_quick_prompts_exist(self, lang):
        for key in ("article", "image", "translate", "code"):
            assert quick_prompt(lang, key)


class TestKeyboards:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_main_menu_labels_are_known_actions(self, lang):
        """Каждая кнопка меню должна что-то делать на любом языке."""
        keyboard = main_menu(lang)
        for row in keyboard.keyboard:
            for button in row:
                assert button.text in MENU_ACTIONS, f"кнопка {button.text} никуда не ведёт"

    def test_quick_prompts_have_callbacks(self):
        keyboard = quick_prompts("ru")
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        assert len(buttons) == 8
        assert all(b.callback_data.startswith("q:") for b in buttons)

    def test_callback_data_fits_telegram_limit(self):
        """Telegram обрежет callback_data длиннее 64 байт — кнопка перестанет работать."""
        keyboard = quick_prompts("ru")
        for row in keyboard.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64


class TestMediaLimits:
    def test_extensions_cover_site_formats(self):
        from bot.routers.media import DOC_EXTENSIONS, IMAGE_EXTENSIONS

        for ext in (".pdf", ".docx", ".xlsx", ".pptx", ".txt"):
            assert ext in DOC_EXTENSIONS
        assert ".jpg" in IMAGE_EXTENSIONS

    def test_limits_match_reality(self):
        """20 МБ — предел Telegram, 15 МБ — наш; их нельзя путать местами."""
        from bot.routers.media import API_LIMIT, TELEGRAM_LIMIT

        assert TELEGRAM_LIMIT == 20 * 1024 * 1024
        assert API_LIMIT == 15 * 1024 * 1024
        assert API_LIMIT < TELEGRAM_LIMIT

    def test_doc_actions_have_prompts(self):
        from bot.routers.media import DOC_ACTIONS

        for key, (label, prompt) in DOC_ACTIONS.items():
            assert label and prompt, f"действие {key} без подписи или промпта"
