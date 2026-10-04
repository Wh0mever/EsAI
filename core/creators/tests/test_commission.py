"""Комиссия креатора: база и сумма по каждому провайдеру, правила статуса, ручные действия.

Здесь же лежит общая база денежных тестов (MoneyTestCase) и помощники,
которые проводят подставной платёж НАСТОЯЩИМ путём начисления — тем же кодом,
что постбэк FreedomPay, сверка, вебхук ЮKassa, криптопроцессор и бот Stars.
Остальные денежные тесты берут их отсюда.
"""
import threading
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from adminapi.runtime import set_runtime
from audit.models import AdminActionLog, EventLog
from payments import tasks as payment_tasks
from payments import views as payment_views
from payments.crypto import base as crypto_base
from payments.crypto import credit as crypto_credit
from payments.models import CryptoInvoice, Payment, StarInvoice
from plans.models import CurrencyRate, TokenTransaction
from plans.wallet import credit_tokens

from .. import balance, commission
from ..errors import CreatorsError
from ..models import Creator, CreatorCommission, CreatorLevel, CreatorReferral
from . import factories as f

RATE = Decimal("0.0115")
# Настоящая функция курса: в тестах она подменена, а её саму проверяет RateTests.
REAL_KGS_RATE = commission.kgs_rate


class MoneyTestCase(f.CreatorsTestCase):
    """Курс сом -> доллар зафиксирован, уведомления и письма заглушены."""

    def setUp(self):
        super().setUp()
        self.emit = self.patch("creators.notify.emit")
        self.patch("creators.commission.kgs_rate", return_value=(RATE, "test"))
        self.patch("payments.views._notify_balance_topup")
        self.patch("botapi.tasks.notify")

    def patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def emitted(self, event):
        return [call for call in self.emit.call_args_list if call.args[1] == event]

    def bound(self, creator=None, **referral):
        """Креатор (10 %), покупатель и действующая привязка между ними."""
        creator = creator or f.make_creator(code=f"C{uuid.uuid4().hex[:8].upper()}")
        buyer = f.make_user()
        return creator, buyer, f.make_referral(creator, buyer, **referral)

    def rows(self, payment):
        return list(CreatorCommission.objects.filter(payment=payment).order_by("id"))

    def shares(self, order_id):
        return TokenTransaction.objects.filter(reason="referral", meta__order_id=order_id)


# ------------------------------------------------- настоящие пути оплаты ---

def pay_postback(payment):
    """То, что делает подписанный постбэк FreedomPay: начисление под блокировкой платежа."""
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        locked.success, locked.error = True, ""
        payment_views._credit_token_package_for_payment(locked, locked.order_id)
        locked.save(update_fields=["response", "success", "error"])


def pay_reconcile(payment):
    """Сверка FreedomPay: статус спрашивается у провайдера (ответ подставной)."""
    status = {"pg_status": "ok", "pg_transaction_status": "ok",
              "pg_amount": str(payment.amount), "pg_currency": payment.currency}
    with patch("payments.tasks.fetch_payment_status", return_value=status):
        return payment_tasks._verify_and_credit(payment)


def refund_postback(payment):
    """То, что делает сигнал возврата FreedomPay: изъятие под блокировкой платежа."""
    with transaction.atomic():
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        payment_views._clawback_token_package_for_payment(locked, locked.order_id, {})
        locked.success = False
        locked.error = locked.error or "refunded"
        locked.save(update_fields=["response", "success", "error"])


def yk_answer(payment, **extra):
    """Ответ API ЮKassa про оплаченный платёж."""
    return {"id": "yk-1", "status": "succeeded", "paid": True,
            "amount": {"value": str(payment.amount), "currency": "RUB"},
            "metadata": {"order_id": payment.order_id}, **extra}


def pay_yookassa(payment):
    return payment_views.apply_yookassa_state(payment, yk_answer(payment), source="yookassa_webhook")


def crypto_invoice(payment, pay_amount="10.5"):
    return CryptoInvoice.objects.create(
        payment=payment, provider="nowpayments", provider_invoice_id=f"np-{uuid.uuid4().hex[:12]}",
        price_amount=payment.amount, price_currency="USD", pay_currency="usdttrc20",
        pay_coin="USDT", pay_network="TRC-20", pay_address="TX-address",
        pay_amount=Decimal(pay_amount))


def pay_crypto(invoice, paid, status=crypto_base.FINISHED):
    """Состояние счёта у процессора: сколько пришло и в каком он статусе."""
    state = crypto_base.InvoiceState(
        provider_id=invoice.provider_invoice_id, order_id=invoice.payment.order_id,
        status=status, provider_status=status, price_amount=invoice.price_amount,
        price_currency="USD", pay_currency=invoice.pay_currency, pay_amount=invoice.pay_amount,
        actually_paid=Decimal(str(paid)), raw={"payment_status": status})
    return crypto_credit.apply_provider_status(invoice, state, source="ipn")


def star_invoice(payment, status=StarInvoice.STATUS_PAID):
    info = payment.request["token_purchase"]
    return StarInvoice.objects.create(
        payment=payment, telegram_id=900100, payload=f"i1.{uuid.uuid4().hex}", package_id=1,
        tokens=info["tokens"], bonus_tokens=info["bonus_tokens"],
        stars_amount=int(payment.amount), status=status,
        expires_at=timezone.now() + timedelta(hours=1),
        telegram_payment_charge_id=f"charge-{uuid.uuid4().hex}", paid_at=timezone.now())


def pay_stars(payment):
    """Подтверждение оплаты Stars начисляет тем же кодом, что и постбэк."""
    pay_postback(payment)


# ---------------------------------------------------------- база и сумма ---

class BaseAndAmountTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound()

    def accrued(self, payment, **kwargs):
        row = commission.accrue(payment, **kwargs)
        self.assertIsNotNone(row)
        return row

    def test_freedompay_kgs(self):
        row = self.accrued(f.make_payment(self.buyer, amount="490.00"))
        self.assertEqual((row.paid_amount, row.paid_currency), (Decimal("490.00"), "KGS"))
        self.assertEqual(row.base_usd, Decimal("5.635000"))
        self.assertEqual(row.rate_to_usd, Decimal("0.01150000"))
        self.assertEqual(row.rate_source, "kgs:test")
        self.assertEqual((row.percent, row.level_key), (Decimal("10.00"), "creator"))
        self.assertEqual(row.amount_usdt, Decimal("0.563500"))
        self.assertEqual((row.status, row.reason), ("accrued", ""))
        self.assertEqual((row.provider, row.order_id, row.part), ("freedompay", row.payment.order_id, ""))
        self.assertEqual((row.buyer_id, row.buyer_pk, row.referral_id),
                         (self.buyer.pk, self.buyer.pk, self.referral.pk))

    def test_hundred_som_at_ten_percent(self):
        # Пример из постановки: 100 сом × 0.0115 × 10 % = 0.115 USDT.
        row = self.accrued(f.make_payment(self.buyer, amount="100.00"))
        self.assertEqual(row.base_usd, Decimal("1.150000"))
        self.assertEqual(row.amount_usdt, Decimal("0.115000"))

    def test_amount_is_rounded_down_to_six_decimals(self):
        # 333.33 × 0.0115 = 3.833295; 10 % от этого — 0.3833295, седьмой знак отбрасывается.
        row = self.accrued(f.make_payment(self.buyer, amount="333.33"))
        self.assertEqual(row.base_usd, Decimal("3.833295"))
        self.assertEqual(row.amount_usdt, Decimal("0.383329"))

    def test_base_is_rounded_down_too(self):
        # И база, и сумма округляются вниз: лишней миллионной доли креатору не начислить.
        with patch("creators.commission.kgs_rate", return_value=(Decimal("0.01151234"), "test")):
            row = self.accrued(f.make_payment(self.buyer, amount="490.00"))
        self.assertEqual(row.base_usd, Decimal("5.641046"))      # 5.6410466 -> вниз
        self.assertEqual(row.amount_usdt, Decimal("0.564104"))   # 0.5641046 -> вниз

    def test_freedompay_usd(self):
        row = self.accrued(f.make_payment(self.buyer, amount="10.00", currency="USD"))
        self.assertEqual((row.base_usd, row.rate_source, row.rate_to_usd),
                         (Decimal("10.000000"), "usd", Decimal("1.00000000")))
        self.assertEqual(row.amount_usdt, Decimal("1.000000"))

    def test_freedompay_unknown_currency_is_void(self):
        row = self.accrued(f.make_payment(self.buyer, amount="10.00", currency="EUR"))
        self.assertEqual((row.status, row.reason, row.amount_usdt),
                         ("void", "unsupported_currency", Decimal("0")))
        self.assertEqual((row.paid_amount, row.paid_currency, row.base_usd, row.rate_source),
                         (Decimal("10.00"), "EUR", Decimal("0"), ""))
        self.assertIsNone(row.available_at)

    def test_yookassa_by_kgs_price(self):
        # В рублях заплачено 520, но база — цена пакета в сомах: 490 × 0.0115.
        payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00",
                                 kgs_price="490.00", rate_kgs_to_rub="1.0612")
        row = self.accrued(payment)
        self.assertEqual((row.paid_amount, row.paid_currency), (Decimal("520.00"), "RUB"))
        self.assertEqual(row.base_usd, Decimal("5.635000"))
        self.assertEqual(row.rate_source, "kgs_price:test")
        self.assertEqual(row.rate_to_usd, Decimal("0.01083654"))     # 5.635 / 520
        self.assertEqual(row.amount_usdt, Decimal("0.563500"))

    def test_yookassa_falls_back_to_showcase_rate(self):
        # Цены в сомах в платеже нет: сомы восстанавливаются из рублей по витринному курсу.
        payment = f.make_payment(self.buyer, provider="yookassa", amount="509.60",
                                 kgs_price="", rate_kgs_to_rub="1.04")
        row = self.accrued(payment)
        self.assertEqual(row.base_usd, Decimal("5.635000"))          # 509.60 / 1.04 = 490 сом
        self.assertEqual(row.rate_source, "kgs_price:test")

    def test_yookassa_without_any_price_is_void(self):
        for extra in ({"kgs_price": "", "rate_kgs_to_rub": ""},
                      {"kgs_price": "мусор", "rate_kgs_to_rub": "0"}):
            with self.subTest(extra=extra):
                payment = f.make_payment(self.buyer, provider="yookassa", amount="520.00", **extra)
                row = self.accrued(payment)
                self.assertEqual((row.status, row.reason), ("void", "no_base"))

    def test_crypto_parts(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=1000)
        first = self.accrued(payment, part="333", credited=333)
        second = self.accrued(payment, part="1000", credited=667)
        self.assertEqual((first.paid_amount, first.paid_currency), (Decimal("3.33"), "USD"))
        self.assertEqual((first.base_usd, first.rate_source), (Decimal("3.330000"), "usd"))
        self.assertEqual(first.amount_usdt, Decimal("0.333000"))
        self.assertEqual(second.base_usd, Decimal("6.670000"))
        self.assertEqual(second.amount_usdt, Decimal("0.667000"))
        # Части в сумме не превышают целого.
        self.assertLessEqual(first.base_usd + second.base_usd, Decimal("10"))

    def test_crypto_part_base_never_sums_above_the_payment(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00",
                                 tokens=3)
        parts = [self.accrued(payment, part=str(n), credited=1) for n in (1, 2, 3)]
        self.assertEqual([p.base_usd for p in parts], [Decimal("3.333333")] * 3)
        self.assertLess(sum(p.base_usd for p in parts), Decimal("10"))

    def test_crypto_without_credited_is_void(self):
        payment = f.make_payment(self.buyer, provider="crypto_nowpayments", amount="10.00")
        row = self.accrued(payment)
        self.assertEqual((row.status, row.reason), ("void", "no_base"))

    def test_stars(self):
        payment = f.make_payment(self.buyer, provider="telegram_stars", amount="385")
        with patch("plans.stars.withdraw_rate", return_value=Decimal("0.013")):
            row = self.accrued(payment)
        self.assertEqual((row.paid_amount, row.paid_currency), (Decimal("385.00"), "XTR"))
        self.assertEqual((row.base_usd, row.rate_source), (Decimal("5.005000"), "stars_withdraw_rate"))
        self.assertEqual(row.rate_to_usd, Decimal("0.01300000"))
        self.assertEqual(row.amount_usdt, Decimal("0.500500"))

    def test_unknown_provider_is_void(self):
        row = self.accrued(f.make_payment(self.buyer, provider="paypal", amount="10.00"))
        self.assertEqual((row.status, row.reason), ("void", "unsupported_provider"))

    def test_payment_success_flag_is_not_consulted(self):
        # Недоплаченный криптосчёт остаётся success=False, хотя деньги пришли.
        row = self.accrued(f.make_payment(self.buyer, amount="490.00", success=False))
        self.assertEqual(row.status, "accrued")

    def test_compute_base_raises_codes(self):
        cases = ((f.make_payment(self.buyer, currency="EUR"), None, "unsupported_currency"),
                 (f.make_payment(self.buyer, provider="paypal"), None, "unsupported_provider"),
                 (f.make_payment(self.buyer, provider="crypto_nowpayments", tokens=0), 5, "no_base"))
        for payment, credited, code in cases:
            with self.subTest(code=code), self.assertRaises(CreatorsError) as ctx:
                commission.compute_base(payment, credited=credited)
            self.assertEqual(ctx.exception.code, code)


