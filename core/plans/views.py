import logging
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import generics, permissions
from rest_framework.response import Response
from django.views.decorators.vary import vary_on_headers
from rest_framework.exceptions import NotFound

from .models import (
    Plan, UserSubscription, AddonPurchase, SubscriptionStatus, PaymentStatus,
    TokenPackage, TokenTransaction, ExitDiscountOffer,
)
from .serializers import (
    PlanSerializer, UserSubscriptionSerializer,
    GenerationUsageSerializer, AddonPurchaseSerializer,
    TokenPackageSerializer, TokenTransactionSerializer,
)
from .services import get_currency_per_usd_map_cached
from .services import plan_cycle_days
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as drf_status
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.utils import timezone
from django.conf import settings
import uuid
import requests
from datetime import timedelta
from users.models import User, UserCardBind
from django.db import transaction
from payments.freedompay import FreedomPay, FreedomPayError, make_api_signature
from decimal import Decimal
from core.langutils import request_lang


@method_decorator(cache_page(60), name="dispatch")               # page cache
@method_decorator(vary_on_headers("Accept-Language"), name="dispatch")  # vary by i18n header (если нужно)
class PlanListView(generics.ListAPIView):
    """Public plans for pricing page."""
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer

    ALLOWED_PERIODS = {"weekly", "monthly", "yearly"}

    def get_queryset(self):
        qs = (
            Plan.objects
            .filter(is_active=True)
            .order_by("sort_order", "id")
            .select_related(None)
        )
        period = self.request.query_params.get("period")
        if period in self.ALLOWED_PERIODS:
            qs = qs.filter(period=period)
        return qs

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        # Preload RUB/KGS once; serializer не дергает БД повторно
        ctx["currency_per_usd"] = get_currency_per_usd_map_cached(["RUB", "KGS"], timeout=300)
        return ctx


class PlanRetrieveView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = PlanSerializer
    queryset = Plan.objects.filter(is_active=True).order_by("sort_order", "id")


class MeSubscriptionView(generics.GenericAPIView):
    """Current active subscription for the authenticated user."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSubscriptionSerializer

    def get(self, request, *args, **kwargs):
        sub = (UserSubscription.objects
               .select_related("plan")
               .select_related("usage")
               .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
               .order_by("-start_date")
               .first())
        if not sub:
            raise NotFound("Active subscription not found.")
        return Response(self.get_serializer(sub).data)


class MeUsageView(APIView):
    """Легаси-эндпоинт подписочного usage снят (Vokalo). Отвечает 410."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response({"detail": "subscriptions_deprecated"}, status=410)


class MeAddonsView(APIView):
    """Легаси-эндпоинт подписочных аддонов снят (Vokalo). Отвечает 410."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response({"detail": "subscriptions_deprecated"}, status=410)


class UnsubscribeView(APIView):
    """Легаси-отписка снята (Vokalo). Отвечает 410."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        return Response({"detail": "subscriptions_deprecated"}, status=410)


