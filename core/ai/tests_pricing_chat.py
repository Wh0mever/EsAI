# -*- coding: utf-8 -*-
"""Картинки в чате в режиме «наценка» — то, что реально спишет чат (A_FIX, раунд 2).

Клиент 4.1: наценка — для всех моделей. Картинку Nano Banana чат списывает
токенами × тариф (ai/handlers.py), и наценка доходит до неё только кнопкой
«Пересчитать тариф картинок в чате». FLUX Flex берёт деньги за каждое входное
фото — чат передаёт их число (flux_ref_count).

Курс 87.4 сома за доллар, MASTER 4990 / 6500, наценка 40 %, порог 25 %: Nano
Banana $0.039 → 7 кр, Nano Banana Pro $0.134 → 22 кр, FLUX Flex $0.06 + $0.06 за
фото → 10 / 20 / 39 кр без фото / с одним / с тремя. Сети нет.
"""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from adminapi.runtime import set_runtime
from ai import handlers, pricing
from ai.model_billing import FLUX_MAX_REFS, flux_charge_credits, flux_ref_count
from ai.models import AiProvider, GPTModels
from ai.tests_pricing_golden import TEST_CACHES, create_packages, start_price_mocks
from audit.models import AdminActionLog
from plans.models import TokenTransaction

CHAT_URL = "/api/ai/chat/"
CFG = {"api_key": "k", "base_url": "http://provider/api/v1", "referer": "r", "title": "t"}
NANO = "google/gemini-2.5-flash-image"
NANO_PRO = "google/gemini-3-pro-image"
FLEX = "black-forest-labs/flux.2-flex"
PICTURE = [{"type": "image", "url": "/media/ai_images/result.png"}]


def _image(orid, name, coeff, unit=None, ref=None, **extra):
    return GPTModels.objects.create(
        name=name, openrouter_id=orid, category="image", markup_coefficient=Decimal(coeff), max_tokens=4096,
        is_active=True, unit_cost_usd=None if unit is None else Decimal(unit),
        ref_cost_usd=None if ref is None else Decimal(ref), **extra)


def _frames(response) -> list:
    out = []
    for chunk in response.streaming_content:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        out += [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data: ")]
    return out


class _ImageStream:
    """Поток OpenRouter с одной картинкой (delta.images) и usage в конце."""

    def __init__(self, total_tokens: int):
        self.total_tokens = total_tokens

    def __iter__(self):
        image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
        yield SimpleNamespace(usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content=None,
                                                                                         images=[image]))])
        yield SimpleNamespace(usage=SimpleNamespace(prompt_tokens=self.total_tokens - 1290, completion_tokens=1290,
                                                    total_tokens=self.total_tokens), choices=[])

    def close(self):
        pass


class _Client:
    def __init__(self, stream):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **params: stream))


@override_settings(CACHES=TEST_CACHES, TOKEN_CREDIT_DIVISOR=1000)
class ChatImageChargeBase(TestCase):
    """Режим «наценка», курс закреплён, пакеты прода; покупатель с балансом 1000."""

    def setUp(self):
        cache.clear()
        start_price_mocks(self)
        create_packages()
        set_runtime(pricing.KEY_MODE, pricing.MODE_MARKUP)
        set_runtime(pricing.KEY_KGS_PER_USD, "87.4")
        pricing.invalidate_price_caches()
        AiProvider.objects.create(name="GPT", token="x")
        User = get_user_model()
        self.user = User.objects.create_user(email="buyer@example.com", password="x-12345678")
        self.user.token_balance = 1000
        self.user.is_paid = True
        self.user.save(update_fields=["token_balance", "is_paid"])
        self.staff = User.objects.create_user(email="owner@example.com", password="x-12345678", is_staff=True)
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.panel = APIClient()
        self.panel.force_authenticate(self.staff)
        for target in ("users.tasks.extract_user_memory.delay", "ai.tasks.summarize_session_context.delay"):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def balance(self) -> int:
        self.user.refresh_from_db(fields=["token_balance"])
        return self.user.token_balance

    def last_charge(self) -> int:
        return -TokenTransaction.objects.filter(user=self.user).order_by("-id").first().delta