class RateTests(MoneyTestCase):
    """Источник курса сом -> доллар: ручной, живой, из настроек, запасной."""

    @override_settings(CURRENCY_KGS_TO_USD_RATE=0.0115)
    def test_sources_in_order(self):
        self.assertEqual(REAL_KGS_RATE(), (Decimal("0.0115"), "settings"))

        CurrencyRate.objects.create(currency="KGS", rate_to_usd=Decimal("0.0114"))
        rate, source = REAL_KGS_RATE()
        self.assertEqual((rate, source), (Decimal("0.0114"), "live"))

        # Ручное значение администратора сильнее живого курса.
        set_runtime("currency_kgs_to_usd_rate", 0.012)
        self.assertEqual(REAL_KGS_RATE(), (Decimal("0.012"), "manual"))

    @override_settings(CURRENCY_KGS_TO_USD_RATE=0.0115)
    def test_stale_live_rate_is_ignored(self):
        CurrencyRate.objects.create(currency="KGS", rate_to_usd=Decimal("0.0114"))
        CurrencyRate.objects.update(fetched_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(REAL_KGS_RATE(), (Decimal("0.0115"), "settings"))

    @override_settings(CURRENCY_KGS_TO_USD_RATE=0.0115)
    def test_rate_outside_the_corridor_falls_back_to_settings(self):
        for broken in (5, 0.00001):
            with self.subTest(rate=broken):
                set_runtime("currency_kgs_to_usd_rate", broken)
                self.assertEqual(REAL_KGS_RATE(), (Decimal("0.0115"), "settings_fallback"))

    @override_settings(CURRENCY_KGS_TO_USD_RATE=0.0115)
    def test_rate_source_lands_on_the_row(self):
        creator, buyer, _ = self.bound()
        set_runtime("currency_kgs_to_usd_rate", 0.012)
        with patch("creators.commission.kgs_rate", REAL_KGS_RATE):
            row = commission.accrue(f.make_payment(buyer, amount="100.00"))
        self.assertEqual((row.rate_source, row.base_usd, row.amount_usdt),
                         ("kgs:manual", Decimal("1.200000"), Decimal("0.120000")))


# -------------------------------------------------------- правила статуса ---

class StatusRuleTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.creator, self.buyer, self.referral = self.bound()

    def assertVoid(self, payment, reason, **kwargs):
        row = commission.accrue(payment, **kwargs)
        self.assertEqual((row.status, row.reason), ("void", reason))
        self.assertEqual(row.amount_usdt, Decimal("0"))
        self.assertIsNone(row.available_at)
        self.assertEqual(self.emitted("commission_accrued"), [])
        self.assertEqual(self.emitted("new_paying_user"), [])
        return row

    def test_legacy_charge_without_token_purchase(self):
        self.assertVoid(f.make_payment(self.buyer, token_purchase=None), "no_token_purchase")

    def test_test_payment(self):
        self.assertVoid(f.make_payment(self.buyer, is_test=True), "test_payment")

    def test_creators_own_purchase(self):
        f.make_referral(self.creator, self.creator.user)
        self.assertVoid(f.make_payment(self.creator.user), "self_purchase")

    def test_staff_buyer(self):
        for flag in ("is_staff", "is_superuser"):
            with self.subTest(flag=flag):
                creator, buyer, _ = self.bound()
                setattr(buyer, flag, True)
                buyer.save(update_fields=[flag])
                self.assertVoid(f.make_payment(buyer), "buyer_staff")

    def test_unlimited_buyer(self):
        self.buyer.is_unlimited = True
        self.buyer.save(update_fields=["is_unlimited"])
        self.assertVoid(f.make_payment(self.buyer), "buyer_unlimited")

    def test_ordinary_share_already_paid_for_the_order(self):
        payment = f.make_payment(self.buyer)
        credit_tokens(f.make_user(), 50, "referral", meta={"order_id": payment.order_id})
        self.assertVoid(payment, "referral_share_paid")

    def test_zero_base(self):
        row = self.assertVoid(f.make_payment(self.buyer, amount="0.00"), "zero_base")
        self.assertEqual(row.rate_source, "kgs:test")

    def test_late_accrual_on_refunded_payment_is_reversed(self):
        payment = f.make_payment(self.buyer, amount="490.00")
        payment.response = {"token_purchase_clawed_back": True}
        payment.error = "refunded"
        payment.save(update_fields=["response", "error"])
        row = commission.accrue(payment)
        self.assertEqual((row.status, row.reason), ("reversed", "refund:clawback"))
        self.assertEqual(row.amount_usdt, Decimal("0.563500"))
        self.assertIsNotNone(row.reversed_at)
        self.assertIsNone(row.available_at)
        self.assertEqual(self.emitted("commission_accrued"), [])

    def test_blocked_creator_gets_held(self):
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        row = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        self.assertEqual((row.status, row.reason), ("held", "creator_blocked"))
        self.assertEqual(row.amount_usdt, Decimal("0.563500"))
        self.assertIsNotNone(row.available_at)
        # Придержанная комиссия не объявляется ни заработком, ни «новым платящим».
        self.assertEqual(self.emit.call_args_list, [])

    def test_suspect_referral_gets_held(self):
        creator, buyer, _ = self.bound(suspect=True)
        row = commission.accrue(f.make_payment(buyer, amount="490.00"))
        self.assertEqual((row.status, row.reason), ("held", "referral_suspect"))
        # Подозрительный реферал для креатора невидим: об его оплате не сообщаем
        # вовсе — ни в кабинете, ни в Telegram.
        self.assertEqual(self.emit.call_args_list, [])

    def test_paying_user_is_announced_when_the_first_commission_becomes_earnings(self):
        admin = f.make_user(superuser=True)
        creator, buyer, referral = self.bound(suspect=True)
        first = commission.accrue(f.make_payment(buyer, amount="100.00"))
        second = commission.accrue(f.make_payment(buyer, amount="100.00"))
        self.assertEqual(self.emit.call_args_list, [])

        # Администратор отпустил первую строку: только теперь это «новый платящий».
        commission.release(first.pk, actor=admin, reason="проверено")
        announced = self.emitted("new_paying_user")
        self.assertEqual(len(announced), 1)
        self.assertEqual(announced[0].args[0].pk, creator.pk)
        self.assertIn("*", announced[0].kwargs["user_label"])
        self.assertEqual(len(self.emitted("commission_accrued")), 1)
        # Вторая строка того же человека — уже не «новый».
        commission.release(second.pk, actor=admin, reason="проверено")
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        self.assertEqual(len(self.emitted("commission_accrued")), 2)

    def test_held_rows_do_not_hide_the_first_real_earning(self):
        creator, buyer, referral = self.bound(suspect=True)
        commission.accrue(f.make_payment(buyer, amount="100.00"))
        # Пометку сняли, придержанное не отпускали: следующая оплата — первая объявленная.
        CreatorReferral.objects.filter(pk=referral.pk).update(suspect=False)
        row = commission.accrue(f.make_payment(buyer, amount="100.00"))
        self.assertEqual(row.status, "accrued")
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        self.assertEqual(len(self.emitted("commission_accrued")), 1)

    def test_creator_on_a_deactivated_account_gets_held(self):
        # Аккаунт креатора отключён (администратор, чёрный список): в кабинет
        # войти некому, поэтому комиссии его рефералов не становятся заработком.
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        row = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        self.assertEqual((row.status, row.reason), ("held", "creator_inactive"))
        self.assertEqual(row.amount_usdt, Decimal("0.563500"))
        self.assertIsNotNone(row.available_at)
        self.assertEqual(self.emit.call_args_list, [])
        self.assertEqual(balance.summary(self.creator).earned, Decimal("0"))
        self.assertEqual(balance.summary(self.creator).held, Decimal("0.563500"))
        # Обычная реферальная доля при этом не платится: заказ остаётся за креатором.
        self.assertFalse(self.shares(row.order_id).exists())

        # Аккаунт включили обратно — следующая оплата снова заработок, а
        # придержанную строку отпускает администратор.
        owner.is_active = True
        owner.save(update_fields=["is_active"])
        again = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        self.assertEqual((again.status, again.reason), ("accrued", ""))
        released = commission.release(row.pk, actor=f.factory_admin(), reason="аккаунт вернули")
        self.assertEqual((released.status, released.reason), ("accrued", "released"))

    def test_blocked_creator_wins_over_deactivated_account(self):
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        row = commission.accrue(f.make_payment(self.buyer))
        self.assertEqual((row.status, row.reason), ("held", "creator_blocked"))

    def test_blocked_creator_wins_over_suspect_referral(self):
        creator, buyer, _ = self.bound(suspect=True)
        Creator.objects.filter(pk=creator.pk).update(status="blocked")
        row = commission.accrue(f.make_payment(buyer))
        self.assertEqual((row.status, row.reason), ("held", "creator_blocked"))

    def test_hold_date(self):
        row = commission.accrue(f.make_payment(self.buyer))
        self.assertAlmostEqual(row.available_at, row.created_at + timedelta(days=14),
                               delta=timedelta(seconds=5))
        with override_settings(CREATORS_HOLD_DAYS=3):
            row = commission.accrue(f.make_payment(self.buyer))
        self.assertAlmostEqual(row.available_at, row.created_at + timedelta(days=3),
                               delta=timedelta(seconds=5))

    def test_level_snapshot_survives_a_level_change(self):
        first = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        Creator.objects.filter(pk=self.creator.pk).update(
            level=CreatorLevel.objects.get(key="ambassador"))
        second = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        first.refresh_from_db()
        # Смена уровня действует только на следующие начисления.
        self.assertEqual((first.percent, first.level_key, first.amount_usdt),
                         (Decimal("10.00"), "creator", Decimal("0.563500")))
        self.assertEqual((second.percent, second.level_key, second.amount_usdt),
                         (Decimal("20.00"), "ambassador", Decimal("1.127000")))

    def test_level_percent_edit_does_not_touch_old_rows(self):
        first = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        CreatorLevel.objects.filter(key="creator").update(percent=Decimal("12.50"))
        second = commission.accrue(f.make_payment(self.buyer, amount="490.00"))
        first.refresh_from_db()
        self.assertEqual(first.percent, Decimal("10.00"))
        self.assertEqual((second.percent, second.amount_usdt), (Decimal("12.50"), Decimal("0.704375")))

    def test_nothing_without_binding_user_or_in_off_mode(self):
        stranger = f.make_user()
        self.assertIsNone(commission.accrue(f.make_payment(stranger)))
        self.assertIsNone(commission.accrue(f.make_payment(None)))
        with override_settings(CREATORS_MODE="off"):
            self.assertIsNone(commission.accrue(f.make_payment(self.buyer)))
        self.assertEqual(CreatorCommission.objects.count(), 0)

    def test_staff_mode_still_accrues(self):
        with override_settings(CREATORS_MODE="staff"):
            row = commission.accrue(f.make_payment(self.buyer))
        self.assertEqual(row.status, "accrued")

    def test_notifications(self):
        commission.accrue(f.make_payment(self.buyer, amount="100.00"))
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        accrued = self.emitted("commission_accrued")
        self.assertEqual(len(accrued), 1)
        self.assertEqual(accrued[0].args[0].pk, self.creator.pk)
        self.assertEqual(accrued[0].kwargs,
                         {"amount_usdt": "0.115", "base_usdt": "1.15", "percent": "10"})
        # В уведомлении покупатель замаскирован: почта целиком креатору не уходит.
        label = self.emitted("new_paying_user")[0].kwargs["user_label"]
        self.assertNotEqual(label, self.buyer.email)
        self.assertIn("*", label)

        # Вторая оплата того же человека: «новый платящий» уже был.
        commission.accrue(f.make_payment(self.buyer, amount="100.00"))
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        self.assertEqual(len(self.emitted("commission_accrued")), 2)

    def test_accrue_never_raises_and_purchase_survives(self):
        payment = f.make_payment(self.buyer, amount="490.00", tokens=500, success=False)
        with patch("creators.commission._insert", side_effect=RuntimeError("boom")):
            self.assertIsNone(commission.accrue(payment))
            pay_postback(payment)
        self.buyer.refresh_from_db()
        payment.refresh_from_db()
        # Кредиты покупателя на месте, платёж оплачен, комиссии нет — её доделает дозачисление.
        self.assertEqual(self.buyer.token_balance, 500)
        self.assertTrue(payment.success)
        self.assertEqual(self.rows(payment), [])
        self.assertTrue(EventLog.objects.filter(
            type="payment", level="error",
            message__startswith="creator_commission_failed").exists())

    def test_failing_side_effects_do_not_lose_the_commission(self):
        self.emit.side_effect = RuntimeError("telegram down")
        row = commission.accrue(f.make_payment(self.buyer))
        self.assertEqual(row.status, "accrued")


# ----------------------------------------------- привязка на момент оплаты ---

class CoverageTests(MoneyTestCase):
    def test_checkout_opened_before_the_code_was_typed(self):
        # Оплата открыта (строка платежа есть), потом введён код, потом оплачен
        # тот же заказ: комиссия положена — привязка смотрится на момент зачисления.
        creator = f.make_creator()
        buyer = f.make_user()
        payment = f.make_payment(buyer, amount="490.00", success=False,
                                 created_at=timezone.now() - timedelta(hours=2))
        referral = f.make_referral(creator, buyer, source="promo")
        self.assertGreater(referral.bound_at, payment.created_at)
        pay_postback(payment)
        rows = self.rows(payment)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].creator_id, rows[0].status), (creator.pk, "accrued"))
        self.assertEqual(self.shares(payment.order_id).count(), 0)

    def test_order_paid_before_a_rebind_stays_with_the_old_creator(self):
        old, buyer, referral = self.bound()
        new = f.make_creator()
        before = f.make_payment(buyer, success=False)
        open_order = f.make_payment(buyer, success=False)     # создан до перепривязки
        pay_postback(before)

        # Перепривязка администратором: старая строка закрыта, новая открыта.
        CreatorReferral.objects.filter(pk=referral.pk).update(
            ended_at=timezone.now(), end_reason="admin_rebind")
        f.make_referral(new, buyer, source="admin")
        pay_postback(open_order)

        self.assertEqual([row.creator_id for row in self.rows(before)], [old.pk])
        # Создан до перепривязки, оплачен после — комиссия новому креатору.
        self.assertEqual([row.creator_id for row in self.rows(open_order)], [new.pk])

    def test_credited_at(self):
        creator, buyer, _ = self.bound()
        payment = f.make_payment(buyer, provider="crypto_nowpayments", amount="10.00", tokens=1000)
        before = timezone.now()
        # Записи о зачислении ещё нет — берётся текущий момент.
        self.assertGreaterEqual(commission.credited_at(payment), before)

        f.credit_purchase(payment, credited=400, idem="400")
        f.credit_purchase(payment, credited=600, idem="1000")
        first, second = TokenTransaction.objects.filter(reason="purchase").order_by("id")
        earlier = timezone.now() - timedelta(days=2)
        TokenTransaction.objects.filter(pk=first.pk).update(created_at=earlier)
        self.assertEqual(commission.credited_at(payment), earlier)
        self.assertEqual(commission.credited_at(payment, "400"), earlier)
        second.refresh_from_db()
        self.assertEqual(commission.credited_at(payment, "1000"), second.created_at)

    def test_accrue_without_a_passed_referral_uses_the_binding_at_credit_time(self):
        # Привязку сняли после оплаты — дозачисление всё равно находит того, кто действовал тогда.
        creator, buyer, referral = self.bound(bound_at=timezone.now() - timedelta(days=5))
        payment = f.make_payment(buyer)
        f.credit_purchase(payment)
        TokenTransaction.objects.filter(reason="purchase").update(
            created_at=timezone.now() - timedelta(days=2))
        CreatorReferral.objects.filter(pk=referral.pk).update(
            ended_at=timezone.now() - timedelta(days=1), end_reason="admin_unbind")
        row = commission.accrue(payment)
        self.assertEqual((row.creator_id, row.referral_id), (creator.pk, referral.pk))


