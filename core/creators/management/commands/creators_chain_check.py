"""python manage.py creators_chain_check [--rollback] [--json]

Проверка всей цепочки программы Creators до того, как появится интерфейс:
заявка -> креатор -> код -> ссылка -> пользователь -> оплата -> комиссия ->
баланс -> вывод USDT -> возврат -> долг -> блокировка -> сверка.

Платежи подставные, а пути начисления и возврата — НАСТОЯЩИЕ: те же функции,
которые вызывают постбэк FreedomPay, сверка, вебхук ЮKassa, криптопроцессор,
единый QR (GoPay) и бот Stars. Наружу не уходит ни одного запроса: провайдеры
и уведомления подменены.

По умолчанию работает в отдельной временной базе (под settings_sqlitetest — в
памяти, на PostgreSQL — test_<имя>). С --rollback — в текущей базе внутри одной
транзакции, которая в конце всегда откатывается.

Печатает таблицу «шаг | провайдер | ожидалось | получено | PASS/FAIL»;
код возврата 1, если есть хотя бы один FAIL.
"""
from __future__ import annotations

import json
import sys
import uuid
from contextlib import ExitStack
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.test import RequestFactory, override_settings
from django.utils import timezone

from creators import balance, checks, commission, levels, tasks, withdrawals
from creators.errors import CreatorsError
from creators.models import Creator, CreatorCommission, CreatorReferral
from payments.models import CryptoInvoice, GoPayInvoice, Payment, StarInvoice

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "creators-chain-check"}}

Q6 = Decimal("0.000001")
CODE = "CHAIN15"
RATE = Decimal("0.0115")
VALID_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
BAD_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u"   # та же строка с испорченной контрольной суммой


def _q6(value) -> str:
    return str(Decimal(value).quantize(Q6, rounding=ROUND_DOWN))


def _refusal(call) -> str:
    """Код отказа сервиса или "ok", если отказа не было."""
    try:
        call()
    except CreatorsError as exc:
        return exc.code
    return "ok"


