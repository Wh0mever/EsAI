# -*- coding: utf-8 -*-
"""Result-уведомление FreedomPay об оплате в сомах.

Раньше адрес уведомления уходил в параметре, которого у init_payment нет, и
FreedomPay нас не вызывал: кредиты ждали сверки. Здесь проверяется, что адрес
теперь передаётся, уведомление начисляет ровно один раз (в том числе рядом со
сверкой) и получает ответ в том виде, какой FreedomPay понимает.
"""
import hashlib
import xml.etree.ElementTree as ET
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from payments import kgs_methods
from payments.freedompay import (
    make_api_signature,
    match_freedompay_script_name,
    normalize_kg_phone,
    verify_freedompay_signature,
)
from payments.models import Payment
from payments.tasks import _has_payment_marker, _verify_and_credit
from plans.models import TokenPackage, TokenTransaction

TEST_CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                           "LOCATION": "payments-result-notify-tests"}}
SECRET = "secret"
POSTBACK = "/api/payments/tokens/postback/"


def _sig(script, params, secret=SECRET):
    pieces = [script] + [str(params[k]) for k in sorted(params)] + [secret]
    return hashlib.md5(";".join(pieces).encode("utf-8")).hexdigest()


def _fp_ok(*args, **kwargs):
    resp = MagicMock(status_code=200)
    order_id = (kwargs.get("data") or {}).get("pg_order_id")
    resp.json.return_value = {"pg_status": "ok", "pg_redirect_url": f"https://pay.example/{order_id}"}
    return resp


class PhoneNormaliserTests(SimpleTestCase):
    def test_kyrgyz_numbers_become_twelve_digits(self):
        for raw in ("996555123456", "+996 555 123 456", "+996 (555) 12-34-56",
                    "0555123456", "0 555 123 456", 996555123456):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_kg_phone(raw), "996555123456")

    def test_everything_else_is_dropped(self):
        for raw in ("", None, "   ", "нет телефона", "+7 701 123 45 67", "79011234567",
                    "12345", "99655512345", "9965551234567", "1555123456",
                    "8 0555 123456", "+1 202 555 0123",
                    # Девять цифр без кода: так пишут и узбекский номер, 996 не приставляем.
                    "555123456", "901234567", "123456789",
                    # Код 996, но не мобильный: городской Бишкека и мусор.
                    "+996 312 12 34 56", "996123456789", "0123456789"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_kg_phone(raw), "")


@override_settings(CACHES=TEST_CACHES, FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN=SECRET,
                   FREEDOM_PAY_INIT_PAYMENT_URL="https://fp.example/init_payment.php",
                   YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY="", KGS_METHODS_MODE="on")
class PurchasePayloadTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        # По умолчанию из способов FreedomPay теперь включена одна карта (банки
        # платят единым QR), а эти тесты — про кошельки: возвращаем прежний список.
        default = patch.object(kgs_methods, "DEFAULT_ENABLED", "mbank,odengi,megapay,card")
        default.start()
        self.addCleanup(default.stop)
        self.user = get_user_model().objects.create_user(email="buyer@example.com", password="x")
        self.pkg = TokenPackage.objects.create(name="A", tokens=500, price=Decimal("490"))
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _sent(self, post, method=None):
        body = {"package_id": self.pkg.id}
        if method:
            body["method"] = method
        r = self.client.post("/api/plans/purchase/", body, format="json")
        self.assertEqual(r.status_code, 200)
        return post.call_args.kwargs["data"]

    def _assert_signed(self, sent):
        unsigned = {k: v for k, v in sent.items() if k != "pg_sig"}
        self.assertEqual(sent["pg_sig"], make_api_signature("init_payment", unsigned, SECRET))

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_result_url_is_sent_for_every_kgs_purchase(self, post):
        for method in (None, "card", "mbank"):
            with self.subTest(method=method):
                sent = self._sent(post, method)
                self.assertEqual(sent["pg_result_url"], "http://testserver" + POSTBACK)
                self.assertEqual(sent["pg_request_method"], "POST")
                self.assertNotIn("pg_post_link", sent)
                self.assertNotIn("pg_user_phone", sent)
                self._assert_signed(sent)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_kyrgyz_phone_is_sent_and_signed(self, post):
        self.user.tel = "+996 (555) 12-34-56"
        self.user.save(update_fields=["tel"])
        sent = self._sent(post)
        self.assertEqual(sent["pg_user_phone"], "996555123456")
        self._assert_signed(sent)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_phone_is_not_sent_to_wallets(self, post):
        # У кошелька номер может решать, кому уйдёт счёт, — из профиля его не берём.
        self.user.tel = "+996 555 123 456"
        self.user.save(update_fields=["tel"])
        self.assertEqual(self._sent(post, "card")["pg_user_phone"], "996555123456")
        for method in ("mbank", "odengi", "megapay"):
            with self.subTest(method=method):
                sent = self._sent(post, method)
                self.assertNotIn("pg_user_phone", sent)
                self._assert_signed(sent)

    def test_refused_request_is_repeated_once_without_the_phone(self):
        self.user.tel = "0555123456"
        self.user.save(update_fields=["tel"])
        sent = []

        def fp(*args, **kwargs):
            data = dict(kwargs["data"])
            sent.append(data)
            if "pg_user_phone" in data:
                resp = MagicMock(status_code=200)
                resp.json.return_value = {"pg_status": "error", "pg_error_description": "bad phone"}
                return resp
            return _fp_ok(*args, **kwargs)

        with patch("plans.views.requests.post", side_effect=fp):
            r = self.client.post("/api/plans/purchase/", {"package_id": self.pkg.id}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0]["pg_user_phone"], "996555123456")
        self.assertNotIn("pg_user_phone", sent[1])
        self._assert_signed(sent[1])
        self.assertEqual(sent[0]["pg_order_id"], sent[1]["pg_order_id"])
        # В платеже лежит то, что в итоге ушло.
        stored = Payment.objects.get(order_id=r.data["order_id"]).request["token_purchase"]["payload"]
        self.assertEqual(stored, sent[1])

    def test_refusal_without_phone_is_not_repeated(self):
        refused = MagicMock(status_code=200)
        refused.json.return_value = {"pg_status": "error", "pg_error_description": "nope"}
        with patch("plans.views.requests.post", return_value=refused) as post:
            r = self.client.post("/api/plans/purchase/", {"package_id": self.pkg.id}, format="json")
        self.assertEqual(r.status_code, 502)
        self.assertEqual(post.call_count, 1)

    @patch("plans.views.requests.post", side_effect=_fp_ok)
    def test_bad_phone_is_not_sent_and_purchase_goes_on(self, post):
        for tel in ("+7 701 123 45 67", "позвоните мне", "123"):
            with self.subTest(tel=tel):
                Payment.objects.all().delete()
                self.user.tel = tel
                self.user.save(update_fields=["tel"])
                sent = self._sent(post)
                self.assertNotIn("pg_user_phone", sent)
                self._assert_signed(sent)


