"""Фабрики и базовые классы тестов программы Creators.

Простые функции без factory_boy (его нет в зависимостях) и БЕЗ вызовов
сервисов: строки создаются напрямую через ORM, чтобы тест одного модуля не
зависел от готовности другого.

    creator = make_creator(code="TORA20")              # активный, уровень creator (10%)
    buyer = make_user()
    make_referral(creator, buyer)
    payment = make_payment(buyer, amount="1000.00")    # FreedomPay, KGS
    make_commission(creator, payment, available_in_days=-1)   # уже доступна к выводу

Каждый класс тестов наследует CreatorsTestCase — это обязательно, а не
условность. Кэш LocMem живёт в словаре модуля: его не чистят ни
override_settings, ни откат транзакции теста. Без cache.clear() между
классами текли бы режим программы (кэш get_runtime на 30 с), счётчик неверных
промокодов, защита от двойного начисления кредитов и счётчики троттлинга.

Данные фабрик проходят сверку creators_check: статус, уровень, ручная привязка
и вывод сопровождаются строкой журнала (logged=True по умолчанию).
"""
from __future__ import annotations

import itertools
import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from audit.models import AdminActionLog
from payments.models import Payment

from .. import levels
from ..models import (
    Creator,
    CreatorCode,
    CreatorCommission,
    CreatorReferral,
    CreatorWithdrawal,
)

LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                      "LOCATION": "creators-tests"}}

VALID_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
VALID_TRC20_2 = "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7"
VALID_TXID = "a" * 64

FACTORY_ADMIN_EMAIL = "creators-factory-admin@example.com"

Q2 = Decimal("0.01")
Q8 = Decimal("0.00000001")

# Валюта платежа по умолчанию — как её пишет каждый провайдер.
_CURRENCY = {"freedompay": "KGS", "gopay": "KGS", "yookassa": "RUB", "telegram_stars": "XTR"}

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


# ------------------------------------------------------------- базовые классы

@override_settings(CREATORS_MODE="on", CACHES=LOCMEM)
class CreatorsTestCase(TestCase):
    """База всех тестов программы. Тест рубильника переопределяет CREATORS_MODE ещё раз."""

    def setUp(self):
        super().setUp()
        # Режим, счётчик промокодов, защита начисления, троттлинг — всё в кэше.
        cache.clear()
        # Миграции под settings_sqlitetest выключены: 0002_seed_levels не выполнялась.
        levels.ensure_levels()


@override_settings(CREATORS_MODE="on", CACHES=LOCMEM)
class CreatorsTransactionTestCase(TransactionTestCase):
    """Для тестов с двумя потоками (только Postgres: SQLite блокировки строк не держит)."""

    def setUp(self):
        super().setUp()
        cache.clear()
        levels.ensure_levels()


# ----------------------------------------------------------------------- люди

def make_user(email=None, *, staff=False, superuser=False, paid=False, balance=0,
              joined_ago=None, telegram_uid=None, **extra):
    """Пользователь.

    superuser=True делает его и сотрудником (как create_superuser).
    joined_ago — timedelta или число часов: сдвигает date_joined в прошлое.
    telegram_uid — создаёт привязку SocialAccount(provider="telegram").
    """
    User = get_user_model()
    user = User.objects.create_user(
        email=email or f"cr{_n()}@example.com", password="x",
        is_staff=bool(staff or superuser), is_superuser=bool(superuser), **extra)
    fields = []
    if balance:
        user.token_balance = int(balance)
        fields.append("token_balance")
    if paid:
        user.is_paid = True
        user.first_paid_at = timezone.now()
        fields += ["is_paid", "first_paid_at"]
    if joined_ago is not None:
        if not isinstance(joined_ago, timedelta):
            joined_ago = timedelta(hours=float(joined_ago))
        user.date_joined = timezone.now() - joined_ago
        fields.append("date_joined")
    if fields:
        user.save(update_fields=fields)
    if telegram_uid is not None:
        from allauth.socialaccount.models import SocialAccount

        SocialAccount.objects.create(user=user, provider="telegram", uid=str(telegram_uid))
    return user


def factory_admin():
    """Главный администратор, от имени которого фабрики пишут журнал."""
    User = get_user_model()
    admin = User.objects.filter(email=FACTORY_ADMIN_EMAIL).first()
    if admin is None:
        admin = User.objects.create_user(email=FACTORY_ADMIN_EMAIL, password="x",
                                         is_staff=True, is_superuser=True)
    return admin