# --------------------------------------------------- признаки возврата ---

class RefundMarkerTests(MoneyTestCase):
    def test_every_marker_in_order(self):
        buyer = f.make_user()
        payment = f.make_payment(buyer, provider="telegram_stars", amount="385")
        self.assertEqual(commission.refund_markers(payment), [])
        self.assertEqual(commission.refund_marker(payment), "")

        star_invoice(payment, status=StarInvoice.STATUS_REFUNDED)
        invoice = crypto_invoice(payment)
        CryptoInvoice.objects.filter(pk=invoice.pk).update(flags={"refund_seen": True})
        # Заново из базы: у прежнего объекта запомнено, что счетов нет.
        payment = Payment.objects.get(pk=payment.pk)
        payment.response = {"admin_refund": {"kind": "fraud"}, "token_purchase_clawed_back": True,
                            "yookassa_refunded": {"amount": "1"}, "freedompay_refunded": {"at": "x"}}
        payment.error = "stars_refunded"
        self.assertEqual(commission.refund_markers(payment),
                         ["admin_fraud", "clawback", "stars", "crypto", "yookassa", "freedompay",
                          "error_flag"])
        self.assertEqual(commission.refund_marker(payment), "admin_fraud")

    def test_failed_clawback_is_a_marker(self):
        payment = f.make_payment(f.make_user())
        payment.error = "token_clawback_failed:boom"
        self.assertEqual(commission.refund_markers(payment), ["clawback_failed"])
        payment.error = "refunded"
        self.assertEqual(commission.refund_markers(payment), ["error_flag"])
        payment.error = "amount_mismatch"
        self.assertEqual(commission.refund_markers(payment), [])

    def test_crypto_invoice_status(self):
        payment = f.make_payment(f.make_user(), provider="crypto_nowpayments", amount="10.00")
        invoice = crypto_invoice(payment)
        self.assertEqual(commission.refund_marker(Payment.objects.get(pk=payment.pk)), "")
        CryptoInvoice.objects.filter(pk=invoice.pk).update(status="refunded")
        self.assertEqual(commission.refund_marker(Payment.objects.get(pk=payment.pk)), "crypto")


