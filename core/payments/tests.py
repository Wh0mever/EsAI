from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from payments.freedompay import FreedomPay, FreedomPayError
from plans.models import BillingPeriod, Plan, SubscriptionStatus, UserSubscription
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

    @patch("plans.views.FreedomPay.charge")
    def test_activate_plan_is_gone_and_never_charges_the_card(self, charge_mock):
        """Активация подписки снята: 410 и ни одного обращения к деньгам.

        Раньше этот тест проверял, что отказ банка превращается в 400. Той
        ветки больше нет — подписки заменены на pay-as-you-go, и
        ActivatePlanView сразу отвечает 410 (старый код сохранён рядом как
        _legacy_post). Проверять исчезнувший ответ бессмысленно, а вот
        обратное включение легаси-ветки — реальный риск: она списывает деньги
        с привязанной карты. Поэтому здесь и стоят карта, платный план и
        зеркало FreedomPay.charge: если кто-то вернёт списание, тест упадёт.
        """
        plan = Plan.objects.create(
            is_active=True,
            is_free=False,
            period=BillingPeriod.MONTHLY,
            price_amount=Decimal("1.00"),
        )
        UserCardBind.objects.create(
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

        request = APIRequestFactory().post(f"/api/plans/activate/{plan.id}/", {})
        force_authenticate(request, user=self.user)
        response = ActivatePlanView.as_view()(request, plan_id=plan.id)

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.data, {"detail": "subscriptions_deprecated"})
        charge_mock.assert_not_called()
        self.assertFalse(
            UserSubscription.objects.filter(
                user=self.user, status=SubscriptionStatus.ACTIVE).exists())