def _log(action, *, target=None, creator=None, before=None, after=None, reason="factory"):
    return AdminActionLog.objects.create(
        actor=factory_admin(), action=action,
        target_type=f"{target._meta.app_label}.{target._meta.model_name}" if target else "",
        target_id=str(target.pk) if target else "",
        creator=creator, before=before or {}, after=after or {}, reason=reason)


# ------------------------------------------------------------------- программа

def make_creator(user=None, *, level="creator", status="active", code=None, lang="ru",
                 logged=True, **extra) -> Creator:
    """Креатор без заявки. code — его основной промокод.

    logged=True пишет в журнал то, что написали бы сервисы: одобрение с уровнем
    (application.approve, after={"level": ...}) и, для заблокированного,
    creator.block — иначе сверка I9 считала бы данные фабрики нарушением.
    """
    levels.ensure_levels()
    user = user or make_user()
    fields = {"display_name": f"Creator {_n()}", "lang": lang}
    if status == "blocked":
        fields.update(blocked_at=timezone.now(), blocked_reason="factory")
    fields.update(extra)
    creator = Creator.objects.create(user=user, level=levels.get_level(level), status=status,
                                     **fields)
    if code:
        CreatorCode.objects.create(code=code, creator=creator, is_primary=True, is_active=True,
                                   created_by=user)
    if logged:
        _log("application.approve", target=creator, creator=creator, after={"level": level})
        if status == "blocked":
            _log("creator.block", target=creator, creator=creator,
                 before={"status": "active"}, after={"status": "blocked"})
    return creator


def make_referral(creator, user=None, *, source="link", bound_at=None,
                  suspect=False) -> CreatorReferral:
    """Действующая привязка пользователя к креатору (code_used — основной код креатора).

    source="admin" сопровождается строкой журнала referral.rebind (сверка I8).
    """
    user = user or make_user()
    code = (CreatorCode.objects.filter(creator=creator, is_primary=True)
            .values_list("code", flat=True).first() or "")
    by_admin = source == "admin"
    referral = CreatorReferral.objects.create(
        user=user, creator=creator, source=source, code_used="" if by_admin else code,
        bound_at=bound_at or timezone.now(), bound_by=factory_admin() if by_admin else None,
        suspect=suspect, flags={"reasons": ["factory"]} if suspect else {})
    if by_admin:
        _log("referral.rebind", target=user, creator=creator,
             before={"creator_id": None}, after={"creator_id": creator.pk})
    return referral


# --------------------------------------------------------------------- деньги

def make_payment(user, *, provider="freedompay", amount="490.00", currency=None, tokens=500,
                 bonus=0, order_id=None, is_test=False, created_at=None, success=True,
                 **request_extra) -> Payment:
    """Платёж за пакет кредитов — как его создаёт оформление заказа.

    request["token_purchase"] заполнен; token_purchase=None убирает его
    (старое списание с сохранённой карты). Остальные ключевые слова попадают в
    request поверх значений по умолчанию (например kgs_price="490.00").
    Валюта по провайдеру: FreedomPay и GoPay (единый QR) — KGS, ЮKassa — RUB,
    крипта — USD, Stars — XTR.
    Кредиты фабрика не начисляет — для этого credit_purchase().
    """
    amount = Decimal(str(amount))
    is_crypto = str(provider).startswith("crypto_")
    currency = currency or ("USD" if is_crypto else _CURRENCY.get(provider, "USD"))
    request = {"token_purchase": {"package_id": 1, "tokens": int(tokens),
                                  "bonus_tokens": int(bonus)}}
    if provider == "yookassa":
        # Цена пакета в сомах и витринный курс: сумма в рублях = kgs_price × курс.
        request.update(provider="yookassa", kgs_price=str(amount), rate_kgs_to_rub="1")
    elif is_crypto:
        rate = Decimal(str(settings.CURRENCY_KGS_TO_USD_RATE))
        request.update(provider=provider, pay_method="crypto",
                       kgs_price=str((amount / rate).quantize(Q2)),
                       rate_kgs_to_usd=str(rate), amount_usd=str(amount))
    elif provider == "telegram_stars":
        request.update(provider="telegram_stars", pay_method="stars", stars=int(amount))
    elif provider == "gopay":
        request.update(provider="gopay", pay_method="elqr")
    request.update(request_extra)
    if request.get("token_purchase") is None:
        request.pop("token_purchase", None)

    payment = Payment.objects.create(
        user=user, provider=provider, amount=amount, currency=currency,
        order_id=order_id or f"tokpkg-{getattr(user, 'pk', 0) or 0}-1-{uuid.uuid4().hex[:10]}",
        description="Token package purchase #1 (test)", is_test=is_test, success=success,
        request=request, response={})
    if created_at is not None:
        # auto_now_add не даёт задать дату при создании.
        Payment.objects.filter(pk=payment.pk).update(created_at=created_at)
        payment.created_at = created_at
    return payment