@override_settings(CACHES=TEST_CACHES, FREEDOM_PAY_MERCHANT_ID="m1", FREEDOM_PAY_TOKEN=SECRET)
class ResultNotifyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user(email="payer@example.com", password="x")
        self.pkg = TokenPackage.objects.create(name="A", tokens=500, bonus_tokens=50, price=Decimal("490"))
        self.order_id = f"tokpkg-{self.user.pk}-{self.pkg.pk}-abc"
        self.payment = Payment.objects.create(
            user=self.user, amount=Decimal("490.00"), currency="KGS", order_id=self.order_id,
            request={"token_purchase": {"package_id": self.pkg.pk, "tokens": 500, "bonus_tokens": 50}},
            response={},
        )
        self.client = APIClient()
        # Письмо и сообщение в Telegram о пополнении к делу не относятся.
        notify = patch("payments.views._notify_balance_topup")
        notify.start()
        self.addCleanup(notify.stop)

    def _notification(self, script="postback", secret=SECRET, **over):
        params = {
            "pg_order_id": self.order_id, "pg_payment_id": "1502541913",
            "pg_amount": "490", "pg_currency": "KGS", "pg_net_amount": "475.3",
            "pg_ps_amount": "490", "pg_ps_full_amount": "490", "pg_ps_currency": "KGS",
            "pg_description": "EsAI: A — 500 кредитов", "pg_result": "1",
            "pg_payment_date": "2026-09-30 12:00:00", "pg_can_reject": "1",
            "pg_user_phone": "996555123456", "pg_testing_mode": "0", "pg_salt": "abc123",
        }
        params.update(over)
        params["pg_sig"] = _sig(script, params, secret)
        return params

    def _post(self, params):
        # Так уведомление и приходит: обычная форма, не JSON.
        return self.client.post(POSTBACK, urlencode(params),
                                content_type="application/x-www-form-urlencoded")

    def _credits(self):
        return TokenTransaction.objects.filter(reason="purchase", meta__order_id=self.order_id).count()

    def _balance(self):
        self.user.refresh_from_db()
        return self.user.token_balance

    def _assert_ok_xml(self, r, script="postback"):
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("application/xml"))
        body = r.content.decode("utf-8")
        self.assertTrue(body.startswith('<?xml version="1.0" encoding="utf-8"?><response>'))
        root = ET.fromstring(r.content)
        self.assertEqual(root.tag, "response")
        fields = {child.tag: child.text for child in root}
        self.assertEqual(set(fields), {"pg_status", "pg_description", "pg_salt", "pg_sig"})
        self.assertEqual(fields["pg_status"], "ok")
        self.assertTrue(fields["pg_salt"])
        unsigned = {k: v for k, v in fields.items() if k != "pg_sig"}
        self.assertEqual(fields["pg_sig"], _sig(script, unsigned))
        return fields

    def test_paid_notification_credits_once_and_gets_signed_xml(self):
        r = self._post(self._notification())
        self._assert_ok_xml(r)
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._balance(), 550)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)
        self.assertEqual(self.payment.error, "")
        self.assertTrue(self.payment.response["token_purchase_applied"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_paid)

    def test_repeat_of_the_same_notification_does_not_credit_twice(self):
        params = self._notification()
        self._assert_ok_xml(self._post(params))
        # FreedomPay повторяет вызов — ответ должен быть тем же, кредиты те же.
        self._assert_ok_xml(self._post(params))
        self._assert_ok_xml(self._post(self._notification(pg_salt="another")))
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._balance(), 550)

    def test_multipart_notification_is_accepted(self):
        r = self.client.post(POSTBACK, self._notification(), format="multipart")
        self._assert_ok_xml(r)
        self.assertEqual(self._credits(), 1)

    def test_signature_with_empty_script_name_is_accepted(self):
        # Адрес кончается слэшем: имя скрипта у FreedomPay может оказаться пустым.
        r = self._post(self._notification(script=""))
        # Ответ подписан тем же именем, с которым сошёлся запрос.
        self._assert_ok_xml(r, script="")
        self.assertEqual(self._credits(), 1)

    def test_wrong_signature_is_rejected_without_credit(self):
        cases = {
            "чужой секрет": self._notification(secret="other"),
            "другое имя скрипта": self._notification(script="result"),
            "подписи нет": {k: v for k, v in self._notification().items() if k != "pg_sig"},
            "сумму подменили": {**self._notification(), "pg_amount": "1"},
        }
        for name, params in cases.items():
            with self.subTest(case=name):
                r = self._post(params)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(self._credits(), 0)
        self.assertEqual(self._balance(), 0)
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.success)

    @override_settings(FREEDOM_PAY_TOKEN="")
    def test_no_secret_means_no_valid_signature(self):
        r = self._post(self._notification(secret=""))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._credits(), 0)

    def test_failed_payment_does_not_credit(self):
        for result in ("0", "2"):
            with self.subTest(pg_result=result):
                r = self._post(self._notification(pg_result=result))
                self._assert_ok_xml(r)
                self.assertEqual(self._credits(), 0)
                self.payment.refresh_from_db()
                self.assertFalse(self.payment.success)
        self.assertEqual(self._balance(), 0)

    def test_amount_or_currency_mismatch_does_not_credit_but_replies_ok(self):
        for over in ({"pg_amount": "49"}, {"pg_currency": "USD"}, {"pg_amount": "много"}):
            with self.subTest(**over):
                r = self._post(self._notification(**over))
                fields = self._assert_ok_xml(r)
                # Отказывать FreedomPay нельзя: «rejected» отменил бы оплату.
                self.assertNotEqual(fields["pg_status"], "rejected")
                self.assertEqual(self._credits(), 0)
                self.payment.refresh_from_db()
                self.assertFalse(self.payment.success)
                self.assertEqual(self.payment.error, "amount_mismatch")
        self.assertEqual(self._balance(), 0)

    def test_unknown_order_gets_ok_xml(self):
        r = self._post(self._notification(pg_order_id="tokpkg-0-0-missing"))
        self._assert_ok_xml(r)
        self.assertEqual(self._credits(), 0)

    def test_unknown_order_without_valid_signature_gets_nothing_signed(self):
        # Подпись нашим секретом получает только тот, кто сам его знает.
        for params in ({"pg_order_id": "nope"},
                       self._notification(pg_order_id="nope", secret="other")):
            with self.subTest(params=len(params)):
                r = self._post(params)
                self.assertEqual(r.status_code, 200)
                self.assertNotIn(b"pg_sig", r.content)

    # --- запрос возврата в браузер вместо уведомления ---------------------

    def _redirect_query(self, script=""):
        # С этим FreedomPay возвращает покупателя на success/failure URL.
        params = {"pg_order_id": self.order_id, "pg_payment_id": "1502541913", "pg_salt": "redir"}
        params["pg_sig"] = _sig(script, params)
        return params

    def test_browser_redirect_query_changes_nothing_on_postback(self):
        # До оплаты: не начисляет и не портит заказ.
        self._assert_ok_xml(self._post(self._redirect_query()), script="")
        self.assertEqual(self._credits(), 0)
        self.payment.refresh_from_db()
        self.assertFalse(self.payment.error)
        self.assertEqual(self.payment.response, {})
        # После оплаты: заказ остаётся оплаченным.
        self._assert_ok_xml(self._post(self._notification()))
        self._assert_ok_xml(self._post(self._redirect_query()), script="")
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)
        self.assertEqual(self.payment.error, "")
        self.assertEqual(self._balance(), 550)

    def test_signed_message_without_result_does_not_credit(self):
        params = self._notification()
        params.pop("pg_result")
        params.pop("pg_sig")
        params["pg_sig"] = _sig("postback", params)
        self._assert_ok_xml(self._post(params))
        self.assertEqual(self._credits(), 0)
        self.assertEqual(self._balance(), 0)

    def test_browser_redirect_query_is_not_a_refund(self):
        self._assert_ok_xml(self._post(self._notification()))
        for send in (lambda p: self.client.get("/api/payments/tokens/refund/", p),
                     lambda p: self.client.post("/api/payments/tokens/refund/", p)):
            r = send(self._redirect_query())
            self.assertEqual(r.status_code, 400)
        self.assertEqual(self._balance(), 550)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)
        # Пустое имя скрипта — только для адреса уведомления.
        self.assertFalse(verify_freedompay_signature(
            MagicMock(path="/api/payments/tokens/refund/"), self._redirect_query(), SECRET))

    # --- уведомление после того, как заказ уже зачислен --------------------

    def test_late_failure_does_not_unpay_a_credited_order(self):
        self._assert_ok_xml(self._post(self._notification()))
        for over in ({"pg_result": "0"}, {"pg_result": "2"}, {"pg_amount": "489"},
                     {"pg_result": "0", "pg_error_description": "declined"}):
            with self.subTest(**over):
                self._assert_ok_xml(self._post(self._notification(pg_salt="late", **over)))
                self.payment.refresh_from_db()
                self.assertTrue(self.payment.success)
                self.assertEqual(self.payment.error, "")
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._balance(), 550)
        # Обращения при этом записаны.
        self.assertEqual(len(self.payment.response["callbacks"]), 5)

    def test_failure_then_success_credits(self):
        self._assert_ok_xml(self._post(self._notification(pg_result="0")))
        self._assert_ok_xml(self._post(self._notification(pg_salt="second")))
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)
        self.assertEqual(self._balance(), 550)

    # --- транспорт ---------------------------------------------------------

    def test_xml_accept_header_is_not_refused(self):
        for accept in ("application/xml", "text/xml", "text/xml, application/xml"):
            with self.subTest(accept=accept):
                r = self.client.post(POSTBACK, urlencode(self._notification()),
                                     content_type="application/x-www-form-urlencoded",
                                     HTTP_ACCEPT=accept)
                self._assert_ok_xml(r)
        self.assertEqual(self._credits(), 1)
        # Отказ в подписи тоже доходит до обработчика, а не превращается в 406.
        r = self.client.post(POSTBACK, urlencode(self._notification(secret="other")),
                             content_type="application/x-www-form-urlencoded",
                             HTTP_ACCEPT="application/xml")
        self.assertEqual(r.status_code, 400)

    def test_burst_from_one_address_is_not_throttled(self):
        # Общий анонимный лимит — 30 в минуту, а FreedomPay ходит с одного адреса.
        params = self._notification()
        for _ in range(35):
            self.assertEqual(self._post(params).status_code, 200)
        self.assertEqual(self._credits(), 1)

    def test_card_secrets_and_signature_are_not_stored(self):
        self._assert_ok_xml(self._post(self._notification(
            pg_card_token="tok-123", pg_card_owner="IVAN IVANOV", pg_card_exp="12/30",
            pg_card_pan="4111-11XX-XXXX-1111")))
        with patch("payments.tasks.reconcile_pending_token_payments.delay"):
            self.client.get("/api/payments/tokens/success/", self._redirect_query("success"))
        self.payment.refresh_from_db()
        post_cb, browser_cb = self.payment.response["callbacks"]
        for key in ("pg_sig", "pg_card_token", "pg_card_owner", "pg_card_exp"):
            self.assertNotIn(key, post_cb["payload"])
        self.assertNotIn("pg_sig", browser_cb["payload"])
        # Нужное для разбора и для сверки остаётся.
        self.assertEqual(post_cb["payload"]["pg_payment_id"], "1502541913")
        self.assertEqual(post_cb["payload"]["pg_card_pan"], "4111-11XX-XXXX-1111")
        self.assertEqual(browser_cb["type"], "success")
        # Запись возврата из браузера не стёрла отметку о начислении.
        self.assertTrue(self.payment.response["token_purchase_applied"])

    def test_buyer_is_notified_only_after_commit(self):
        from payments import views as payment_views

        with self.captureOnCommitCallbacks() as callbacks:
            self._assert_ok_xml(self._post(self._notification()))
            # Кредиты уже записаны, а письмо ещё не отправлялось.
            self.assertEqual(self._credits(), 1)
            payment_views._notify_balance_topup.assert_not_called()
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        payment_views._notify_balance_topup.assert_called_once()
        self.assertEqual(payment_views._notify_balance_topup.call_args.args[1], 550)

    def test_failure_notification_is_not_a_payment_marker(self):
        self._post(self._notification(pg_result="0"))
        self.payment.refresh_from_db()
        self.assertEqual(len(self.payment.response["callbacks"]), 1)
        # Отказ не заставляет сверку опрашивать заказ всю неделю…
        self.assertFalse(_has_payment_marker(self.payment))
        # …а возврат покупателя из оплаты и успешное уведомление — признак оплаты.
        self.payment.response = {"callbacks": [{"type": "failure", "payload": {"pg_payment_id": "1"}}]}
        self.assertTrue(_has_payment_marker(self.payment))
        self.payment.response = {"callbacks": [{"type": "post", "payload": {"pg_payment_id": "1", "pg_result": "1"}}]}
        self.assertTrue(_has_payment_marker(self.payment))

    def test_browser_success_page_is_untouched(self):
        with patch("payments.tasks.reconcile_pending_token_payments.delay"):
            r = self.client.get("/api/payments/tokens/success/", {"pg_order_id": self.order_id})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._credits(), 0)

    # --- уведомление и сверка рядом ------------------------------------

    def _status(self):
        return {"pg_status": "ok", "pg_transaction_status": "ok",
                "pg_amount": "490.00", "pg_currency": "KGS", "pg_payment_id": "1502541913"}

    def test_notification_then_reconcile_credits_once(self):
        self._assert_ok_xml(self._post(self._notification()))
        with patch("payments.tasks.fetch_payment_status", return_value=self._status()):
            self.assertEqual(_verify_and_credit(self.payment), "already")
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._balance(), 550)

    def test_reconcile_then_notification_credits_once(self):
        with patch("payments.tasks.fetch_payment_status", return_value=self._status()):
            self.assertEqual(_verify_and_credit(self.payment), "credited")
        self.assertEqual(self._credits(), 1)
        self._assert_ok_xml(self._post(self._notification()))
        self.assertEqual(self._credits(), 1)
        self.assertEqual(self._balance(), 550)
        self.payment.refresh_from_db()
        self.assertTrue(self.payment.success)