class ResumeSubscriptionView(APIView):
    """Легаси-возобновление подписки снято (Vokalo). Отвечает 410."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        return Response({"detail": "subscriptions_deprecated"}, status=410)


class ActivatePlanView(APIView):
    """Легаси-активация подписок Vokalo снята.

    Подписочная модель заменена на pay-as-you-go токены, поэтому эндпоинт
    больше не создаёт подписку и не списывает деньги — он отвечает 410 Gone.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, plan_id: int):
        return Response({"detail": "subscriptions_deprecated"}, status=410)

    def _legacy_post(self, request, plan_id: int):
        # Current active subscription (may be for a different plan)
        existing = (UserSubscription.objects
                    .select_related("plan")
                    .filter(user=request.user, status=SubscriptionStatus.ACTIVE)
                    .order_by("-start_date")
                    .first())

        # Plan must exist and be active
        try:
            plan = Plan.objects.get(pk=plan_id, is_active=True)
        except Plan.DoesNotExist:
            return Response({"message": "plan_not_found"}, status=404)

        u: User = request.user
        now = timezone.now()

        # Paid plan + linked card => charge first, then switch/activate.
        # This prevents granting new limits without successful payment.
        charged_now = False
        price_amount = Decimal(str(getattr(plan, "price_amount", 0) or 0))
        is_paid_plan = (not plan.is_free) and price_amount > 0
        card = UserCardBind.objects.filter(user=u).order_by("-created_at").first()
        if is_paid_plan and card:
            card_token = (card.card_token or "").strip()
            if not card_token:
                return Response({"message": "no_pay_token"}, status=400)
            try:
                fp = FreedomPay(u)
                order_id = f"plan-switch-{u.id}-{uuid.uuid4().hex[:10]}"
                charge_resp = fp.charge(
                    amount=price_amount,
                    currency="USD",
                    order_id=order_id,
                    description=f"Plan switch to #{plan.id} for user #{u.id}",
                    card_token=card_token,
                    test=False,
                )
                status_text = str((charge_resp or {}).get("pg_status") or "").lower()
                if status_text != "ok":
                    return Response({"message": "provider_declined"}, status=400)
                charged_now = True
            except FreedomPayError as exc:
                log = logging.getLogger("plans")
                if exc.is_provider_decline:
                    log.warning(
                        "plan_switch_charge_declined user=%s plan=%s order=%s code=%s status=%s desc=%s response=%s",
                        u.id,
                        plan.id,
                        order_id,
                        exc.code,
                        exc.status,
                        exc.description,
                        exc.response,
                    )
                    return Response({"message": "provider_declined"}, status=400)
                log.exception(
                    "plan_switch_charge_failed user=%s plan=%s order=%s",
                    u.id,
                    plan.id,
                    order_id,
                )
                return Response({"message": "provider_error"}, status=502)
            except Exception:
                logging.getLogger("plans").exception(
                    "plan_switch_charge_failed user=%s plan=%s", u.id, plan.id
                )
                return Response({"message": "provider_error"}, status=502)

        # Switch and activate new plan in a transaction
        from .models import GenerationUsage
        with transaction.atomic():
            # If already on this plan, keep behavior as 'already_active'
            if existing and existing.plan_id == plan.id:
                if not existing.end_date:
                    existing.start_date = now
                    existing.end_date = now + timedelta(days=plan_cycle_days(plan.period))
                    existing.save(update_fields=["start_date", "end_date"])
                return Response({"message": "already_active"}, status=400)

            # If switching from another active plan: rollover leftovers to bonus and deactivate old
            if existing and existing.plan_id != plan.id:
                user_locked = type(u).objects.select_for_update().get(pk=u.pk)
                usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=existing)
                old_plan = existing.plan
                if old_plan.text_limit and (usage.texts_left or 0) > 0:
                    user_locked.bonus_texts = (user_locked.bonus_texts or 0) + int(usage.texts_left)
                if old_plan.image_limit and (usage.images_left or 0) > 0:
                    user_locked.bonus_images = (user_locked.bonus_images or 0) + int(usage.images_left)
                if old_plan.song_limit and (usage.songs_left or 0) > 0:
                    user_locked.bonus_songs = (user_locked.bonus_songs or 0) + int(usage.songs_left)
                if old_plan.music_limit and (usage.music_left or 0) > 0:
                    user_locked.bonus_music = (user_locked.bonus_music or 0) + int(usage.music_left)
                user_locked.save(update_fields=["bonus_texts", "bonus_images", "bonus_songs", "bonus_music"])
                existing.status = SubscriptionStatus.INACTIVE
                existing.save(update_fields=["status"])
                logging.getLogger("plans").info(
                    "subscription_switched user=%s from_sub=%s from_plan=%s to_plan=%s",
                    u.id, existing.id, old_plan.id, plan.id,
                )

            # Create subscription and initialize usage counters for the new plan
            now = timezone.now()
            sub = UserSubscription.objects.create(
                user=u,
                plan=plan,
                start_date=now,
                end_date=now + timedelta(days=plan_cycle_days(plan.period)),
                status=SubscriptionStatus.ACTIVE,
                payment_status=PaymentStatus.PAID if charged_now else PaymentStatus.UNPAID,
                payment_date=now if charged_now else None,
            )
            GenerationUsage.objects.get_or_create(
                subscription=sub,
                defaults={
                    "songs_left": int(plan.song_limit or 0),
                    "music_left": int(plan.music_limit or 0),
                    "texts_left": int(plan.text_limit or 0),
                    "images_left": int(plan.image_limit or 0),
                },
            )
        
        resp = UserSubscriptionSerializer(sub).data
        logging.getLogger("plans").info(
            "subscription_created user=%s sub_id=%s plan_id=%s end_date=%s",
            request.user.id, sub.id, plan.id, sub.end_date)

        return Response(resp, status=200)