class Chain:
    """Один прогон цепочки. Строки таблицы копятся в rows."""

    def __init__(self, fp_status: MagicMock):
        self.rows: list[dict] = []
        self.fp_status = fp_status          # подменённый запрос статуса FreedomPay
        self.run_id = uuid.uuid4().hex[:8]
        self.User = get_user_model()
        # Сколько креатор должен заработать к шагу S12 — по расчёту, а не по базе.
        self.expected_earned = Decimal("0")

    # ------------------------------------------------------------ служебное

    def check(self, step: str, provider: str, expected, actual) -> None:
        expected, actual = str(expected), str(actual)
        self.rows.append({"step": step, "provider": provider, "expected": expected,
                          "actual": actual, "result": "PASS" if expected == actual else "FAIL"})

    def run(self) -> list[dict]:
        steps = [
            ("S01", self.s01_application), ("S02", self.s02_code), ("S03", self.s03_link),
            ("S04", self.s04_promo), ("S05", self.s05_refusals),
            ("S06", self.s06_freedompay_postback), ("S07", self.s07_freedompay_reconcile),
            ("S08", self.s08_yookassa), ("S09", self.s09_crypto), ("S10", self.s10_stars),
            ("S11", self.s11_ordinary), ("S12", self.s12_balance), ("S13", self.s13_level),
            ("S14", self.s14_withdrawal),
            ("S15", self.s15_refund_freedompay), ("S16", self.s16_refund_admin),
            ("S17", self.s17_refund_yookassa), ("S18", self.s18_refund_crypto),
            ("S19", self.s19_refund_stars),
            ("S20", self.s20_debt), ("S21", self.s21_blocked), ("S22", self.s22_checks),
        ]
        for name, step in steps:
            try:
                # Шаг в своей точке сохранения: сбой одного шага не ломает
                # транзакцию прогона (--rollback) и не прячет остальные.
                with transaction.atomic():
                    step(name)
            except Exception as exc:  # noqa: BLE001 — строка FAIL вместо падения команды
                self.check(name, "-", "шаг выполнен", f"{type(exc).__name__}: {exc}"[:300])
        return self.rows

    def user(self, label: str, **extra):
        return self.User.objects.create_user(
            email=f"chain-{label}-{self.run_id}@example.com", password=None, **extra)

    @staticmethod
    def request(cookies: dict | None = None):
        request = RequestFactory().post("/")
        request.COOKIES.update(cookies or {})
        request.data = {}
        return request

    def payment(self, user, provider: str, amount: str, currency: str, tokens: int,
                request: dict | None = None) -> Payment:
        """Заказ пакета кредитов — как его создаёт оформление оплаты (ещё не оплачен)."""
        return Payment.objects.create(
            user=user, provider=provider, amount=Decimal(amount), currency=currency,
            order_id=f"tokpkg-{user.pk}-1-{uuid.uuid4().hex[:10]}",
            description="creators_chain_check", is_test=False, success=False,
            request={"token_purchase": {"package_id": 1, "tokens": tokens, "bonus_tokens": 0},
                     **(request or {})},
            response={})

    def facts(self, payment) -> str:
        """Что начислено по платежу: строки комиссии и доля обычной рефералки."""
        from plans.models import TokenTransaction

        rows = list(CreatorCommission.objects.filter(payment=payment).order_by("id"))
        shares = TokenTransaction.objects.filter(
            reason="referral", delta__gt=0, meta__order_id=payment.order_id).count()
        parts = [f"[part={row.part or '-'} base={_q6(row.base_usd)} amount={_q6(row.amount_usdt)} "
                 f"percent={row.percent:.2f} source={row.rate_source} status={row.status}]"
                 for row in rows]
        return f"rows={len(rows)} {' '.join(parts)} referral_tx={shares}".replace("  ", " ")

    @staticmethod
    def expect(*rows, referral_tx: int = 0) -> str:
        """rows: (part, base, amount, percent, source, status)."""
        parts = [f"[part={part or '-'} base={base} amount={amount} percent={percent} "
                 f"source={source} status={status}]"
                 for part, base, amount, percent, source, status in rows]
        return f"rows={len(rows)} {' '.join(parts)} referral_tx={referral_tx}".replace("  ", " ")

    def states(self, payment) -> str:
        rows = CreatorCommission.objects.filter(payment=payment).order_by("id")
        return " ".join(f"{row.status}/{row.reason}" for row in rows) or "нет комиссий"

    # -------------------------------------------------- настоящие пути оплаты

    @staticmethod
    def credit_postback(payment) -> None:
        """То, что делает подписанный постбэк FreedomPay (и подтверждение Stars)."""
        from payments import views as payment_views

        with transaction.atomic():
            locked = Payment.objects.select_for_update().get(pk=payment.pk)
            locked.success, locked.error = True, ""
            payment_views._credit_token_package_for_payment(locked, locked.order_id,
                                                            defer_notify=True)
            locked.save(update_fields=["response", "success", "error"])

    @staticmethod
    def refund_postback(payment) -> None:
        """То, что делает сигнал возврата FreedomPay: изъятие кредитов под блокировкой платежа."""
        from payments import views as payment_views

        with transaction.atomic():
            locked = Payment.objects.select_for_update().get(pk=payment.pk)
            payment_views._clawback_token_package_for_payment(locked, locked.order_id, {})
            locked.success = False
            locked.error = locked.error or "refunded"
            locked.save(update_fields=["response", "success", "error"])

    def credit_reconcile(self, payment) -> str:
        from payments import tasks as payment_tasks

        self.fp_status.return_value = {
            "pg_status": "ok", "pg_transaction_status": "ok",
            "pg_amount": str(payment.amount), "pg_currency": "KGS"}
        try:
            return payment_tasks._verify_and_credit(payment)
        finally:
            self.fp_status.return_value = {}

    def yookassa_answer(self, payment, **extra) -> dict:
        return {"id": payment.request["yookassa_payment_id"], "status": "succeeded", "paid": True,
                "amount": {"value": str(payment.amount), "currency": "RUB"},
                "metadata": {"order_id": payment.order_id}, **extra}

    def crypto_state(self, payment, invoice, status: str, paid: str):
        from payments.crypto import base

        return base.InvoiceState(
            provider_id=invoice.provider_invoice_id, order_id=payment.order_id, status=status,
            provider_status=status, price_amount=invoice.price_amount, price_currency="USD",
            pay_currency=invoice.pay_currency, pay_amount=invoice.pay_amount,
            actually_paid=Decimal(paid), raw={"payment_status": status, "chain_check": True})

    def gopay_invoice(self, payment, env: str = "live") -> GoPayInvoice:
        """Счёт единого QR — как его сохраняет оформление оплаты после ответа GoPay."""
        return GoPayInvoice.objects.create(
            payment=payment, env=env, provider_payment_id=uuid.uuid4().hex, status="created",
            amount=payment.amount, lifetime_seconds=900, qr_data="https://pay.example#chain",
            expires_at=timezone.now() + timedelta(minutes=15))

    @staticmethod
    def gopay_state(payment, invoice, status: str = "COMMITTED"):
        """Ответ GoPay на наш запрос статуса. Оба номера обязательны: без них не зачисляется."""
        from payments.gopay.client import PaymentState

        data = {"payment_id": invoice.provider_payment_id, "order_id": payment.order_id,
                "status": status, "amount": str(payment.amount)}
        if invoice.env == "test":
            # GoPay присылает флаг только у тестовых платежей.
            data["testing_mode"] = True
        return PaymentState.from_payload(data)

    def star_invoice(self, payment, telegram_id: int) -> StarInvoice:
        info = payment.request["token_purchase"]
        return StarInvoice.objects.create(
            payment=payment, telegram_id=telegram_id, payload=f"chain-{uuid.uuid4().hex}",
            package_id=1, package_name="chain", tokens=info["tokens"], bonus_tokens=0,
            stars_amount=int(payment.amount), status=StarInvoice.STATUS_PAID,
            expires_at=timezone.now() + timedelta(hours=24),
            telegram_payment_charge_id=f"chain-charge-{uuid.uuid4().hex}", paid_at=timezone.now())

    def kgs_purchase(self, buyer, amount: str = "490.00", tokens: int = 500) -> Payment:
        payment = self.payment(buyer, "freedompay", amount, "KGS", tokens)
        self.credit_postback(payment)
        return payment

    # ------------------------------------------------------------------ шаги

    def s01_application(self, step):
        from creators import program

        self.admin = self.user("admin", is_staff=True, is_superuser=True)
        self.creator_user = self.user("creator")
        application = program.submit_application(self.creator_user, {
            "name": "Chain Creator", "telegram": "@chain_creator", "country": "KG",
            "instagram_url": "https://instagram.com/chain_creator", "followers": 1000,
            "occupation": "Проверка цепочки программы", "motivation": "Проверка цепочки программы",
            "samples": ["https://example.com/sample"], "lang": "ru"})
        self.check(step, "-", "заявка new", f"заявка {application.status}")

        no_level = _refusal(lambda: program.approve_application(
            application.pk, actor=self.admin, level_key=""))
        still_none = not Creator.objects.filter(user=self.creator_user).exists()
        self.check(step, "-", "одобрение без уровня: validation, креатора нет",
                   f"одобрение без уровня: {no_level}, креатора {'нет' if still_none else 'СОЗДАН'}")

        program.approve_application(application.pk, actor=self.admin, level_key="creator_pro")
        self.creator = Creator.objects.select_related("level").get(user=self.creator_user)
        self.check(step, "-", "креатор active creator_pro 15.00",
                   f"креатор {self.creator.status} {self.creator.level.key} "
                   f"{self.creator.level.percent:.2f}")

    def s02_code(self, step):
        from adminapi.serializers import PromoCodeAdminSerializer
        from creators import codes
        from plans.models import PromoCode
        from rest_framework import serializers

        # Прямое направление общего пространства имён: код, занятый реф-кодом
        # пользователя или обычным промокодом, креатору не достаётся.
        self.user("uid-owner", referral_uid="ChainUid")
        PromoCode.objects.create(code="CHAINPROMO", bonus_credits=1)
        self.check(step, "-", "код = чужой referral_uid: code_taken",
                   "код = чужой referral_uid: "
                   + _refusal(lambda: codes.create_code(self.creator, "chainuid")))
        self.check(step, "-", "код = обычный промокод: code_taken",
                   "код = обычный промокод: "
                   + _refusal(lambda: codes.create_code(self.creator, "chainpromo")))

        row = codes.create_code(self.creator, CODE.lower())
        self.check(step, "-", f"код {CODE}", f"код {row.code}")
        self.check(step, "-", "второй код: code_already_set",
                   "второй код: " + _refusal(lambda: codes.create_code(self.creator, "CHAIN16")))
        try:
            PromoCodeAdminSerializer().validate_code(CODE)
            promo = "принят"
        except serializers.ValidationError:
            promo = "отказ"
        self.check(step, "-", f"обычный промокод {CODE}: отказ", f"обычный промокод {CODE}: {promo}")
        squatter = self.user("squatter", referral_uid=CODE)
        self.check(step, "-", f"referral_uid {CODE}: заменён",
                   f"referral_uid {CODE}: " + ("заменён" if squatter.referral_uid != CODE else "ПРИНЯТ"))

    def s03_link(self, step):
        from users.services import maybe_link_referrer

        self.buyer_link = self.user("buyer-link")
        maybe_link_referrer(self.request({"esai_ref": CODE}), self.buyer_link)
        self.buyer_link.refresh_from_db()
        referral = CreatorReferral.objects.active_for(self.buyer_link.pk)
        self.check(step, "-", f"привязка link к креатору {self.creator.pk}, referred_by пуст",
                   f"привязка {getattr(referral, 'source', 'нет')} к креатору "
                   f"{getattr(referral, 'creator_id', None)}, referred_by "
                   f"{'пуст' if self.buyer_link.referred_by_id is None else 'ЗАПОЛНЕН'}")

    def s04_promo(self, step):
        from users.services import activate_promo

        self.buyer_promo = self.user("buyer-promo")
        # Оплата открыта ДО ввода кода: этот заказ оплачивается в S06 и обязан дать
        # комиссию — привязка проверяется на момент зачисления, а не создания платежа.
        self.early_order = self.payment(self.buyer_promo, "freedompay", "4900.00", "KGS", 5000)
        ok, message, credited = activate_promo(self.buyer_promo, CODE.lower())
        self.buyer_promo.refresh_from_db()
        referral = CreatorReferral.objects.active_for(self.buyer_promo.pk)
        self.check(step, "-", "True «Промокод принят» credited=0 source=promo balance=0",
                   f"{ok} «{str(message)[:15]}» credited={credited} "
                   f"source={getattr(referral, 'source', 'нет')} "
                   f"balance={self.buyer_promo.token_balance}")

    def s05_refusals(self, step):
        from users.services import activate_promo, maybe_link_referrer

        ok, _message, credited = activate_promo(self.creator_user, CODE)
        own = CreatorReferral.objects.filter(user=self.creator_user).exists()
        self.check(step, "-", "свой код: False credited=0 привязки нет",
                   f"свой код: {ok} credited={credited} привязки {'нет' if not own else 'ЕСТЬ'}")

        self.inviter = self.user("inviter")
        self.ordinary = self.user("ordinary")
        maybe_link_referrer(self.request({"esai_ref": self.inviter.referral_uid}), self.ordinary)
        self.ordinary.refresh_from_db()
        bound = CreatorReferral.objects.filter(user=self.ordinary).exists()
        self.check(step, "-", f"обычная ссылка: referred_by={self.inviter.pk} привязки к креатору нет",
                   f"обычная ссылка: referred_by={self.ordinary.referred_by_id} "
                   f"привязки к креатору {'нет' if not bound else 'ЕСТЬ'}")

    def s06_freedompay_postback(self, step):
        provider = "freedompay (постбэк)"
        self.fp_postback = self.early_order
        self.credit_postback(self.fp_postback)
        self.credit_postback(self.fp_postback)      # повтор уведомления
        self.check(step, provider,
                   self.expect(("", "56.350000", "8.452500", "15.00", "kgs:chain_check", "accrued")),
                   self.facts(self.fp_postback))
        # Ещё два заказа — для возврата из кабинета (S15) и для упавшего изъятия (S15).
        small = self.expect(("", "5.635000", "0.845250", "15.00", "kgs:chain_check", "accrued"))
        self.fp_cabinet = self.kgs_purchase(self.buyer_link)
        self.check(step, provider, small, self.facts(self.fp_cabinet))
        self.fp_failed = self.kgs_purchase(self.buyer_link)
        self.check(step, provider, small, self.facts(self.fp_failed))
        self.expected_earned += Decimal("8.452500") + 2 * Decimal("0.845250")

    def s07_freedompay_reconcile(self, step):
        self.fp_reconcile = self.payment(self.buyer_link, "freedompay", "9900.00", "KGS", 10000)
        first = self.credit_reconcile(self.fp_reconcile)
        second = self.credit_reconcile(self.fp_reconcile)     # повторный проход сверки
        self.check(step, "freedompay (сверка)", "credited затем already", f"{first} затем {second}")
        self.check(step, "freedompay (сверка)",
                   self.expect(("", "113.850000", "17.077500", "15.00", "kgs:chain_check", "accrued")),
                   self.facts(self.fp_reconcile))
        self.expected_earned += Decimal("17.077500")

        # Единый QR (GoPay): то же начисление, что по вебхуку и в сверке, —
        # через единственный путь зачисления apply_state.
        from payments.gopay import service as gopay_service

        provider = "gopay (вебхук и сверка)"
        self.gp = self.payment(self.buyer_link, "gopay", "490.00", "KGS", 500, {
            "provider": "gopay", "pay_method": "elqr", "gopay": {"env": "live", "lifetime": 900}})
        self.gp_invoice = self.gopay_invoice(self.gp)
        state = self.gopay_state(self.gp, self.gp_invoice)
        first = gopay_service.apply_state(self.gp_invoice, state, source="webhook")
        second = gopay_service.apply_state(self.gp_invoice, state, source="reconcile")   # повтор
        self.check(step, provider, "credited затем already", f"{first} затем {second}")
        self.check(step, provider,
                   self.expect(("", "5.635000", "0.845250", "15.00", "kgs:chain_check", "accrued")),
                   self.facts(self.gp))
        self.expected_earned += Decimal("0.845250")

        # Тестовая среда GoPay: кредиты зачисляются (цепочку проверяет сотрудник),
        # а комиссии креатору нет. Привязку делаем, пока покупатель — обычный
        # пользователь (сотрудника привязать нельзя), и только потом повышаем:
        # тестовый платёж зачисляется лишь сотруднику.
        from users.services import maybe_link_referrer

        self.buyer_gp_test = self.user("buyer-gp-test")
        maybe_link_referrer(self.request({"esai_ref": CODE}), self.buyer_gp_test)
        self.User.objects.filter(pk=self.buyer_gp_test.pk).update(is_staff=True)
        self.buyer_gp_test.refresh_from_db()
        test_payment = self.payment(self.buyer_gp_test, "gopay", "490.00", "KGS", 500, {
            "provider": "gopay", "pay_method": "elqr", "gopay": {"env": "test", "lifetime": 900}})
        Payment.objects.filter(pk=test_payment.pk).update(is_test=True)
        test_payment.refresh_from_db()
        test_invoice = self.gopay_invoice(test_payment, env="test")
        result = gopay_service.apply_state(
            test_invoice, self.gopay_state(test_payment, test_invoice), source="webhook")
        self.check(step, "gopay (тестовый платёж)", "credited void/test_payment",
                   f"{result} {self.states(test_payment)}")

    def s08_yookassa(self, step):
        from payments import views as payment_views

        self.yk = self.payment(self.buyer_link, "yookassa", "5200.00", "RUB", 5000, {
            "provider": "yookassa", "kgs_price": "4900.00", "rate_kgs_to_rub": "1.0612",
            "yookassa_payment_id": f"yk-{self.run_id}"})
        answer = self.yookassa_answer(self.yk)
        first = payment_views.apply_yookassa_state(self.yk, answer, source="chain_check")
        payment_views.apply_yookassa_state(self.yk, answer, source="chain_check")   # повтор вебхука
        self.check(step, "yookassa", "credited", first)
        self.check(step, "yookassa",
                   self.expect(("", "56.350000", "8.452500", "15.00", "kgs_price:chain_check", "accrued")),
                   self.facts(self.yk))
        self.expected_earned += Decimal("8.452500")

    def s09_crypto(self, step):
        from payments.crypto import credit as crypto_credit

        self.crypto = self.payment(self.buyer_link, "crypto_nowpayments", "100.00", "USD", 10000,
                                   {"provider": "nowpayments", "pay_method": "crypto"})
        self.crypto_invoice = CryptoInvoice.objects.create(
            payment=self.crypto, provider="nowpayments",
            provider_invoice_id=f"chain-np-{uuid.uuid4().hex[:16]}",
            status=CryptoInvoice.STATUS_WAITING, price_amount=Decimal("100.00"),
            price_currency="USD", pay_currency="usdttrc20", pay_coin="USDT", pay_network="TRC-20",
            pay_address="chain-check-address", pay_amount=Decimal("100.5"))
        half = self.crypto_state(self.crypto, self.crypto_invoice, "partially_paid", "50.25")
        full = self.crypto_state(self.crypto, self.crypto_invoice, "finished", "100.5")
        results = [crypto_credit.apply_provider_status(self.crypto_invoice, state, source="chain_check")
                   for state in (half, full, full)]     # половина, остаток, повтор
        self.check(step, "crypto_nowpayments", "credited credited noop", " ".join(results))
        self.check(step, "crypto_nowpayments",
                   self.expect(("5000", "50.000000", "7.500000", "15.00", "usd", "accrued"),
                               ("10000", "50.000000", "7.500000", "15.00", "usd", "accrued")),
                   self.facts(self.crypto))
        self.expected_earned += 2 * Decimal("7.500000")

    def s10_stars(self, step):
        from plans.stars import withdraw_rate

        rate = withdraw_rate()

        def expected(stars: int) -> str:
            base = (Decimal(stars) * rate).quantize(Q6, rounding=ROUND_DOWN)
            amount = (base * Decimal("15.00") / 100).quantize(Q6, rounding=ROUND_DOWN)
            self.expected_earned += amount
            return self.expect(("", _q6(base), _q6(amount), "15.00", "stars_withdraw_rate", "accrued"))

        self.stars = self.payment(self.buyer_link, "telegram_stars", "3850", "XTR", 5000, {
            "provider": "telegram_stars", "pay_method": "stars", "stars": 3850})
        self.stars_invoice = self.star_invoice(self.stars, telegram_id=7_000_000_001)
        self.credit_postback(self.stars)
        self.credit_postback(self.stars)        # повтор successful_payment
        self.check(step, "telegram_stars", expected(3850), self.facts(self.stars))
        # Второй заказ — для возврата Stars у платежа без пользователя (S19).
        self.stars_orphan = self.payment(self.buyer_link, "telegram_stars", "385", "XTR", 500, {
            "provider": "telegram_stars", "pay_method": "stars", "stars": 385})
        self.stars_orphan_invoice = self.star_invoice(self.stars_orphan, telegram_id=7_000_000_001)
        self.credit_postback(self.stars_orphan)
        self.check(step, "telegram_stars", expected(385), self.facts(self.stars_orphan))

    def s11_ordinary(self, step):
        from payments.referral import referral_percent
        from plans.models import TokenTransaction

        payment = self.kgs_purchase(self.ordinary)
        self.credit_postback(payment)
        shares = list(TokenTransaction.objects.filter(
            reason="referral", delta__gt=0, meta__order_id=payment.order_id))
        self.check(step, "freedompay (обычная рефералка)",
                   f"доля: 1 строка на {500 * referral_percent() // 100} кредитов пригласившему "
                   f"{self.inviter.pk}, комиссий 0",
                   f"доля: {len(shares)} строка на {sum(int(s.delta) for s in shares)} кредитов "
                   f"пригласившему {shares[0].user_id if shares else None}, комиссий "
                   f"{CreatorCommission.objects.filter(payment=payment).count()}")

    def s12_balance(self, step):
        total = self.expected_earned
        now = balance.summary(self.creator)
        later = balance.summary(self.creator, now=timezone.now() + timedelta(days=15))
        self.check(step, "-", f"сейчас: earned={_q6(total)} available=0.000000 pending={_q6(total)}",
                   f"сейчас: earned={_q6(now.earned)} available={_q6(now.available)} "
                   f"pending={_q6(now.pending)}")
        self.check(step, "-", f"через 15 дней: available={_q6(total)} pending=0.000000",
                   f"через 15 дней: available={_q6(later.available)} pending={_q6(later.pending)}")

    def s13_level(self, step):
        from creators import program

        before = set(CreatorCommission.objects.filter(creator=self.creator)
                     .values_list("pk", flat=True))
        program.set_level(self.creator, "ambassador", actor=self.admin, reason="creators_chain_check")
        self.after_level = self.kgs_purchase(self.buyer_link)
        self.check(step, "freedompay (постбэк)",
                   self.expect(("", "5.635000", "1.127000", "20.00", "kgs:chain_check", "accrued")),
                   self.facts(self.after_level))
        kept = set(CreatorCommission.objects.filter(pk__in=before)
                   .values_list("percent", "level_key"))
        self.check(step, "-", "прежние комиссии: {(15.00, creator_pro)}",
                   "прежние комиссии: {" + ", ".join(f"({p:.2f}, {k})" for p, k in sorted(kept)) + "}")

    def s14_withdrawal(self, step):
        # Холд «прошёл»: сдвигаем дату доступности в прошлое.
        CreatorCommission.objects.filter(creator=self.creator).update(
            available_at=timezone.now() - timedelta(days=1))
        self.check(step, "-", "неверный адрес: address_invalid",
                   "неверный адрес: " + _refusal(lambda: withdrawals.request_withdrawal(
                       self.creator, "10", address=BAD_ADDRESS)))
        row = withdrawals.request_withdrawal(self.creator, "10", address=VALID_ADDRESS)
        self.check(step, "-", "заявка 10.00 USDT review", f"заявка {row.amount_usdt} USDT {row.status}")
        self.check(step, "-", "вторая заявка: withdrawal_open",
                   "вторая заявка: " + _refusal(lambda: withdrawals.request_withdrawal(
                       self.creator, "10", address=VALID_ADDRESS)))
        withdrawals.approve(row.pk, actor=self.admin)
        self.check(step, "-", "TXID из 63 символов: txid_invalid",
                   "TXID из 63 символов: " + _refusal(lambda: withdrawals.mark_paid(
                       row.pk, actor=self.admin, txid="a" * 63)))
        txid = uuid.uuid4().hex + uuid.uuid4().hex
        row = withdrawals.mark_paid(row.pk, actor=self.admin, txid="0x" + txid.upper())
        summary = balance.summary(self.creator)
        self.check(step, "-", f"вывод paid txid={txid} paid=10.00",
                   f"вывод {row.status} txid={row.txid} paid={balance.as_json(summary)['paid']}")

    def s15_refund_freedompay(self, step):
        from payments import views as payment_views

        provider = "freedompay (сигнал возврата)"
        self.refund_postback(self.fp_postback)
        first = self.states(self.fp_postback)
        self.refund_postback(self.fp_postback)      # повтор возврата
        self.check(step, provider, "reversed/refund:freedompay, повтор без изменений",
                   f"{first}, повтор " + ("без изменений" if self.states(self.fp_postback) == first
                                           else "ИЗМЕНИЛ"))
        self.buyer_promo.refresh_from_db()
        self.check(step, provider, "кредиты покупателя изъяты: баланс 0",
                   f"кредиты покупателя изъяты: баланс {self.buyer_promo.token_balance}")

        provider = "freedompay (возврат в кабинете)"
        self.buyer_link.refresh_from_db()
        credits_before = self.buyer_link.token_balance
        status = {"pg_status": "ok", "pg_transaction_status": "refunded"}
        first = payment_views.apply_freedompay_refund(self.fp_cabinet, status, source="chain_check")
        second = payment_views.apply_freedompay_refund(self.fp_cabinet, status, source="chain_check")
        self.buyer_link.refresh_from_db()
        self.check(step, provider, "refunded затем already: reversed/refund:freedompay, кредиты на месте",
                   f"{first} затем {second}: {self.states(self.fp_cabinet)}, кредиты "
                   + ("на месте" if self.buyer_link.token_balance == credits_before else "ИЗЪЯТЫ"))

        provider = "freedompay (изъятие упало)"
        # Состояние, которое оставляет обработчик возврата, когда изъятие кредитов
        # упало: отметка об ошибке есть, комиссия ещё начислена.
        Payment.objects.filter(pk=self.fp_failed.pk).update(
            success=False, error="token_clawback_failed:chain_check")
        before = self.states(self.fp_failed)
        result = tasks.commission_safety_net()
        self.check(step, provider, "accrued/ -> страховка ok -> reversed/refund:clawback_failed",
                   f"{before} -> страховка {result.get('status')} -> {self.states(self.fp_failed)}")

    def s16_refund_admin(self, step):
        result = commission.mark_payment_refunded(
            self.fp_reconcile.pk, kind="refund", actor=self.admin,
            reason="creators_chain_check", clawback_credits=True)
        repeat = _refusal(lambda: commission.mark_payment_refunded(
            self.fp_reconcile.pk, kind="refund", actor=self.admin,
            reason="creators_chain_check", clawback_credits=True))
        self.check(step, "freedompay (отметка администратора)",
                   "reversed=1 изъято=10000 reversed/refund:admin, повтор: already_marked",
                   f"reversed={result['reversed']} изъято={result['clawback_debited']} "
                   f"{self.states(self.fp_reconcile)}, повтор: {repeat}")

        # Единый QR: возврата через API у GoPay нет — только отметка администратора.
        # После неё GoPay по-прежнему отвечает «оплачен», и сверка не должна ни
        # зачислить заказ заново, ни вернуть ему success.
        from payments.gopay import service as gopay_service

        result = commission.mark_payment_refunded(
            self.gp.pk, kind="refund", actor=self.admin,
            reason="creators_chain_check", clawback_credits=True)
        again = gopay_service.apply_state(
            self.gp_invoice, self.gopay_state(self.gp, self.gp_invoice), source="reconcile")
        self.gp.refresh_from_db()
        self.check(step, "gopay (отметка администратора)",
                   "reversed=1 изъято=500 reversed/refund:admin, сверка после: already success=False",
                   f"reversed={result['reversed']} изъято={result['clawback_debited']} "
                   f"{self.states(self.gp)}, сверка после: {again} success={self.gp.success}")

    def s17_refund_yookassa(self, step):
        from payments import views as payment_views

        answer = self.yookassa_answer(self.yk, refunded_amount={"value": "5200.00", "currency": "RUB"})
        first = payment_views.apply_yookassa_refund(self.yk, answer, source="chain_check")
        second = payment_views.apply_yookassa_refund(self.yk, answer, source="chain_check")
        self.check(step, "yookassa", "refunded затем already: reversed/refund:yookassa",
                   f"{first} затем {second}: {self.states(self.yk)}")

    def s18_refund_crypto(self, step):
        from payments.crypto import credit as crypto_credit

        refunded = self.crypto_state(self.crypto, self.crypto_invoice, "refunded", "100.5")
        crypto_credit.apply_provider_status(self.crypto_invoice, refunded, source="chain_check")
        first = self.states(self.crypto)
        crypto_credit.apply_provider_status(self.crypto_invoice, refunded, source="chain_check")
        self.check(step, "crypto_nowpayments",
                   "reversed/refund:crypto reversed/refund:crypto, повтор без изменений",
                   f"{first}, повтор " + ("без изменений" if self.states(self.crypto) == first
                                           else "ИЗМЕНИЛ"))

    def s19_refund_stars(self, step):
        from botapi import stars as stars_service

        charge = self.stars_invoice.telegram_payment_charge_id
        first = stars_service.mark_refunded(charge_id=charge, reason="creators_chain_check")
        second = stars_service.mark_refunded(charge_id=charge, reason="creators_chain_check")
        self.check(step, "telegram_stars",
                   "refunded затем already_refunded: reversed/refund:telegram_stars",
                   f"{first.get('status')} затем {second.get('status')}: {self.states(self.stars)}")

        # Покупателя у платежа уже нет (аккаунт удалён), счёт помечен возвращённым:
        # хук оплаты сюда не доходит, комиссию отменяет страховка.
        Payment.objects.filter(pk=self.stars_orphan.pk).update(user=None)
        StarInvoice.objects.filter(pk=self.stars_orphan_invoice.pk).update(
            status=StarInvoice.STATUS_REFUNDED, refunded_at=timezone.now())
        before = self.states(self.stars_orphan)
        result = tasks.commission_safety_net()
        self.check(step, "telegram_stars (без пользователя)",
                   "accrued/ -> страховка ok -> reversed/refund:stars",
                   f"{before} -> страховка {result.get('status')} -> {self.states(self.stars_orphan)}")

    def s20_debt(self, step):
        future = timezone.now() + timedelta(days=15)
        now = balance.summary(self.creator)
        # Выплачено 10, а из начисленного осталась одна комиссия шага S13.
        self.check(step, "-", "available_raw=-8.873000 debt=8.873000 available=0.000000",
                   f"available_raw={_q6(now.available_raw)} debt={_q6(now.debt)} "
                   f"available={_q6(now.available)}")
        self.check(step, "-", "новая заявка: insufficient_available",
                   "новая заявка: " + _refusal(lambda: withdrawals.request_withdrawal(
                       self.creator, "10", address=VALID_ADDRESS)))
        before = balance.summary(self.creator, now=future).debt
        self.kgs_purchase(self.buyer_link)
        after = balance.summary(self.creator, now=future).debt
        self.check(step, "freedompay (постбэк)", "долг после холда: 8.873000 -> 7.746000",
                   f"долг после холда: {_q6(before)} -> {_q6(after)}")

    def s21_blocked(self, step):
        from creators import program

        program.block(self.creator, actor=self.admin, reason="creators_chain_check")
        payment = self.kgs_purchase(self.buyer_link)
        self.check(step, "freedompay (постбэк)", "held/creator_blocked", self.states(payment))
        self.check(step, "-", "заявка на вывод: creator_blocked",
                   "заявка на вывод: " + _refusal(lambda: withdrawals.request_withdrawal(
                       self.creator, "10", address=VALID_ADDRESS)))
        row = CreatorCommission.objects.get(payment=payment)
        commission.release(row.pk, actor=self.admin, reason="creators_chain_check")
        self.check(step, "-", "после release: accrued/released",
                   f"после release: {self.states(payment)}")

    def s22_checks(self, step):
        failed = [v for v in checks.run() if v.level == "fail"]
        self.check(step, "-", "creators_check: нарушений 0",
                   "creators_check: нарушений " + (
                       "0" if not failed else
                       f"{len(failed)} — " + "; ".join(f"{v.code} {v.detail}" for v in failed)))


