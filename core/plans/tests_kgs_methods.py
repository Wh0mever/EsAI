# -*- coding: utf-8 -*-
"""Выбор способа оплаты в сомах до ухода на FreedomPay.

Меняются только параметры init_payment. Главное, что здесь проверяется:
без способа запрос к FreedomPay остаётся прежним, а ссылка, созданная под
один способ, не достаётся нажавшему на другой.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from adminapi.runtime import get_runtime, set_runtime
from adminapi.serializers import PaymentAdminSerializer
from payments import kgs_methods
from payments.freedompay import make_api_signature
from payments.models import FunnelEvent, Payment
from plans.models import ExitDiscountOffer, TokenPackage

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "plans-kgs-methods-tests"}}

APP_PARAMS = {
    "mbank": "MBANKKGS",
    "odengi": "ODENGIKGSV2",
    "balance": "BEELINEKGS",
    "megapay": "MEGAPAYKGS",
}
DEFAULT_LIST = [
    {"key": "mbank", "kind": "app"}, {"key": "odengi", "kind": "app"},
    {"key": "megapay", "kind": "app"},
    {"key": "card", "kind": "card"},
]


def _fp_ok(*args, **kwargs):
    resp = MagicMock(status_code=200)
    order_id = (kwargs.get("data") or {}).get("pg_order_id")
    resp.json.return_value = {"pg_status": "ok", "pg_redirect_url": f"https://pay.example/{order_id}"}
    return resp


@override_settings(CACHES=TEST_CACHES, FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN="secret",
                   FREEDOM_PAY_INIT_PAYMENT_URL="https://fp.example/init_payment.php",
                   YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY="", KGS_METHODS_MODE="on")
class KgsMethodsTestCase(TestCase):
    def setUp(self):
        # Настройки из админки кэшируются на 30 с, а кэш между тестами общий.
        cache.clear()
        self.addCleanup(cache.clear)
        users = get_user_model().objects
        self.user = users.create_user(email="buyer@example.com", password="x")
        self.staff = users.create_user(email="staff@example.com", password="x", is_staff=True)
        self.pkg = TokenPackage.objects.create(name="A", tokens=500, price=Decimal("490"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.staff_client = APIClient()
        self.staff_client.force_authenticate(self.staff)

    def _buy(self, method=None, client=None, **extra):
        body = {"package_id": self.pkg.id, **extra}
        if method is not None:
            body["method"] = method
        return (client or self.client).post("/api/plans/purchase/", body, format="json")

    def _rate(self, client=None):
        # Подсказка валюты ходит во внешний гео-сервис — в тестах его нет.
        with patch("plans.geo.detect_country_code", return_value=None):
            return (client or self.client).get("/api/plans/currency-rate/").data

    def _assert_signed(self, sent):
        unsigned = {k: v for k, v in sent.items() if k != "pg_sig"}
        self.assertEqual(sent["pg_sig"], make_api_signature("init_payment", unsigned, "secret"))


class PurchasePayloadTests(KgsMethodsTestCase):
    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_without_method_request_is_the_old_one(self, post):
        r = self._buy()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.data), {"redirect_url", "order_id", "amount", "currency", "package_id"})

        sent = post.call_args.kwargs["data"]
        self.assertEqual(set(sent), {
            "pg_merchant_id", "pg_amount", "pg_currency", "pg_order_id", "pg_user_id",
            "pg_description", "pg_language", "pg_user_contact_email", "pg_salt",
            "pg_success_url", "pg_failure_url", "pg_result_url", "pg_request_method",
            "pg_testing_mode", "pg_sig"})
        self._assert_signed(sent)

        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertNotIn("pay_method", payment.request)
        self.assertEqual(set(payment.request), {"token_purchase", "return_to"})
        # Пустая строка и пробелы — то же самое, что способа нет.
        self.assertTrue(self._buy("  ").data.get("resumed"))
        self.assertEqual(Payment.objects.count(), 1)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_bank_app_sends_its_payment_system(self, post):
        # Balance.kg у магазина не подключён и по умолчанию выключен: без
        # галочки в админке кнопки нет и запрос с ним отклоняется.
        self.assertEqual(self._buy("balance").status_code, 400)
        post.assert_not_called()
        set_runtime("kgs_methods_enabled", "mbank,odengi,balance,megapay,card")
        for method, code in APP_PARAMS.items():
            with self.subTest(method=method):
                r = self._buy(method)
                self.assertEqual(r.status_code, 200)
                self.assertEqual(set(r.data),
                                 {"redirect_url", "order_id", "amount", "currency", "package_id"})
                sent = post.call_args.kwargs["data"]
                self.assertEqual(sent["pg_payment_system"], code)
                self.assertNotIn("pg_payment_method", sent)
                # Ссылка в приложение банка живёт не сутки, но дольше получаса,
                # в течение которого к ней возвращают.
                self.assertEqual(sent["pg_lifetime"], "2700")
                self._assert_signed(sent)

                payment = Payment.objects.get(order_id=r.data["order_id"])
                self.assertEqual(payment.request["pay_method"], method)
                self.assertEqual(payment.request["token_purchase"]["payload"], sent)
                self.assertEqual(payment.provider, "freedompay")
                self.assertEqual(r.data["amount"], "490.00")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_card_sends_bankcard_and_keeps_default_lifetime(self, post):
        r = self._buy(" Card ")
        self.assertEqual(r.status_code, 200)
        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["pg_payment_method"], "bankcard")
        self.assertNotIn("pg_payment_system", sent)
        self.assertNotIn("pg_lifetime", sent)
        self._assert_signed(sent)
        self.assertEqual(Payment.objects.get(order_id=r.data["order_id"]).request["pay_method"], "card")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_unknown_method_creates_nothing(self, post):
        for method in ("paypal", "MBANKKGS", "elqr", ["mbank"]):
            with self.subTest(method=method):
                r = self._buy(method)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.data, {"detail": "method_unavailable"})
        self.assertEqual(Payment.objects.count(), 0)
        post.assert_not_called()

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_method_is_ignored_for_roubles(self, post):
        # Рубли обслуживает ЮKassa: способ сомовой оплаты там не при чём, и
        # даже неизвестный не должен превращаться в «способ недоступен».
        r = self._buy("paypal", pay_currency="RUB")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.data, {"detail": "yookassa_config_missing"})
        post.assert_not_called()


class AvailabilityTests(KgsMethodsTestCase):
    def test_mode_on_shows_methods_to_everyone(self):
        self.assertEqual(self._rate()["kgs_methods"], DEFAULT_LIST)
        self.assertEqual(self._rate(APIClient())["kgs_methods"], DEFAULT_LIST)
        self.assertEqual(kgs_methods.available_for(None), DEFAULT_LIST)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_mode_off_hides_methods_even_from_staff(self, post):
        set_runtime("kgs_methods_mode", "off")
        self.assertEqual(self._rate(self.staff_client)["kgs_methods"], [])
        r = self._buy("mbank", client=self.staff_client)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data, {"detail": "method_unavailable"})
        self.assertEqual(Payment.objects.count(), 0)
        # Оплата без способа при этом работает как работала.
        self.assertEqual(self._buy(client=self.staff_client).status_code, 200)

    @override_settings(KGS_METHODS_MODE="staff")
    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_mode_staff_opens_methods_to_staff_only(self, post):
        self.assertEqual(self._rate()["kgs_methods"], [])
        self.assertEqual(self._rate(APIClient())["kgs_methods"], [])
        self.assertEqual(self._buy("mbank").status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

        self.assertEqual(self._rate(self.staff_client)["kgs_methods"], DEFAULT_LIST)
        self.assertEqual(self._buy("mbank", client=self.staff_client).status_code, 200)

    def test_admin_mode_overrides_environment(self):
        with override_settings(KGS_METHODS_MODE="off"):
            self.assertEqual(kgs_methods.mode(), "off")
            set_runtime("kgs_methods_mode", "on")
            self.assertEqual(kgs_methods.mode(), "on")
        # Мусор в настройке — выбора нет, а не «открыто всем».
        set_runtime("kgs_methods_mode", "everyone")
        self.assertEqual(kgs_methods.mode(), "off")
        self.assertEqual(self._rate()["kgs_methods"], [])

    def test_missing_setting_falls_back_to_staff(self):
        from django.conf import settings as dj_settings

        with override_settings():
            del dj_settings.KGS_METHODS_MODE
            self.assertEqual(kgs_methods.mode(), "staff")

    def test_shipped_default_mode_is_staff(self):
        # Значение по умолчанию живёт в settings.py, и окружение тестов может
        # его перекрыть — поэтому читаем сам вызов env.str(...), а не настройку.
        import re
        from pathlib import Path

        import core.settings as base_settings

        source = Path(base_settings.__file__).read_text(encoding="utf-8")
        found = re.findall(
            r'^KGS_METHODS_MODE\s*=\s*env(?:\.str)?\(\s*"KGS_METHODS_MODE"\s*,\s*default="(\w+)"\s*\)',
            source, flags=re.M)
        self.assertEqual(found, ["staff"])

    def test_enabled_list_is_filtered_and_ordered(self):
        set_runtime("kgs_methods_enabled", " card, MBANK ,paypal,,megapay")
        self.assertEqual(kgs_methods.enabled_keys(), ["mbank", "megapay", "card"])
        self.assertEqual([m["key"] for m in self._rate()["kgs_methods"]], ["mbank", "megapay", "card"])
        # Выключенный способ недоступен и при покупке.
        self.assertIsNone(kgs_methods.fp_params("odengi", self.user))
        self.assertEqual(kgs_methods.fp_params("megapay", self.user), {"pg_payment_system": "MEGAPAYKGS"})

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_card_alone_is_not_a_choice(self, post):
        set_runtime("kgs_methods_enabled", "card")
        self.assertEqual(self._rate()["kgs_methods"], [])
        self.assertEqual(self._buy("card").status_code, 400)
        set_runtime("kgs_methods_enabled", "")
        self.assertEqual(self._rate()["kgs_methods"], [])
        post.assert_not_called()

    def test_fp_params_returns_a_copy(self):
        kgs_methods.fp_params("mbank", self.user)["pg_payment_system"] = "X"
        self.assertEqual(kgs_methods.fp_params("mbank", self.user), {"pg_payment_system": "MBANKKGS"})


class ElqrTests(KgsMethodsTestCase):
    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_elqr_absent_without_code(self, post):
        self.assertNotIn("elqr", [m["key"] for m in self._rate()["kgs_methods"]])
        # В списке включённых он без кода ничего не значит.
        set_runtime("kgs_methods_enabled", "elqr,mbank,card")
        self.assertEqual(kgs_methods.enabled_keys(), ["mbank", "card"])
        self.assertEqual(self._buy("elqr").status_code, 400)
        post.assert_not_called()

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_elqr_with_code_goes_first_and_sends_the_code(self, post):
        set_runtime("kgs_elqr_ps_code", " ELQRKGS_1 ")
        self.assertEqual(self._rate()["kgs_methods"], [{"key": "elqr", "kind": "qr"}] + DEFAULT_LIST)

        r = self._buy("elqr")
        self.assertEqual(r.status_code, 200)
        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["pg_payment_system"], "ELQRKGS_1")
        self.assertEqual(sent["pg_lifetime"], "2700")
        self._assert_signed(sent)
        self.assertEqual(Payment.objects.get(order_id=r.data["order_id"]).request["pay_method"], "elqr")

    def test_elqr_alone_is_still_a_choice_for_the_buyer(self):
        set_runtime("kgs_elqr_ps_code", "ELQRKGS")
        set_runtime("kgs_methods_enabled", "card")
        self.assertEqual([m["key"] for m in self._rate()["kgs_methods"]], ["elqr", "card"])

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_bad_code_is_ignored(self, post):
        for bad in ("EL QR", "ab", "x" * 33, "ELQR;pg_amount=1", "код"):
            with self.subTest(code=bad):
                set_runtime("kgs_elqr_ps_code", bad)
                self.assertEqual(kgs_methods.elqr_code(), "")
                self.assertEqual(self._rate()["kgs_methods"], DEFAULT_LIST)
                self.assertEqual(self._buy("elqr").status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)
        post.assert_not_called()


class ResumeTests(KgsMethodsTestCase):
    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_resume_does_not_cross_methods(self, post):
        card = self._buy("card").data
        self.assertNotIn("resumed", card)

        # «Через MBANK» после «картой» — другая страница оплаты, новый платёж.
        mbank = self._buy("mbank").data
        self.assertNotIn("resumed", mbank)
        self.assertNotEqual(mbank["order_id"], card["order_id"])

        again = self._buy("mbank").data
        self.assertTrue(again["resumed"])
        self.assertEqual(again["order_id"], mbank["order_id"])
        self.assertEqual(again["redirect_url"], mbank["redirect_url"])
        self.assertEqual(set(again), {"redirect_url", "order_id", "amount", "currency", "resumed"})

        card_again = self._buy("card").data
        self.assertTrue(card_again["resumed"])
        self.assertEqual(card_again["order_id"], card["order_id"])
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(post.call_count, 2)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_plain_click_does_not_get_a_method_link_and_back(self, post):
        mbank = self._buy("mbank").data
        # Без способа (выбор выключен или старый клиент) — прежняя общая страница.
        plain = self._buy().data
        self.assertNotIn("resumed", plain)
        self.assertNotEqual(plain["order_id"], mbank["order_id"])
        self.assertTrue(self._buy().data["resumed"])
        self.assertEqual(self._buy().data["order_id"], plain["order_id"])

        # И наоборот: ссылку без способа не отдаём выбравшему карту.
        card = self._buy("card").data
        self.assertNotIn("resumed", card)
        self.assertEqual(Payment.objects.count(), 3)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_pending_banner_shows_any_method(self, post):
        mbank = self._buy("mbank").data
        pending = self.client.get("/api/plans/purchase/pending/").data["pending"]
        self.assertEqual(pending["kind"], "card")
        self.assertEqual(pending["order_id"], mbank["order_id"])
        self.assertEqual(pending["redirect_url"], mbank["redirect_url"])

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_disabled_method_link_is_not_resumed(self, post):
        self._buy("mbank")
        set_runtime("kgs_methods_enabled", "odengi,card")
        self.assertEqual(self._buy("mbank").status_code, 400)
        self.assertEqual(Payment.objects.count(), 1)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_link_with_an_old_code_is_not_resumed(self, post):
        # Код единого QR поправили в админке: ссылка со старым кодом открыла бы
        # прежнюю, неверную страницу — повторный клик должен уйти с новым кодом.
        set_runtime("kgs_elqr_ps_code", "ELQR1")
        old = self._buy("elqr").data
        self.assertTrue(self._buy("elqr").data["resumed"])

        set_runtime("kgs_elqr_ps_code", "ELQR2")
        new = self._buy("elqr").data
        self.assertNotIn("resumed", new)
        self.assertNotEqual(new["order_id"], old["order_id"])
        self.assertEqual(post.call_args.kwargs["data"]["pg_payment_system"], "ELQR2")
        # Дальше возвращаем уже к новой ссылке.
        again = self._buy("elqr").data
        self.assertTrue(again["resumed"])
        self.assertEqual(again["order_id"], new["order_id"])
        self.assertEqual(post.call_count, 2)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_resumed_bank_link_outlives_the_resume_window(self, post):
        from plans.views import KGS_APP_LINK_LIFETIME_SECONDS, RESUME_WINDOW_MINUTES

        # Ссылку отдают повторно до 30-й минуты — у неё должен оставаться запас,
        # иначе человек получит ссылку, которая умрёт, пока он открывает банк.
        self.assertGreaterEqual(KGS_APP_LINK_LIFETIME_SECONDS - RESUME_WINDOW_MINUTES * 60, 600)
        first = self._buy("mbank").data
        Payment.objects.filter(order_id=first["order_id"]).update(
            created_at=timezone.now() - timedelta(minutes=RESUME_WINDOW_MINUTES - 1))
        self.assertTrue(self._buy("mbank").data["resumed"])
        Payment.objects.filter(order_id=first["order_id"]).update(
            created_at=timezone.now() - timedelta(minutes=RESUME_WINDOW_MINUTES + 1))
        self.assertNotIn("resumed", self._buy("mbank").data)


class ExitDiscountWithMethodsTests(KgsMethodsTestCase):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.offer = ExitDiscountOffer.objects.create(
            user=self.user, shown_at=now, claimed_at=now, percent=20,
            expires_at=now + timedelta(hours=2))

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_discount_applies_with_a_method(self, post):
        r = self._buy("card")
        self.assertEqual(r.data["amount"], "392.00")
        sent = post.call_args.kwargs["data"]
        self.assertEqual(sent["pg_amount"], "392.00")
        self.assertEqual(sent["pg_payment_method"], "bankcard")
        # Скидочная ссылка живёт полчаса при любом способе, включая карту.
        self.assertEqual(sent["pg_lifetime"], "1800")
        self._assert_signed(sent)
        payment = Payment.objects.get(order_id=r.data["order_id"])
        self.assertEqual(payment.request["exit_discount"]["percent"], 20)
        self.offer.refresh_from_db()
        self.assertEqual(self.offer.applied_to_payment_id, payment.pk)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_discounted_bank_link_keeps_the_discount_lifetime(self, post):
        # Срок скидочной ссылки решает, когда скидку можно отдать другому
        # платежу, — способ оплаты его не удлиняет.
        self.assertEqual(self._buy("mbank").data["amount"], "392.00")
        self.assertEqual(post.call_args.kwargs["data"]["pg_lifetime"], "1800")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_other_method_is_not_silently_charged_full_price(self, post):
        first = self._buy("mbank").data
        self.assertEqual(first["amount"], "392.00")
        # Скидка одноразовая и закреплена за ссылкой MBANK. В окне выбора при
        # этом стоит 392 — молча выдать «картой» ссылку на 490 нельзя.
        r = self._buy("card")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data, {
            "detail": "discount_held", "amount": "490.00", "currency": "KGS",
            "held": {"method": "mbank", "order_id": first["order_id"],
                     "redirect_url": first["redirect_url"], "amount": "392.00"}})
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(post.call_count, 1)

        # Возврат к прежнему способу — та же скидочная ссылка.
        again = self._buy("mbank").data
        self.assertTrue(again["resumed"])
        self.assertEqual(again["order_id"], first["order_id"])
        self.assertEqual(again["amount"], "392.00")

        # Человек согласился платить без скидки — скидка при этом не двоится.
        for flag in ("true", 1):
            self.assertEqual(self._buy("card", full_price=flag).status_code, 409)
        full = self._buy("card", full_price=True)
        self.assertEqual(full.status_code, 200)
        self.assertEqual(full.data["amount"], "490.00")
        self.assertEqual(post.call_args.kwargs["data"]["pg_amount"], "490.00")
        self.assertEqual(Payment.objects.filter(request__exit_discount__isnull=False).count(), 1)
        # Вопрос задаётся снова при каждом клике без согласия, даже когда
        # ссылка «картой» по полной цене уже есть.
        self.assertEqual(self._buy("card").status_code, 409)
        self.assertTrue(self._buy("card", full_price=True).data["resumed"])

        # Срок скидочной ссылки вышел — скидка переезжает на новый платёж.
        Payment.objects.filter(order_id__in=[first["order_id"], full.data["order_id"]]).update(
            created_at=timezone.now() - timedelta(minutes=32))
        self.assertEqual(self._buy("card").data["amount"], "392.00")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_full_price_link_is_not_resumed_while_discount_is_held_elsewhere(self, post):
        # Зеркальный случай: MBANK начат по полной цене, потом забрана скидка
        # и ею оплачивают картой. Клик по MBANK вернул бы ссылку на 490.
        self.offer.claimed_at = None
        self.offer.save(update_fields=["claimed_at"])
        mbank = self._buy("mbank").data
        self.assertEqual(mbank["amount"], "490.00")
        self.offer.claimed_at = timezone.now()
        self.offer.save(update_fields=["claimed_at"])

        card = self._buy("card").data
        self.assertEqual(card["amount"], "392.00")
        r = self._buy("mbank")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data["held"]["method"], "card")
        self.assertEqual(r.data["held"]["order_id"], card["order_id"])
        resumed = self._buy("mbank", full_price=True).data
        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["order_id"], mbank["order_id"])
        self.assertEqual(Payment.objects.count(), 2)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_held_discount_does_not_block_other_cases(self, post):
        first = self._buy("mbank").data
        # Другой пакет: скидочной ссылки на него нет, продолжать нечего.
        other = TokenPackage.objects.create(name="B", tokens=900, price=Decimal("900"))
        r = self.client.post("/api/plans/purchase/",
                             {"package_id": other.id, "method": "card"}, format="json")
        self.assertEqual(r.status_code, 200)
        # Клик без способа (выбор выключен, старый клиент) идёт как раньше:
        # такой клиент ответа «скидка занята» не поймёт.
        self.assertEqual(self._buy().status_code, 200)

        # По скидочной ссылке банк уже ответил — продолжать там нечего.
        Payment.objects.filter(order_id=first["order_id"]).update(
            response={"redirect_url": first["redirect_url"], "callbacks": [{"type": "failure"}]})
        self.assertEqual(self._buy("odengi").status_code, 200)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_expired_offer_does_not_ask_about_the_discount(self, post):
        self._buy("mbank")
        # Скидка на витрине истекла — цена в окне выбора уже полная.
        ExitDiscountOffer.objects.filter(pk=self.offer.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1))
        r = self._buy("card")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["amount"], "490.00")


class AdminSettingsTests(KgsMethodsTestCase):
    def _patch(self, body, client=None):
        return (client or self.staff_client).patch("/api/manage/settings/", body, format="json")

    def test_settings_are_staff_only(self):
        self.assertEqual(self._patch({"kgs_methods_mode": "on"}, client=self.client).status_code, 403)

    def test_snapshot_exposes_values(self):
        data = self.staff_client.get("/api/manage/settings/").data
        self.assertEqual(data["kgs_methods_mode"], "on")
        self.assertEqual(data["kgs_methods_enabled"], "mbank,odengi,megapay,card")
        self.assertEqual(data["kgs_elqr_ps_code"], "")
        self.assertEqual(data["kgs_methods_known"],
                         ["elqr", "mbank", "odengi", "balance", "megapay", "card"])

    def test_mode_validation(self):
        for bad in ("everyone", "", None, "true"):
            with self.subTest(mode=bad):
                self.assertEqual(self._patch({"kgs_methods_mode": bad}).status_code, 400)
        self.assertEqual(kgs_methods.mode(), "on")
        r = self._patch({"kgs_methods_mode": " STAFF "})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kgs_methods_mode"], "staff")
        self.assertEqual(kgs_methods.mode(), "staff")

    def test_enabled_validation_and_normalisation(self):
        r = self._patch({"kgs_methods_enabled": "mbank,paypal"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("paypal", r.data["detail"])
        self.assertEqual(get_runtime("kgs_methods_enabled", "unset"), "unset")

        r = self._patch({"kgs_methods_enabled": " card , MBANK,card"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(get_runtime("kgs_methods_enabled", ""), "mbank,card")
        self.assertEqual(r.data["kgs_methods_enabled"], "mbank,card")

        # Список принимается и массивом; единый QR в нём не хранится.
        r = self._patch({"kgs_methods_enabled": ["megapay", "elqr", "odengi"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(get_runtime("kgs_methods_enabled", ""), "odengi,megapay")

        self.assertEqual(self._patch({"kgs_methods_enabled": ""}).status_code, 200)
        self.assertEqual(kgs_methods.enabled_keys(), [])

    def test_elqr_code_validation(self):
        for bad in ("EL QR", "ab", "x" * 33, "ELQR-KGS"):
            with self.subTest(code=bad):
                self.assertEqual(self._patch({"kgs_elqr_ps_code": bad}).status_code, 400)
        self.assertEqual(kgs_methods.elqr_code(), "")

        r = self._patch({"kgs_elqr_ps_code": " ELQRKGS "})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["kgs_elqr_ps_code"], "ELQRKGS")
        self.assertEqual(r.data["kgs_methods_enabled"], "elqr,mbank,odengi,megapay,card")

        # Пустое значение убирает код, а не записывает пустую строку.
        self.assertEqual(self._patch({"kgs_elqr_ps_code": ""}).status_code, 200)
        self.assertEqual(get_runtime("kgs_elqr_ps_code", "unset"), "unset")
        self.assertEqual(kgs_methods.elqr_code(), "")

    def test_only_strings_are_accepted(self):
        # str(True) == "True" прошёл бы проверку кода и ушёл бы в FreedomPay.
        for bad in (True, 12345, ["ELQRKGS"], {"code": "ELQRKGS"}):
            with self.subTest(code=bad):
                self.assertEqual(self._patch({"kgs_elqr_ps_code": bad}).status_code, 400)
        self.assertEqual(get_runtime("kgs_elqr_ps_code", "unset"), "unset")
        # null — то же, что пусто: кода нет.
        self.assertEqual(self._patch({"kgs_elqr_ps_code": None}).status_code, 200)

        for bad in (True, 1, ["on"]):
            with self.subTest(mode=bad):
                self.assertEqual(self._patch({"kgs_methods_mode": bad}).status_code, 400)
        self.assertEqual(kgs_methods.mode(), "on")

        # null раньше молча записывал пустой список и выключал все способы.
        for bad in (None, True, 5, ["mbank", 1], {"mbank": True}):
            with self.subTest(enabled=bad):
                self.assertEqual(self._patch({"kgs_methods_enabled": bad}).status_code, 400)
        self.assertEqual(get_runtime("kgs_methods_enabled", "unset"), "unset")

    def test_bad_field_saves_nothing_of_the_block(self):
        r = self._patch({"kgs_methods_mode": "off", "kgs_methods_enabled": "mbank,card",
                         "kgs_elqr_ps_code": "bad code"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(kgs_methods.mode(), "on")
        self.assertEqual(get_runtime("kgs_methods_enabled", "unset"), "unset")

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_payment_list_shows_the_method(self, post):
        mbank = Payment.objects.get(order_id=self._buy("mbank").data["order_id"])
        plain = Payment.objects.get(order_id=self._buy().data["order_id"])
        crypto = Payment.objects.create(
            user=self.user, amount=1, currency="USD", order_id="tokpkg-crypto",
            provider="crypto_nowpayments", request={"pay_method": "crypto"}, response={})
        self.assertEqual(PaymentAdminSerializer(mbank).data["method"], "mbank")
        self.assertEqual(PaymentAdminSerializer(plain).data["method"], "")
        # У крипты способ и так виден по провайдеру.
        self.assertEqual(PaymentAdminSerializer(crypto).data["method"], "")

        rows = self.staff_client.get("/api/manage/payments/").data
        rows = rows["results"] if isinstance(rows, dict) else rows
        by_order = {row["order_id"]: row for row in rows}
        self.assertEqual(by_order[mbank.order_id]["method"], "mbank")
        self.assertEqual(by_order[mbank.order_id]["provider"], "freedompay")


class FunnelStepTests(KgsMethodsTestCase):
    def test_method_pick_step_is_accepted(self):
        r = self.client.post("/api/payments/funnel/event/",
                             {"name": "kgs_method_pick", "meta": {"package_id": self.pkg.id, "method": "mbank"}},
                             format="json")
        self.assertEqual(r.status_code, 201)
        event = FunnelEvent.objects.get(name="kgs_method_pick")
        self.assertEqual(event.meta["method"], "mbank")
        self.assertEqual(event.user_id, self.user.id)