# ------------------------------------------- действия администратора ---

class AdminActionTests(MoneyTestCase):
    def setUp(self):
        super().setUp()
        self.admin = f.make_user(superuser=True)
        self.creator, self.buyer, self.referral = self.bound()

    def logs(self, action):
        return AdminActionLog.objects.filter(action=action)

    def assertRefused(self, code, fn, *args, **kwargs):
        with self.assertRaises(CreatorsError) as ctx:
            fn(*args, **kwargs)
        self.assertEqual(ctx.exception.code, code)

    # --- void

    def test_void_from_accrued_and_held(self):
        for status in ("accrued", "held"):
            with self.subTest(status=status):
                row = f.make_commission(self.creator, status=status,
                                        reason="creator_blocked" if status == "held" else "")
                result = commission.void(row.pk, actor=self.admin, reason="дубль")
                self.assertEqual((result.status, result.reason), ("void", "admin_void"))
                # Сумма остаётся в строке: её можно вернуть restore().
                self.assertEqual(result.amount_usdt, Decimal("1.500000"))
                log = self.logs("commission.void").get(target_id=str(row.pk))
                self.assertEqual((log.actor_id, log.creator_id, log.reason),
                                 (self.admin.pk, self.creator.pk, "дубль"))
                self.assertEqual(log.before["status"], status)
                self.assertEqual(log.after, {"status": "void", "reason": "admin_void"})

    def test_void_refusals(self):
        row = f.make_commission(self.creator)
        self.assertRefused("reason_required", commission.void, row.pk, actor=self.admin, reason=" ")
        self.assertRefused("not_found", commission.void, 10 ** 9, actor=self.admin, reason="x")
        for status in ("reversed", "void"):
            other = f.make_commission(self.creator, status=status)
            self.assertRefused("bad_state", commission.void, other.pk, actor=self.admin, reason="x")
        self.assertEqual(self.logs("commission.void").count(), 0)

    # --- release

    def test_release(self):
        row = f.make_commission(self.creator, status="held", reason="referral_suspect",
                                amount="0.115000", base="1.150000")
        available_at = row.available_at
        result = commission.release(row.pk, actor=self.admin, reason="проверено")
        self.assertEqual((result.status, result.reason), ("accrued", "released"))
        self.assertEqual(result.available_at, available_at)
        log = self.logs("commission.release").get()
        self.assertEqual((log.target_id, log.creator_id), (str(row.pk), self.creator.pk))
        self.assertEqual(log.before, {"status": "held", "reason": "referral_suspect"})
        # Придержанную строку креатору не объявляли — объявляем сейчас.
        self.assertEqual(self.emitted("commission_accrued")[0].kwargs,
                         {"amount_usdt": "0.115", "base_usdt": "1.15", "percent": "10"})
        self.assertEqual(len(self.emitted("new_paying_user")), 1)

    def test_release_does_not_announce_a_known_paying_user_again(self):
        payment = f.make_payment(self.buyer, amount="100.00")
        commission.accrue(payment)
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        held = f.make_commission(self.creator, buyer=self.buyer, status="held",
                                 reason="creator_blocked")
        commission.release(held.pk, actor=self.admin)
        self.assertEqual(len(self.emitted("new_paying_user")), 1)
        self.assertEqual(len(self.emitted("commission_accrued")), 2)

    def test_release_refusals(self):
        for status in ("accrued", "reversed", "void"):
            row = f.make_commission(self.creator, status=status)
            self.assertRefused("bad_state", commission.release, row.pk, actor=self.admin)
        payment = f.make_payment(self.buyer)
        row = f.make_commission(self.creator, payment, status="held", reason="creator_blocked")
        Payment.objects.filter(pk=payment.pk).update(error="refunded")
        self.assertRefused("payment_refunded", commission.release, row.pk, actor=self.admin)
        self.assertEqual(self.logs("commission.release").count(), 0)
        self.assertEqual(self.emitted("commission_accrued"), [])

    # --- restore

    def test_restore_from_reversed_and_from_admin_void(self):
        cases = (("reversed", "refund:admin"), ("void", "admin_void"))
        for status, reason in cases:
            with self.subTest(status=status):
                row = f.make_commission(self.creator, status=status, reason=reason,
                                        available_in_days=-3)
                result = commission.restore(row.pk, actor=self.admin, reason="ошибка оператора")
                self.assertEqual((result.status, result.reason), ("accrued", "restored"))
                self.assertIsNone(result.reversed_at)
                self.assertIsNotNone(result.available_at)
                log = self.logs("commission.restore").get(target_id=str(row.pk))
                self.assertEqual(log.before, {"status": status, "reason": reason})
                self.assertEqual(log.after, {"status": "accrued", "reason": "restored"})
        # Возврат комиссии — тихое исправление, без уведомления.
        self.assertEqual(self.emitted("commission_accrued"), [])

    def test_restore_hold_date(self):
        # Холд ещё не вышел — дата остаётся прежней.
        fresh = f.make_commission(self.creator, status="reversed", available_in_days=5)
        result = commission.restore(fresh.pk, actor=self.admin, reason="x")
        self.assertEqual(result.available_at, fresh.available_at)
        # Холд уже вышел — доступна с момента возврата, а не задним числом.
        old = f.make_commission(self.creator, status="reversed", available_in_days=-5)
        before = timezone.now()
        result = commission.restore(old.pk, actor=self.admin, reason="x")
        self.assertGreaterEqual(result.available_at, before)
        # Даты не было (аннулировано руками) — холд считается от создания строки.
        void = f.make_commission(self.creator, status="void", reason="admin_void")
        result = commission.restore(void.pk, actor=self.admin, reason="x")
        self.assertAlmostEqual(result.available_at, void.created_at + timedelta(days=14),
                               delta=timedelta(seconds=5))

    def test_restore_refusals(self):
        row = f.make_commission(self.creator, status="reversed")
        self.assertRefused("reason_required", commission.restore, row.pk, actor=self.admin, reason="")
        for status in ("accrued", "held"):
            other = f.make_commission(self.creator, status=status)
            self.assertRefused("bad_state", commission.restore, other.pk, actor=self.admin, reason="x")
        # Аннулировано самим начислением (сумма ноль) — возвращать нечем.
        auto_void = f.make_commission(self.creator, status="void", reason="self_purchase")
        self.assertRefused("bad_state", commission.restore, auto_void.pk, actor=self.admin, reason="x")
        self.assertEqual(self.logs("commission.restore").count(), 0)

    def test_restore_refused_when_the_provider_says_refunded(self):
        markers = ({"response": {"token_purchase_clawed_back": True}},
                   {"response": {"yookassa_refunded": {"amount": "1"}}},
                   {"response": {"freedompay_refunded": {"at": "x"}}},
                   {"error": "refunded"},
                   # Ручная отметка вместе с изъятием кредитов тоже не снимается.
                   {"response": {"admin_refund": {"kind": "refund"},
                                 "token_purchase_clawed_back": True}})
        for fields in markers:
            with self.subTest(fields=fields):
                payment = f.make_payment(self.buyer)
                Payment.objects.filter(pk=payment.pk).update(**fields)
                row = f.make_commission(self.creator, payment, status="reversed")
                for clear in (False, True):
                    self.assertRefused("payment_refunded", commission.restore, row.pk,
                                       actor=self.admin, reason="x", clear_admin_refund=clear)
                payment.refresh_from_db()
                self.assertNotIn("admin_refund_cleared", payment.response or {})

    def test_restore_with_only_the_admin_mark(self):
        payment = f.make_payment(self.buyer)
        mark = {"kind": "refund", "by_id": self.admin.pk, "reason": "по ошибке", "clawback": False}
        Payment.objects.filter(pk=payment.pk).update(response={"admin_refund": mark})
        row = f.make_commission(self.creator, payment, status="reversed", reason="refund:admin")

        self.assertRefused("payment_refunded", commission.restore, row.pk,
                           actor=self.admin, reason="x")
        result = commission.restore(row.pk, actor=self.admin, reason="мисклик",
                                    clear_admin_refund=True)
        self.assertEqual((result.status, result.reason), ("accrued", "restored"))

        payment.refresh_from_db()
        self.assertNotIn("admin_refund", payment.response)
        cleared = payment.response["admin_refund_cleared"]
        self.assertEqual((cleared["kind"], cleared["cleared_by_id"]), ("refund", self.admin.pk))
        self.assertIn("cleared_at", cleared)
        self.assertEqual(commission.refund_markers(payment), [])
        # Две записи журнала: возврат комиссии и снятие отметки с платежа.
        self.assertEqual(self.logs("commission.restore").count(), 1)
        cleared_log = self.logs("payment.mark_refunded").get()
        self.assertEqual((cleared_log.target_id, cleared_log.creator_id),
                         (str(payment.pk), self.creator.pk))
        self.assertEqual(cleared_log.after, {"cleared": True})

    def test_restore_for_blocked_creator_is_held(self):
        row = f.make_commission(self.creator, status="reversed")
        Creator.objects.filter(pk=self.creator.pk).update(status="blocked")
        result = commission.restore(row.pk, actor=self.admin, reason="x")
        self.assertEqual((result.status, result.reason), ("held", "creator_blocked"))

    def test_restore_for_deactivated_creator_account_is_held(self):
        row = f.make_commission(self.creator, status="reversed")
        owner = self.creator.user
        owner.is_active = False
        owner.save(update_fields=["is_active"])
        result = commission.restore(row.pk, actor=self.admin, reason="x")
        self.assertEqual((result.status, result.reason), ("held", "creator_inactive"))
        self.assertEqual(self.logs("commission.restore").get().after,
                         {"status": "held", "reason": "creator_inactive"})

    def test_restore_keeps_the_hold_of_a_suspect_referral(self):
        # «Аннулировать и вернуть» не должно превращать придержанное в заработок
        # в обход снятия пометки с реферала.
        creator, buyer, referral = self.bound(suspect=True)
        row = commission.accrue(f.make_payment(buyer, amount="490.00"))
        self.assertEqual((row.status, row.reason), ("held", "referral_suspect"))
        commission.void(row.pk, actor=self.admin, reason="мисклик")
        result = commission.restore(row.pk, actor=self.admin, reason="вернуть как было")
        self.assertEqual((result.status, result.reason), ("held", "referral_suspect"))
        self.assertEqual(balance.summary(creator).earned, Decimal("0"))
        self.assertEqual(balance.summary(creator).held, Decimal("0.563500"))
        self.assertEqual(self.logs("commission.restore").get().after,
                         {"status": "held", "reason": "referral_suspect"})

        # То же после отмены по ручной отметке о возврате.
        CreatorCommission.objects.filter(pk=row.pk).update(
            status="reversed", reason="refund:admin", reversed_at=timezone.now())
        result = commission.restore(row.pk, actor=self.admin, reason="x")
        self.assertEqual((result.status, result.reason), ("held", "referral_suspect"))

        # Пометку сняли — та же строка возвращается заработком.
        CreatorReferral.objects.filter(pk=referral.pk).update(suspect=False)
        commission.void(row.pk, actor=self.admin, reason="x")
        result = commission.restore(row.pk, actor=self.admin, reason="x")
        self.assertEqual((result.status, result.reason), ("accrued", "restored"))
        self.assertEqual(balance.summary(creator).earned, Decimal("0.563500"))

    def test_restore_keeps_the_hold_of_an_own_purchase(self):
        # След слияния аккаунтов: покупатель — сам креатор. Заработком это не становится.
        own = self.creator.user
        for status, reason in (("void", "admin_void"), ("reversed", "refund:admin")):
            with self.subTest(status=status):
                row = f.make_commission(self.creator, f.make_payment(own), buyer=own,
                                        status=status, reason=reason)
                result = commission.restore(row.pk, actor=self.admin, reason="x")
                self.assertEqual((result.status, result.reason), ("held", "merge_self"))
        self.assertEqual(balance.summary(self.creator).earned, Decimal("0"))

    def test_failed_log_rolls_the_action_back(self):
        row = f.make_commission(self.creator)
        with patch("creators.commission.log_admin_action", side_effect=RuntimeError("журнал")):
            with self.assertRaises(RuntimeError):
                commission.void(row.pk, actor=self.admin, reason="x")
        row.refresh_from_db()
        self.assertEqual(row.status, "accrued")


