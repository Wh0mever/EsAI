from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from payments.freedompay import FreedomPay, FreedomPayError
from payments.models import Payment
from plans.models import (
    BillingPeriod,
    GenerationUsage,
    Plan,
    TokenTransaction,
    UserSubscription,
)
from plans.tiers import user_tier
from plans.views import ActivatePlanView
from users.models import UserCardBind


@override_settings(
    FREEDOM_PAY_API_BASE="https://example.test/v1",
    FREEDOM_PAY_MERCHANT_ID="000000",
    FREEDOM_PAY_TOKEN="secret",
    SITE_BASE_URL="https://vokalo.test",
)
class FreedomPayTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="payer@example.com",
            password="testpass123",
        )

    @patch("payments.freedompay.requests.post")
    def test_charge_raises_provider_decline_with_details(self, post_mock):
        init_response = Mock()
        init_response.status_code = 200
        init_response.json.return_value = {
            "pg_status": "ok",
            "pg_payment_id": "1467039992",
        }

        direct_response = Mock()
        direct_response.status_code = 200
        direct_response.json.return_value = {
            "pg_status": "error",
            "pg_error_code": "99999",
            "pg_error_description": "Неизвестная ошибка платежной системы",
        }

        post_mock.side_effect = [init_response, direct_response]

        client = FreedomPay(self.user)
        with self.assertRaises(FreedomPayError) as ctx:
            client.charge(
                amount=Decimal("1.00"),
                currency="USD",
                order_id="plan-switch-test",
                description="Plan switch",
                card_token="token-123",
                test=False,
            )

        exc = ctx.exception
        self.assertTrue(exc.is_provider_decline)
        self.assertEqual(exc.script, "direct")
        self.assertEqual(exc.code, "99999")
        self.assertEqual(exc.description, "Неизвестная ошибка платежной системы")

    @patch("payments.freedompay.requests.post")
    def test_charge_sends_minimal_direct_payload(self, post_mock):
        init_response = Mock()
        init_response.status_code = 200
        init_response.json.return_value = {
            "pg_status": "ok",
            "pg_payment_id": "1467039992",
        }

        direct_response = Mock()
        direct_response.status_code = 200
        direct_response.json.return_value = {
            "pg_status": "ok",
            "pg_payment_id": "1467039992",
            "pg_payment_status": "ok",
        }

        post_mock.side_effect = [init_response, direct_response]

        client = FreedomPay(self.user)
        client.charge(
            amount=Decimal("1.00"),
            currency="USD",
            order_id="plan-switch-test",
            description="Plan switch",
            card_token="token-123",
            test=False,
        )

        _, direct_call = post_mock.call_args_list
        direct_payload = direct_call.kwargs["data"]
        self.assertEqual(direct_payload["pg_merchant_id"], "000000")
        self.assertEqual(direct_payload["pg_payment_id"], "1467039992")
        self.assertNotIn("pg_amount", direct_payload)
        self.assertNotIn("pg_card_token", direct_payload)
        self.assertNotIn("pg_order_id", direct_payload)

    def _paid_plan(self):
        return Plan.objects.create(
            is_active=True,
            is_free=False,
            period=BillingPeriod.MONTHLY,
            price_amount=Decimal("1.00"),
        )

    def _bind_card(self):
        return UserCardBind.objects.create(
            user=self.user,
            card_id="card-1",
            card_token="token-123",
            card_hash="4111-11XX-XXXX-1111",
            card_month="12",
            card_year="30",
            card_bank="bank",
            card_country="KG",
            card_3ds=False,
        )

    def _activate(self, plan):
        request = APIRequestFactory().post(f"/api/plans/activate/{plan.id}/", {})
        force_authenticate(request, user=self.user)
        return ActivatePlanView.as_view()(request, plan_id=plan.id)

    # Ловушка стоит на единственном сетевом выходе FreedomPay, а не на
    # FreedomPay.charge: так она переживёт переименование метода и поймает
    # списание, откуда бы его ни позвали.
    @patch("payments.freedompay.requests.post")
    def test_activate_plan_is_gone_and_never_charges_the_card(self, post_mock):
        """Активация подписки снята: 410 и ни одного денежного следа.

        Раньше тест проверял, что отказ банка превращается в 400. Той ветки
        больше нет — подписки заменены на pay-as-you-go, и ActivatePlanView
        отвечает 410 первой же строкой. Но старый код никуда не делся, он
        лежит рядом как _legacy_post и умеет списывать с привязанной карты
        по-настоящему (test=False, новый order_id на каждый клик, никакой
        идемпотентности). Хуже того, эти деньги не превращаются в кредиты:
        платёж создаётся без token_purchase, и ни один колбэк не начислит
        баланс. Поэтому тест сторожит не текст ответа, а отсутствие следов —
        запроса в банк, строки платежа, транзакции и изменившегося баланса.
        """
        self.user.token_balance = 777
        self.user.save(update_fields=["token_balance"])
        plan = self._paid_plan()
        self._bind_card()

        response = self._activate(plan)

        # Проверяем деньги раньше кода ответа: если ветку вернут в строй,
        # сообщение теста должно говорить «сходили в банк», а не «502 != 410».
        # Строку платежа FreedomPay заводит ДО сетевого вызова, так что след
        # остался бы даже от списания, умершего на первом запросе.
        post_mock.assert_not_called()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(TokenTransaction.objects.count(), 0)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data, {"detail": "subscriptions_deprecated"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.token_balance, 777)
        self.assertFalse(self.user.is_paid)

    def test_activate_plan_does_not_hand_out_paid_plan_for_free(self):
        """Без карты платный план тоже не выдаётся.

        В снятой ветке списание стояло под условием «платный план И есть
        карта», поэтому человек без карты получал платный тариф даром:
        активную подписку и полные лимиты. Это дороже неудачного списания —
        раздаётся сам товар, — и проверяется отдельно, потому что ловушка на
        банк такой путь не поймала бы: в него просто не заходят.
        """
        plan = self._paid_plan()  # карту намеренно не привязываем

        response = self._activate(plan)

        self.assertEqual(response.status_code, 410)
        # Любая подписка, а не только активная: легаси-ветка завела бы её и
        # в неоплаченном виде, а доступ к моделям это уже открывает.
        self.assertFalse(UserSubscription.objects.filter(user=self.user).exists())
        self.assertEqual(GenerationUsage.objects.count(), 0)
        self.user.refresh_from_db()
        self.assertEqual(user_tier(self.user), "free")