# =========================================================================
# Pay-as-you-go токен-эндпоинты
# =========================================================================


class TokenBalanceView(APIView):
    """GET /api/plans/balance/ — текущий баланс токенов пользователя.

    Помимо баланса возвращает тир (`tier`) и флаг `is_paid`, чтобы фронт знал,
    показывать ли пэйвол/замочки на премиум-моделях (ТЗ 4.1).
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .tiers import user_tier

        balance = int(getattr(request.user, "token_balance", 0) or 0)
        return Response(
            {
                "balance_tokens": balance,
                "tier": user_tier(request.user),
                "is_paid": bool(getattr(request.user, "is_paid", False)),
            },
            status=200,
        )


class TokenPackageListView(generics.ListAPIView):
    """GET /api/plans/packages/ — публичный список активных пакетов токенов."""
    permission_classes = [permissions.AllowAny]
    serializer_class = TokenPackageSerializer

    def get_queryset(self):
        return TokenPackage.objects.filter(is_active=True).order_by("sort_order", "id")

    def get_serializer_context(self):
        # Название и подпись пакета хранятся в базе на трёх языках; какой
        # показать, решает витрина (см. core/langutils).
        ctx = super().get_serializer_context()
        ctx["lang"] = request_lang(self.request)
        return ctx


class TokenPackageValueListView(APIView):
    """GET /api/plans/packages/value/ — публичный расчёт "на что хватит" пакета.

    Фундамент для калькулятора на сайте: для каждого активного пакета
    возвращает базовые поля + оценку количества единиц результата
    (сообщений/картинок/видео/страниц) на эталонных моделях
    (plans/credit_value.py). Если для какой-то категории эталонная модель не
    настроена/неактивна — категория просто отсутствует в value у ВСЕХ
    пакетов (см. логи WARNING), но ответ всё равно 200 с остальными данными.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from .credit_value import compute_all_packages_value

        try:
            packages = compute_all_packages_value(request_lang(request))
        except Exception:
            logging.getLogger(__name__).exception(
                "TokenPackageValueListView: compute_all_packages_value failed")
            packages = []
        return Response({"packages": packages})


class CurrencyRateView(APIView):
    """GET /api/plans/currency-rate/ — публично, без авторизации.

    Витринный курс KGS -> RUB для переключателя валют (задача клиента: ЮKassa
    попросила показывать цены и в рублях, next/src/lib/currency.ts) + подсказка
    валюты по геолокации IP запроса (RU -> RUB, иначе KGS).

    ⚠️ НЕ платёжный эндпоинт и НЕ связан со старой Plan/CurrencyRate/
    selected_currency инфраструктурой (мёртвый остаток подписочной модели
    Vokalo, USD-базис) — курс отсюда ТОЛЬКО пересчитывает ОТОБРАЖАЕМУЮ цену.
    Реальная оплата всегда идёт через FreedomPay в сомах независимо от того,
    какая валюта выбрана для отображения (см. TokenPurchaseView ниже).

    Намеренно без cache_page (в отличие от PlanListView) — ответ зависит от IP
    запроса; сама гео-подсказка кэшируется по IP отдельно (plans/geo.py).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        try:
            from adminapi.runtime import get_runtime

            rate = float(get_runtime("currency_kgs_to_rub_rate", settings.CURRENCY_KGS_TO_RUB_RATE))
        except Exception:  # noqa: BLE001 — курс не должен ронять эндпоинт
            rate = float(settings.CURRENCY_KGS_TO_RUB_RATE)

        suggested_currency = "KGS"
        try:
            from users.antifraud import get_client_ip
            from .geo import detect_country_code

            ip = get_client_ip(request)
            country = detect_country_code(ip)
            if country == "RU":
                suggested_currency = "RUB"
        except Exception:  # noqa: BLE001 — гео-подсказка не должна ронять эндпоинт
            suggested_currency = "KGS"

        return Response({
            "base_currency": "KGS",
            "rate_kgs_to_rub": rate,
            "suggested_currency": suggested_currency,
        })


class PublicBonusSettingsView(APIView):
    """GET /api/plans/bonus-settings/ — публично, без авторизации.

    Отдаёт фронту РЕАЛЬНЫЕ размеры бонусов, чтобы тексты на сайте
    («получите N кредитов за регистрацию», «каждый день баланс пополняется
    до M кредитов») не расходились с тем, что админ выставил в /admin-new.

    Зачем отдельный публичный эндпоинт: числа показываются в том числе
    НЕавторизованным (страница входа, гостевой сайдбар, лимит гостя), а
    /api/manage/settings/ доступен только staff. Раньше эти цифры были
    захардкожены в i18n-строках — классический источник рассинхрона:
    в админке одно, на сайте другое.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        def _runtime_int(key: str, default: int) -> int:
            try:
                from adminapi.runtime import get_runtime

                return int(get_runtime(key, default))
            except Exception:  # noqa: BLE001 — настройки не должны ронять эндпоинт
                return int(default)

        welcome = _runtime_int(
            "WELCOME_BONUS_TOKENS", getattr(settings, "WELCOME_BONUS_TOKENS", 0) or 0
        )
        daily_target = _runtime_int(
            "DAILY_RETENTION_TARGET", getattr(settings, "DAILY_RETENTION_TARGET", 0) or 0
        )

        return Response({
            "welcome_bonus": welcome,
            "daily_free_credits": daily_target,
        })