class ScriptNameMatchTests(SimpleTestCase):
    def _request(self, path=POSTBACK):
        return MagicMock(path=path)

    def test_returns_the_matching_script_name(self):
        params = {"pg_order_id": "o1", "pg_salt": "s"}
        for script in ("postback", "tokens/postback", ""):
            with self.subTest(script=script):
                payload = {**params, "pg_sig": _sig(script, params)}
                self.assertEqual(match_freedompay_script_name(
                    self._request(), payload, SECRET, allow_empty_script=True), script)
                # Общая проверка (возврат денег, привязка карты) пустое имя не принимает.
                self.assertEqual(verify_freedompay_signature(self._request(), payload, SECRET), script != "")
                self.assertEqual(match_freedompay_script_name(self._request(), payload, SECRET),
                                 script or None)

    def test_no_match_is_none_not_empty_string(self):
        params = {"pg_order_id": "o1", "pg_salt": "s"}
        bad = {**params, "pg_sig": _sig("postback", params, "other")}
        self.assertIsNone(match_freedompay_script_name(self._request(), bad, SECRET))
        self.assertFalse(verify_freedompay_signature(self._request(), bad, SECRET))
        # Без секрета и без подписи совпадения быть не может — даже с пустым именем.
        empty = {**params, "pg_sig": _sig("", params, "")}
        self.assertIsNone(match_freedompay_script_name(self._request(), empty, "", allow_empty_script=True))
        self.assertIsNone(match_freedompay_script_name(self._request(), params, SECRET, allow_empty_script=True))