class NanoBananaChatTests(ChatImageChargeBase):
    """Блокер 1/3 (B2): наценка доходит до картинки Nano Banana в чате через кнопку."""

    def setUp(self):
        super().setUp()
        self.nano = _image(NANO, "Nano Banana", "4", "0.039", sort_order=1)
        self.pro = _image(NANO_PRO, "Nano Banana Pro", "12", "0.134", sort_order=2)

    def draw(self, model, total_tokens: int = 1450) -> int:
        """Картинка в чате тем же путём, что у покупателя: поток → списание. Сколько списано."""
        before = self.balance()
        with patch("ai.handlers._make_openai_client", return_value=_Client(_ImageStream(total_tokens))), \
                patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("ai.handlers._save_generated_images", return_value=list(PICTURE)):
            response = self.api.post(CHAT_URL, {"message": "нарисуй кота", "model": model.openrouter_id,
                                                "stream": True}, format="json")
            frames = _frames(response)
        done = frames[-1]
        self.assertTrue(done.get("done"), done)
        self.assertFalse(done.get("error"), done)
        self.assertEqual(before - self.balance(), done["tokens_charged"])
        return done["tokens_charged"]

    def recompute(self) -> dict:
        url = reverse("adminapi:models-chat-image-recompute")
        preview = self.panel.get(url).json()
        items = [{"id": row["id"], "coefficient": row["new_coefficient"]}
                 for row in preview["rows"] if row["status"] == "ok"]
        res = self.panel.post(url, {"confirm": True, "items": items}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_button_makes_the_chat_charge_the_markup_price(self):
        # До кнопки чат берёт по старому тарифу: ⌈1450 × 4 / 1000⌉ = 6 при цене по наценке 7.
        self.assertEqual(self.draw(self.nano), 6)
        self.assertEqual(self.draw(self.pro), 18)
        body = self.recompute()
        self.assertEqual([(row["name"], row["old_coefficient"], row["new_coefficient"]) for row in body["updated"]],
                         [("Nano Banana", "4.000", "4.827"), ("Nano Banana Pro", "12.000", "15.172")])
        self.nano.refresh_from_db()
        self.pro.refresh_from_db()
        # Картинка в 1450 токенов — ровно цена по наценке, как в студиях.
        self.assertEqual(self.draw(self.nano), 7)
        self.assertEqual(self.draw(self.nano), pricing.image_credits(self.nano))
        self.assertEqual(self.draw(self.pro), 22)
        self.assertEqual(self.draw(self.pro), pricing.image_credits(self.pro))
        # Не дешевле себестоимости с порогом 25 %.
        credit = pricing.credit_usd()
        self.assertGreaterEqual(7 * credit, Decimal("0.039") * Decimal("1.25"))
        self.assertGreaterEqual(22 * credit, Decimal("0.134") * Decimal("1.25"))
        self.assertEqual([log.after for log in AdminActionLog.objects.order_by("id")],
                         [{"chat_image_tariff": "4.827"}, {"chat_image_tariff": "15.172"}])

    def test_global_and_own_markup_reach_the_chat_through_the_button(self):
        self.recompute()
        # Общая наценка 60 %: в студиях 8, чат — до кнопки по-прежнему 7.
        res = self.panel.patch(reverse("adminapi:pricing"), {"markup_pct": "60"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.nano.refresh_from_db()
        self.assertEqual(pricing.image_credits(self.nano), 8)
        self.assertEqual(self.draw(self.nano), 7)
        self.recompute()
        self.assertEqual(self.draw(self.nano), 8)
        # Своя наценка модели 100 %: ⌈0.039 × 2 / credit⌉ = 9.
        res = self.panel.patch(reverse("adminapi:models-detail", args=[self.nano.pk]), {"markup_pct": "100"},
                               format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.recompute()
        self.nano.refresh_from_db()
        self.assertEqual((pricing.image_credits(self.nano), self.draw(self.nano)), (9, 9))

    def test_rounding_down_is_what_keeps_the_price_exact(self):
        # 7 × 1000 / 1450 = 4.8275…: вниз — 4.827 → 7; вверх было бы 4.828 → ⌈7.0006⌉ = 8.
        self.assertEqual(pricing.chat_image_tariff(self.nano).coefficient, Decimal("4.827"))
        meta = handlers._augment_usage_meta_with_cost({"total_tokens": 1450, "model": NANO},
                                                      SimpleNamespace(openrouter_id=NANO, name=NANO,
                                                                      markup_coefficient=Decimal("4.828")))
        self.assertEqual(handlers._compute_charge(meta, [], "", web_search=False)[0], 8)


class FluxChatTests(ChatImageChargeBase):
    """Блокер B1: FLUX Flex в чате и число приложенных фото."""

    def setUp(self):
        super().setUp()
        self.flex = _image(FLEX, "FLUX Flex", "12", "0.06", "0.06")

    def edit(self, photos: int, *, stream: bool = True) -> int:
        """Правка FLUX Flex в чате с photos приложенными фото (поток или обычный ответ). Сколько списано."""
        before = self.balance()
        attachments = [{"type": "image", "url": f"/media/uploads/photo{n}.png"} for n in range(photos)]
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("ai.handlers._flux_generate_image", return_value=(list(PICTURE), 0.12)) as generate:
            response = self.api.post(CHAT_URL, {"message": "убери фон", "model": FLEX, "stream": stream,
                                                "attachments": attachments}, format="json")
            done = _frames(response)[-1] if stream else response.json()
        self.assertEqual(done.get("error"), None, done)
        self.assertEqual(len(generate.call_args.kwargs["references"]), photos)
        self.assertEqual(before - self.balance(), done["tokens_charged"])
        return done["tokens_charged"]

    def test_one_photo_edit_is_charged_at_cost_plus_markup(self):
        # Обычная правка — одно фото: $0.12 × 1.4 / credit → 20, не ниже себестоимости с порогом.
        self.assertEqual((self.edit(1), self.edit(1, stream=False)), (20, 20))
        self.assertEqual(pricing.image_credits(self.flex, 1), 20)
        self.assertGreaterEqual(20 * pricing.credit_usd(), Decimal("0.12") * Decimal("1.25"))

    def test_charge_follows_the_number_of_photos(self):
        for stream in (True, False):
            self.assertEqual(self.edit(0, stream=stream), 10)
            self.assertEqual(self.edit(3, stream=stream), pricing.image_credits(self.flex, 3))
            self.assertEqual(self.edit(3, stream=stream), 39)
            self.assertEqual(self.edit(FLUX_MAX_REFS, stream=stream),
                             pricing.image_credits(self.flex, FLUX_MAX_REFS))

    def test_legacy_ignores_the_photos(self):
        set_runtime(pricing.KEY_MODE, pricing.MODE_LEGACY)
        pricing.invalidate_price_caches()
        self.assertEqual((self.edit(0), self.edit(3), self.edit(3, stream=False)), (12, 12, 12))
        self.assertEqual(flux_charge_credits(self.flex, refs=3), 12)

    def test_ref_count_is_what_the_provider_gets(self):
        # flux_ref_count повторяет отбор _flux_generate_image: http(s)-URL, не больше восьми.
        refs = [f"https://esai.kg/media/{n}.png" for n in range(FLUX_MAX_REFS + 2)] + ["/media/rel.png", None, 5]
        reply = MagicMock(status_code=200)
        reply.json.return_value = {"data": [{"b64_json": "AAAA", "media_type": "image/png"}],
                                   "usage": {"cost": 0.54}}
        with patch("ai.handlers._openrouter_config", return_value=CFG), \
                patch("requests.post", return_value=reply) as post, \
                patch("ai.handlers._save_generated_images", return_value=list(PICTURE)):
            handlers._flux_generate_image(FLEX, "убери фон", references=refs)
        sent = post.call_args.kwargs["json"]["input_references"]
        self.assertEqual(len(sent), flux_ref_count(refs))
        self.assertEqual(flux_ref_count(refs), FLUX_MAX_REFS)
        self.assertEqual((flux_ref_count(None), flux_ref_count(["/media/a.png"])), (0, 0))