class TokenTransactionListView(generics.ListAPIView):
    """GET /api/plans/transactions/ — последние ~50 транзакций токенов юзера."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = TokenTransactionSerializer

    def get_queryset(self):
        return (
            TokenTransaction.objects
            .filter(user=self.request.user)
            .order_by("-created_at")[:50]
        )


def safe_return_path(value, default="/profile") -> str:
    """Куда вернуть человека после оплаты.

    Путь приходит с фронта, поэтому пускаем только относительный, свой:
    «//evil.com» браузер считает абсолютным адресом, и открытая переадресация
    из платёжки — готовый фишинг. Всё подозрительное молча заменяем профилем.
    """
    raw = str(value or "").strip()
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw or len(raw) > 200:
        return default
    # Свой параметр «?payment=...» дописывается к этому пути позже, поэтому
    # чужую строку запроса не принимаем — иначе получится «/studio?a=1?payment=».
    if "?" in raw or "#" in raw:
        return default
    return raw


class TokenPurchaseView(APIView):
    """POST /api/plans/purchase/ {"package_id"} — инициировать оплату пакета токенов.

    Переиспользует FreedomPay init_payment flow (как payments.StartOneTimePaymentAPIView).
    Связь пакет↔платёж хранится в Payment.request["token_purchase"] и в order_id (tokpkg-...).
    Callback (payments.FreedomPayTokenPurchase*View) начислит токены по успешной оплате.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from payments.views import _parse_fp_response
        from payments.models import Payment
        from django.urls import reverse
        from .exit_discount import _resolve_identity

        package_id = (request.data or {}).get("package_id")
        try:
            package = TokenPackage.objects.get(pk=int(package_id), is_active=True)
        except (TokenPackage.DoesNotExist, TypeError, ValueError):
            return Response({"message": "package_not_found"}, status=drf_status.HTTP_404_NOT_FOUND)

        base_amount = Decimal(str(package.price or 0)).quantize(Decimal("0.01"))
        if base_amount <= 0:
            return Response({"message": "package_not_payable"}, status=drf_status.HTTP_400_BAD_REQUEST)
        currency = (package.currency or "KGS").strip().upper()

        # Валюта оплаты: пользователь выбирает её переключателем на /pricing.
        # RUB обслуживает ЮKassa, всё остальное (KGS) — FreedomPay. Цена
        # пакета хранится в сомах, поэтому для рублей пересчитываем по тому
        # же курсу, который показан на витрине (CurrencyRateView), — иначе
        # человек увидел бы одну сумму, а списалось бы другое.
        # Куда вернуть после оплаты: студия отправляет человека платить прямо из
        # проекта, и высаживать его в профиль вместо недоделанного мультфильма —
        # значит терять того, кто уже заплатил.
        return_to = safe_return_path((request.data or {}).get("return_to"))
        pay_currency = str((request.data or {}).get("pay_currency") or "").strip().upper()
        if pay_currency == "RUB":
            from payments import yookassa as yk

            if not yk.is_configured():
                return Response({"detail": "yookassa_config_missing"}, status=drf_status.HTTP_502_BAD_GATEWAY)
            try:
                from adminapi.runtime import get_runtime

                rate = Decimal(str(get_runtime("currency_kgs_to_rub_rate", settings.CURRENCY_KGS_TO_RUB_RATE)))
            except Exception:
                rate = Decimal(str(settings.CURRENCY_KGS_TO_RUB_RATE))
            if rate <= 0:
                return Response({"detail": "currency_rate_invalid"}, status=drf_status.HTTP_502_BAD_GATEWAY)
            return self._purchase_via_yookassa(request, package, base_amount, rate, return_to)

        merchant_id = (settings.FREEDOM_PAY_MERCHANT_ID or settings.FP_MERCHANT_ID or "").strip()
        secret = (settings.FREEDOM_PAY_TOKEN or "").strip()
        init_url = (settings.FREEDOM_PAY_INIT_PAYMENT_URL or "").strip()
        if not (merchant_id and secret and init_url):
            return Response({"detail": "freedompay_config_missing"}, status=drf_status.HTTP_502_BAD_GATEWAY)

        # Exit-intent скидка (see plans/exit_discount.py): если у пользователя/устройства
        # есть подтверждённый (claimed_at) и ещё не погашенный/не истёкший оффер — платим
        # меньше за ТОТ ЖЕ пакет (то же количество tokens+bonus_tokens). Лок + бронирование
        # оффера конкретным платежом (applied_to_payment) делаются в одной короткой
        # atomic-транзакции вместе с созданием Payment, ДО любого сетевого вызова к
        # FreedomPay — чтобы 2 параллельных клика "Купить" не могли оба получить скидку.
        identity = _resolve_identity(request)
        ident_user, device_key = identity["user"], identity["device_key"]
        now = timezone.now()

        with transaction.atomic():
            discount_offer = None
            offer = None
            if ident_user is not None:
                offer = ExitDiscountOffer.objects.select_for_update().filter(user=ident_user).first()
            if offer is None and device_key:
                offer = ExitDiscountOffer.objects.select_for_update().filter(device_key=device_key).first()

            if (
                offer is not None
                and offer.claimed_at is not None
                and offer.redeemed_at is None
                and offer.applied_to_payment_id is None
                and offer.expires_at is not None
                and now <= offer.expires_at
                and offer.percent
            ):
                discount_offer = offer

            if discount_offer is not None:
                percent = Decimal(int(discount_offer.percent))
                amount = (base_amount * (Decimal(100) - percent) / Decimal(100)).quantize(Decimal("0.01"))
                if amount <= 0 or amount >= base_amount:
                    # Защита от бракованной конфигурации (0% или >=100%) — не применяем скидку.
                    discount_offer = None
                    amount = base_amount
            else:
                amount = base_amount

            order_id = f"tokpkg-{request.user.id}-{package.id}-{uuid.uuid4().hex[:10]}"
            payload = {
                "pg_merchant_id": merchant_id,
                "pg_amount": format(amount, "f"),
                "pg_currency": currency,
                "pg_order_id": order_id,
                "pg_user_id": str(request.user.id),
                "pg_description": f"Token package #{package.id} for user #{request.user.id}",
                "pg_salt": uuid.uuid4().hex,
                "pg_success_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-success")),
                "pg_failure_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-failure")),
                "pg_post_link": request.build_absolute_uri(reverse("payments:freedompay-tokens-postback")),
                "pg_testing_mode": int(settings.DEBUG),
            }
            payload["pg_sig"] = make_api_signature("init_payment", payload, secret)

            request_payload = {
                "token_purchase": {
                    "package_id": package.id,
                    "tokens": int(package.tokens or 0),
                    "bonus_tokens": int(package.bonus_tokens or 0),
                    "payload": payload,
                },
                "return_to": return_to,
            }
            if discount_offer is not None:
                request_payload["exit_discount"] = {
                    "offer_id": discount_offer.id,
                    "percent": int(discount_offer.percent),
                    "original_amount": str(base_amount),
                }

            payment = Payment.objects.create(
                user=request.user,
                amount=amount,
                currency=currency,
                order_id=order_id,
                description=f"Token package purchase #{package.id}",
                is_test=settings.DEBUG,
                request=request_payload,
                response={},
            )

            if discount_offer is not None:
                discount_offer.applied_to_payment = payment
                discount_offer.save(update_fields=["applied_to_payment"])

        try:
            response = requests.post(init_url, data=payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = _parse_fp_response(response.text)
            except Exception:
                body = {"raw": response.text}
        except requests.RequestException as exc:
            payment.error = str(exc)
            payment.save(update_fields=["error"])
            return Response({"detail": "freedompay_request_failed"}, status=drf_status.HTTP_502_BAD_GATEWAY)

        payment.response = {"token_purchase_init": body}
        if response.status_code >= 400:
            payment.error = body.get("pg_error_description") or body.get("pg_error_message") or "freedompay_http_error"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=drf_status.HTTP_502_BAD_GATEWAY)

        redirect_url = body.get("pg_redirect_url") or body.get("redirect_url") or body.get("payment_url")
        if not redirect_url:
            payment.error = "freedompay_redirect_url_missing"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=drf_status.HTTP_502_BAD_GATEWAY)

        payment.save(update_fields=["response"])
        return Response(
            {
                "redirect_url": redirect_url,
                "order_id": order_id,
                "amount": str(amount),
                "currency": currency,
                "package_id": package.id,
            },
            status=drf_status.HTTP_200_OK,
        )

    def _purchase_via_yookassa(self, request, package, base_amount, rate, return_to="/profile"):
        """Оплата пакета в рублях через ЮKassa.

        Считаем сумму в рублях по тому же курсу, что показан на витрине,
        создаём Payment с currency=RUB и уходим на страницу оплаты ЮKassa.
        Кредиты начисляются НЕ здесь, а на вебхуке после перезапроса статуса
        в API (payments.views.YooKassaWebhookView) — тем же идемпотентным
        механизмом, что и у FreedomPay.

        Скидка exit-intent тут сознательно НЕ применяется: её механика
        завязана на FreedomPay-путь (бронирование оффера за платежом), и
        смешивать две валюты в одном оффере — прямой риск неверных сумм.
        Появится спрос — вынесем расчёт скидки в общий слой.
        """
        from payments import yookassa as yk
        from payments.models import Payment

        amount_rub = (base_amount * rate).quantize(Decimal("0.01"))
        if amount_rub <= 0:
            return Response({"detail": "amount_invalid"}, status=drf_status.HTTP_400_BAD_REQUEST)

        order_id = f"tokpkg-{request.user.id}-{package.id}-{uuid.uuid4().hex[:10]}"
        payment = Payment.objects.create(
            user=request.user,
            amount=amount_rub,
            currency="RUB",
            order_id=order_id,
            description=f"Token package purchase #{package.id} (YooKassa)",
            is_test=settings.DEBUG,
            request={
                "provider": "yookassa",
                "token_purchase": {
                    "package_id": package.id,
                    "tokens": int(package.tokens or 0),
                    "bonus_tokens": int(package.bonus_tokens or 0),
                },
                "kgs_price": str(base_amount),
                "rate_kgs_to_rub": str(rate),
                "return_to": return_to,
            },
            response={},
        )

        from payments.views import _frontend_absolute_url

        return_url = _frontend_absolute_url(request, return_to, {"payment": "tokens_success"})
        try:
            data = yk.create_payment(
                amount=format(amount_rub, "f"),
                currency="RUB",
                description=f"EsAI: пакет кредитов #{package.id}",
                return_url=return_url,
                metadata={"order_id": order_id, "user_id": str(request.user.id)},
                # Ключ идемпотентности = order_id: повторный клик «Купить»
                # не создаст второй платёж в ЮKassa.
                idempotence_key=order_id,
            )
        except Exception as exc:
            payment.error = f"yookassa_create_failed:{exc}"
            payment.save(update_fields=["error"])
            return Response({"detail": "yookassa_request_failed"}, status=drf_status.HTTP_502_BAD_GATEWAY)

        confirmation = (data or {}).get("confirmation") or {}
        redirect_url = confirmation.get("confirmation_url")
        payment.response = {"yookassa_create": data}
        if not redirect_url:
            payment.error = "yookassa_confirmation_url_missing"
            payment.save(update_fields=["response", "error"])
            return Response({"detail": payment.error}, status=drf_status.HTTP_502_BAD_GATEWAY)

        # id платежа ЮKassa нужен, чтобы связать вебхук с нашим заказом.
        req = payment.request or {}
        req["yookassa_payment_id"] = data.get("id")
        payment.request = req
        payment.save(update_fields=["response", "request"])

        return Response(
            {
                "redirect_url": redirect_url,
                "order_id": order_id,
                "amount": str(amount_rub),
                "currency": "RUB",
                "package_id": package.id,
            },
            status=drf_status.HTTP_200_OK,
        )