class Command(BaseCommand):
    help = "Проверка цепочки EsAI Creators на подставных платежах (настоящие пути начисления)."

    def add_arguments(self, parser):
        parser.add_argument("--rollback", action="store_true",
                            help="Работать в текущей базе внутри транзакции и откатить её.")
        parser.add_argument("--json", action="store_true", dest="as_json",
                            help="Вывести результат в JSON.")

    def handle(self, *args, **options):
        # Свой кэш на время прогона. get_runtime кэширует на 30 с каждый ключ,
        # включая «ключа нет»: на временной базе прогон записал бы «нет» в
        # общий боевой кэш (и рабочие процессы полминуты жили бы на значениях по
        # умолчанию), а боевые значения, наоборот, просочились бы в прогон.
        with override_settings(CACHES=CACHES):
            cache.clear()
            rows = self._rolled_back() if options.get("rollback") else self._scratch()

        failed = [row for row in rows if row["result"] != "PASS"]
        if options.get("as_json"):
            self.stdout.write(json.dumps({"ok": not failed, "rows": rows}, ensure_ascii=False))
        else:
            self._print(rows)
            self.stdout.write(f"Итог: {len(rows) - len(failed)} PASS, {len(failed)} FAIL")
        if failed:
            sys.exit(1)

    def _scratch(self) -> list[dict]:
        old_name = connection.settings_dict["NAME"]
        connection.creation.create_test_db(verbosity=0, autoclobber=True, serialize=False)
        try:
            return self._run()
        finally:
            connection.creation.destroy_test_db(old_name, verbosity=0)

    def _rolled_back(self) -> list[dict]:
        with transaction.atomic():
            try:
                return self._run()
            finally:
                transaction.set_rollback(True)

    def _run(self) -> list[dict]:
        fp_status = MagicMock(return_value={})
        with ExitStack() as stack:
            # Режим подменяется функцией, а не настройкой: значение из админки
            # (creators_mode) сильнее CREATORS_MODE из окружения.
            stack.enter_context(patch("creators.flags.mode", return_value="on"))
            stack.enter_context(patch("creators.flags.hold_days", return_value=14))
            stack.enter_context(patch("creators.flags.payouts_enabled", return_value=True))
            stack.enter_context(patch("creators.commission.kgs_rate",
                                      return_value=(RATE, "chain_check")))
            # Ничего не уходит наружу: уведомления, письма, запросы к провайдерам.
            stack.enter_context(patch("creators.notify.emit"))
            stack.enter_context(patch("botapi.tasks.notify"))
            stack.enter_context(patch("payments.views._notify_balance_topup"))
            stack.enter_context(patch("payments.tasks.fetch_payment_status", fp_status))
            stack.enter_context(patch("payments.yookassa.fetch_payment",
                                      side_effect=RuntimeError("creators_chain_check: сеть закрыта")))
            stack.enter_context(patch("payments.gopay.client.requests.post",
                                      side_effect=RuntimeError("creators_chain_check: сеть закрыта")))
            # Под settings_sqlitetest миграции выключены: уровни засевает не 0002_seed_levels.
            levels.ensure_levels()
            return Chain(fp_status).run()

    def _print(self, rows: list[dict]) -> None:
        columns = ("step", "provider", "expected", "actual", "result")
        self.stdout.write("step | provider | expected | actual | PASS/FAIL")
        for row in rows:
            self.stdout.write(" | ".join(str(row[name]) for name in columns))