def make_commission(creator, payment=None, *, buyer=None, amount="1.500000", base="10.000000",
                    status="accrued", available_in_days=14, part="",
                    reason="") -> CreatorCommission:
    """Строка комиссии. Платёж и покупатель создаются, если не переданы.

    Процент в строке считается из amount и base (1.5 от 10 — это 15.00), чтобы
    строка сходилась сама с собой (сверка I2) при любом уровне креатора;
    level_key — текущий уровень креатора. available_in_days — когда комиссия
    выходит из холда: отрицательное число — уже вышла, None — без даты.
    Для void и для available_in_days=None дата не ставится.
    """
    amount, base = Decimal(str(amount)), Decimal(str(base))
    if payment is None:
        buyer = buyer or make_user()
        payment = make_payment(buyer)
    buyer = buyer or payment.user or make_user()
    paid = Decimal(str(payment.amount or 0))
    percent = ((amount / base * 100).quantize(Q2, rounding=ROUND_HALF_UP)
               if base > 0 and amount > 0 else creator.level.percent)
    now = timezone.now()
    available_at = None
    if status != "void" and available_in_days is not None:
        available_at = now + timedelta(days=available_in_days)
    return CreatorCommission.objects.create(
        creator=creator,
        referral=CreatorReferral.objects.filter(user=buyer, creator=creator).order_by("-id").first(),
        buyer=buyer, buyer_pk=buyer.pk, payment=payment, part=part,
        order_id=payment.order_id or "", provider=payment.provider,
        paid_amount=paid, paid_currency=payment.currency,
        rate_to_usd=(base / paid).quantize(Q8) if paid > 0 else Decimal("0"),
        rate_source="factory", base_usd=base, level_key=creator.level.key, percent=percent,
        amount_usdt=amount, status=status, reason=reason, available_at=available_at,
        reversed_at=now if status == "reversed" else None)


def make_withdrawal(creator, amount="10.00", *, status="review", txid="",
                    logged=True) -> CreatorWithdrawal:
    """Заявка на вывод в нужном статусе.

    Адрес — адрес креатора или VALID_TRC20. Для paid без txid подставляется
    уникальный (два «выплачено» с одним TXID база не примет). logged=True пишет
    журнал переходов (approve / mark_paid / reject), как это делают сервисы.
    """
    now = timezone.now()
    fields = {}
    if status in ("approved", "paid"):
        fields.update(approved_by=factory_admin(), approved_at=now)
    if status == "paid":
        txid = txid or f"{_n():064x}"
        fields.update(paid_by=factory_admin(), paid_at=now)
    if status == "rejected":
        fields.update(rejected_by=factory_admin(), rejected_at=now, reject_reason="factory")
    withdrawal = CreatorWithdrawal.objects.create(
        creator=creator, amount_usdt=Decimal(str(amount)),
        address=creator.payout_address or VALID_TRC20, status=status, txid=txid, **fields)
    if logged:
        if status in ("approved", "paid"):
            _log("withdrawal.approve", target=withdrawal, creator=creator,
                 before={"status": "review"}, after={"status": "approved"})
        if status == "paid":
            _log("withdrawal.mark_paid", target=withdrawal, creator=creator,
                 before={"status": "approved"}, after={"status": "paid", "txid": txid})
        if status == "rejected":
            _log("withdrawal.reject", target=withdrawal, creator=creator,
                 before={"status": "review"}, after={"status": "rejected"})
    return withdrawal


def credit_purchase(payment, *, credited=None, idem="") -> None:
    """Запись леджера о покупке — только она, без хуков оплаты.

    credited — сколько кредитов зачислить (по умолчанию весь пакет с бонусом);
    idem — часть крипто-оплаты (накопленные кредиты строкой), как в meta настоящей покупки.
    """
    from plans.wallet import credit_tokens

    info = (payment.request or {}).get("token_purchase") or {}
    if credited is None:
        credited = int(info.get("tokens") or 0) + int(info.get("bonus_tokens") or 0)
    meta = {"order_id": payment.order_id, "package_id": info.get("package_id"),
            "tokens": int(info.get("tokens") or 0),
            "bonus_tokens": int(info.get("bonus_tokens") or 0)}
    if idem:
        meta["idem"] = str(idem)
    credit_tokens(payment.user, int(credited), "purchase", meta=meta)