# ------------------------------------------------------- блокировки [pg] ---

@skipUnless(connection.vendor == "postgresql", "блокировки строк есть только в PostgreSQL")
class AccrueLockTests(f.CreatorsTransactionTestCase):
    def test_accrue_locks_the_creator_row_only(self):
        creator = f.make_creator()
        buyer = f.make_user()
        f.make_referral(creator, buyer)
        payment = f.make_payment(buyer)

        inside, release = threading.Event(), threading.Event()
        real_insert = commission._insert

        def slow_insert(fields):
            inside.set()
            release.wait(20)
            return real_insert(fields)

        def worker():
            try:
                commission.accrue(payment)
            finally:
                connection.close()

        with patch("creators.commission._insert", slow_insert), patch("creators.notify.emit"):
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(inside.wait(20))
                with transaction.atomic():
                    # Пользователь креатора и общий уровень НЕ заблокированы начислением.
                    get_user_model().objects.select_for_update(nowait=True).get(pk=creator.user_id)
                    CreatorLevel.objects.select_for_update(nowait=True).get(pk=creator.level_id)
                    # А сама строка креатора — заблокирована.
                    with self.assertRaises(DatabaseError), transaction.atomic():
                        Creator.objects.select_for_update(nowait=True).get(pk=creator.pk)
            finally:
                release.set()
                thread.join()
        self.assertEqual(CreatorCommission.objects.filter(payment=payment).count(), 1)
