# -*- coding: utf-8 -*-
"""Этапы 2–7: ссылки, меню, мастера, оплата — логика без сети."""
import pytest

import bot.routers.account  # noqa: F401 — регистрирует тексты профиля
from bot.keyboards.common import MENU_ACTIONS, MENU_ROWS, main_menu, more_menu, paywall
from bot.routers.billing import _value_line, balance_keyboard
from bot.routers.image import ASPECT_RATIOS, _card_keyboard, result_keyboard, wizard_prompt
from bot.routers.start import _parse_link, _parse_payload, _parse_shortcut
from bot.routers.studio import _filter_presets
from bot.routers.video import _cost, _status_label
from bot.routers.video import result_keyboard as video_result_keyboard
from bot.texts import TEXTS, t


def _buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


class TestDeepLinks:
    def test_link_code(self):
        assert _parse_link("link_abc123XYZ") == "abc123XYZ"
        assert _parse_link("link_") == ""
        assert _parse_link("ref_ABCD1234") == ""

    def test_link_is_not_referral(self):
        assert _parse_payload("link_abc123XYZ") == ("", "")

    @pytest.mark.parametrize("payload,expected", [
        ("studio", "studio"), ("studio_12", "studio"), ("topup", "topup"),
        ("video", "video"), ("chat", "chat"), ("ref_ABCD1234", ""), ("", ""),
    ])
    def test_shortcuts(self, payload, expected):
        assert _parse_shortcut(payload) == expected


class TestMenu:
    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_every_menu_button_has_action(self, lang):
        for row in main_menu(lang).keyboard:
            for button in row:
                assert button.text in MENU_ACTIONS, button.text

    def test_menu_actions_align_across_languages(self):
        """Третья кнопка второго ряда — студия на любом языке."""
        for lang, rows in MENU_ROWS.items():
            assert MENU_ACTIONS[rows[1][2]] == "studio", lang
            assert MENU_ACTIONS[rows[2][2]] == "more", lang

    @pytest.mark.parametrize("lang", ["ru", "en", "kg"])
    def test_more_menu_actions(self, lang):
        actions = [b.callback_data for b in _buttons(more_menu(lang))]
        assert "more:transfer" in actions and "more:link" in actions
        assert all(len(a.encode()) <= 64 for a in actions)

    def test_paywall_has_no_external_payment_link(self):
        """Правило Telegram: из бота нельзя вести на оплату картой."""
        for button in _buttons(paywall("ru", "https://esai.kg", free_model=True)):
            assert button.url is None
        assert _buttons(paywall("ru"))[0].callback_data == "b:topup"


class TestKeyboards:
    def test_image_card_callbacks_fit(self):
        for button in _buttons(_card_keyboard("ru", "1:1")):
            assert len(button.callback_data.encode()) <= 64
        labels = [b.text for b in _buttons(_card_keyboard("ru", "9:16"))]
        assert "• 9:16" in labels and "1:1" in labels

    def test_image_result_buttons(self):
        data = [b.callback_data for b in _buttons(result_keyboard("en"))]
        assert data == ["i:again", "i:pickar", "i:edit", "i:dl"]

    def test_video_result_callbacks_with_uid(self):
        uid = "a" * 32
        for button in _buttons(video_result_keyboard("ru", uid)):
            assert button.callback_data.endswith(uid)
            assert len(button.callback_data.encode()) <= 64

    def test_balance_keyboard(self):
        data = [b.callback_data for b in _buttons(balance_keyboard("kg"))]
        assert "b:topup" in data and "b:hist" in data

    def test_aspect_ratios_match_site(self):
        assert ASPECT_RATIOS == ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5"]


class TestVideoLogic:
    def test_cost_comes_only_from_server_table(self):
        # «Секунды × тариф» больше не цена: тариф 0 давал «1 кр» за ролик.
        assert _cost({"duration": 5, "cps": 4}) is None
        assert _cost({"duration": 5, "cps": 0}) is None
        assert _cost({"duration": 6, "res": "720p", "prices": {"720p": {"6": 27}}}) == 27

    @pytest.mark.parametrize("status,key", [
        ("pending", "vid_status_pending"), ("queued", "vid_status_pending"),
        ("processing", "vid_status_processing"), ("downloading", "vid_status_downloading"),
        ("joining", "vid_status_joining"), ("", "vid_status_processing"),
    ])
    def test_status_labels(self, status, key):
        assert _status_label("ru", status) == t("ru", key)


class TestStudioLogic:
    PRESETS = {
        "categories": [{"slug": "city", "title": "Город", "emoji": "🏙"}],
        "presets": [
            {"id": 1, "slug": "a", "category": "city", "is_pick": True},
            {"id": 2, "slug": "b", "category": "forest", "is_pick": False},
        ],
        "popular": ["b"],
    }

    def test_filters(self):
        assert [p["id"] for p in _filter_presets(self.PRESETS, "all")[1]] == [1, 2]
        assert [p["id"] for p in _filter_presets(self.PRESETS, "popular")[1]] == [2]
        assert [p["id"] for p in _filter_presets(self.PRESETS, "picks")[1]] == [1]
        title, items = _filter_presets(self.PRESETS, "city")
        assert title == "🏙 Город" and [p["id"] for p in items] == [1]
        assert _filter_presets(self.PRESETS, "nope")[1] == []


class TestBilling:
    def test_value_line(self):
        line = _value_line("ru", {"text": {"count": 200}, "video": {"count": 8}, "image": {}})
        assert "💬 200" in line and "🎬 8" in line and "🎨" not in line
        assert _value_line("ru", {}) == ""
        assert _value_line("ru", None) == ""


class TestTexts:
    def test_all_languages_have_same_keys(self):
        """Новый экран без перевода — молчаливый русский текст у англоязычного человека."""
        ru = set(TEXTS["ru"])
        for lang in ("en", "kg"):
            missing = ru - set(TEXTS[lang])
            assert not missing, f"{lang}: нет переводов {sorted(missing)[:10]}"

    def test_placeholders_match(self):
        """Один и тот же ключ должен ждать те же подстановки на всех языках."""
        import re

        pattern = re.compile(r"{(\w+)}")
        for key, value in TEXTS["ru"].items():
            if not isinstance(value, str):
                continue
            expected = set(pattern.findall(value))
            for lang in ("en", "kg"):
                other = TEXTS[lang].get(key)
                if isinstance(other, str):
                    assert set(pattern.findall(other)) == expected, f"{lang}.{key}"

    def test_terms_and_paysupport_exist(self):
        for lang in ("ru", "en", "kg"):
            assert "14" in t(lang, "terms", site="x")
            assert t(lang, "paysupport")

    def test_faq_is_list(self):
        assert isinstance(t("ru", "faq"), list) and len(t("ru", "faq")) >= 5


class TestImagePrompt:
    def test_bare_topic_becomes_single_image_request(self):
        assert wizard_prompt("ru", "Самарканд", editing=False) == "Нарисуй одну картинку, без текста: Самарканд"
        assert wizard_prompt("en", "a cat", editing=False).startswith("Draw one image")

    def test_explicit_verb_kept_as_is(self):
        assert wizard_prompt("ru", "Нарисуй кота", editing=False) == "Нарисуй кота"
        assert wizard_prompt("en", "draw a cat", editing=False) == "draw a cat"

    def test_editing_keeps_instruction(self):
        assert wizard_prompt("ru", "убери фон", editing=True) == "убери фон"
