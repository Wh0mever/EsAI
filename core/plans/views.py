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
from payments.freedompay import FreedomPay, FreedomPayError, make_api_signature, normalize_kg_phone
from decimal import Decimal
from core.langutils import request_lang, tr


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
        from .tiers import is_unlimited, user_tier

        balance = int(getattr(request.user, "token_balance", 0) or 0)
        unlimited = is_unlimited(request.user)
        # По правам безлимитный аккаунт совпадает с платным, но человеку это
        # надо показывать иначе: подпись «Платный» на экране безлимита выглядит
        # как ошибка биллинга. Поэтому отдельное значение тира собирается
        # ЗДЕСЬ, а plans/tiers.py намеренно не трогаем: на его TIER_PAID завязан
        # допуск к премиум-моделям (is_paid_tier → can_use_model), и лишнее
        # значение молча закрыло бы безлимитному человеку все платные модели.
        # Флаг is_unlimited отдаём рядом — потребителю, который тир не разбирает,
        # хватит булева поля.
        return Response(
            {
                "balance_tokens": balance,
                "tier": "unlimited" if unlimited else user_tier(request.user),
                "is_paid": bool(getattr(request.user, "is_paid", False)),
                "is_unlimited": unlimited,
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

        # Крипта: курс сом -> доллар и виден ли вообще этот способ оплаты.
        # Пока режим «только сотрудникам», обычный человек его не увидит.
        crypto_enabled = False
        rate_kgs_to_usd = 0.0
        try:
            from payments.crypto import rates as crypto_rates
            from payments.crypto import registry as crypto_registry

            user = request.user if request.user.is_authenticated else None
            crypto_enabled = crypto_registry.is_enabled_for(user)
            rate_kgs_to_usd = float(crypto_rates.kgs_to_usd_rate())
        except Exception:  # noqa: BLE001 — витрина не должна падать из-за крипты
            crypto_enabled = False

        # Оплата в сомах: какие способы (банк-приложение, карта) предложить
        # этому человеку до ухода на FreedomPay. Пустой список — выбора нет,
        # витрина ведёт себя как раньше.
        kgs_methods_list = []
        try:
            from payments import kgs_methods

            kgs_methods_list = kgs_methods.available_for(
                request.user if request.user.is_authenticated else None)
        except Exception:  # noqa: BLE001 — витрина не должна падать из-за выбора способа
            kgs_methods_list = []

        return Response({
            "base_currency": "KGS",
            "rate_kgs_to_rub": rate,
            "rate_kgs_to_usd": rate_kgs_to_usd,
            "crypto_enabled": crypto_enabled,
            "kgs_methods": kgs_methods_list,
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


# Сколько ссылка на оплату считается живой. Полчаса — компромисс: человек
# успевает сходить за картой, но не наткнётся завтра на вчерашнюю сумму.
RESUME_WINDOW_MINUTES = 30

# Скидочная ссылка FreedomPay живёт ровно столько, сколько мы готовы к ней
# возвращать (pg_lifetime). После этого по ней уже не заплатить, и скидку
# можно отдать новому платежу.
DISCOUNT_LINK_LIFETIME_SECONDS = RESUME_WINDOW_MINUTES * 60
# Ссылка в приложение банка (без скидки) живёт дольше, чем мы к ней возвращаем:
# при равных сроках человеку, вернувшемуся на 28-й минуте, досталась бы ссылка,
# которая умрёт, пока он открывает банк. Так у возвращённой ссылки в запасе
# минимум четверть часа.
KGS_APP_LINK_LIFETIME_SECONDS = (RESUME_WINDOW_MINUTES + 15) * 60
# Запрос к FreedomPay обрывается через 30 с; платёж без ссылки и без ошибки
# старше этого — оборванный старт, ссылку по нему человек не получил.
DISCOUNT_INIT_GRACE = timedelta(minutes=2)


def _offer_free_for_new_payment(offer, now=None) -> bool:
    """Скидку можно отдать новому платежу.

    Раньше она намертво привязывалась к первому созданному платежу, даже к
    тому, у которого ссылка на оплату так и не появилась. Но и отдавать её
    дальше, пока прежняя скидочная ссылка жива, нельзя: обе оставались бы
    оплачиваемыми со скидкой, и одноразовая скидка срабатывала бы сколько
    угодно раз. Поэтому скидка переезжает, только когда по прежнему платежу
    заплатить со скидкой уже невозможно.
    """
    if offer.applied_to_payment_id is None:
        return True
    applied = getattr(offer, "applied_to_payment", None)
    if applied is None:
        return True
    if applied.success:
        return False
    now = now or timezone.now()
    response = applied.response or {}
    if any(isinstance(cb, dict) and cb.get("type") == "success"
           for cb in (response.get("callbacks") or [])):
        # Банк уже вернул человека со страницы «успешно»: оплата, скорее всего,
        # прошла и ждёт подтверждения — скидку не трогаем.
        return False
    if _redirect_url_of(response):
        # Ссылка выдана — ждём, пока истечёт срок её жизни у FreedomPay.
        payload = ((applied.request or {}).get("token_purchase") or {}).get("payload") or {}
        try:
            lifetime = int(payload.get("pg_lifetime") or 0)
        except (TypeError, ValueError):
            lifetime = 0
        return bool(lifetime) and now >= applied.created_at + timedelta(seconds=lifetime + 60)
    # Ссылки нет: старт упал с ошибкой или оборвался — платить не по чему.
    if applied.error:
        return True
    return now - applied.created_at > DISCOUNT_INIT_GRACE


def _discount_waiting(request, existing) -> bool:
    """Есть забранная, ещё не использованная скидка, которой нет в прежней ссылке."""
    from django.utils import timezone as _tz

    from .exit_discount import _resolve_identity

    try:
        identity = _resolve_identity(request)
        offer = None
        if identity["user"] is not None:
            offer = ExitDiscountOffer.objects.filter(user=identity["user"]).first()
        if offer is None and identity["device_key"]:
            offer = ExitDiscountOffer.objects.filter(device_key=identity["device_key"]).first()
        if (offer is None or offer.claimed_at is None or offer.redeemed_at is not None
                or not offer.percent or offer.expires_at is None or _tz.now() > offer.expires_at):
            return False
        # Прежняя ссылка уже со скидкой — к ней и возвращаем, новую не заводим.
        if (getattr(existing, "request", None) or {}).get("exit_discount"):
            return False
        # Скидка занята живой скидочной ссылкой — новый платёж её не получит,
        # так что и прежнюю ссылку по полной цене отбрасывать незачем.
        return (offer.applied_to_payment_id != getattr(existing, "pk", None)
                and _offer_free_for_new_payment(offer))
    except Exception:
        return False


def _discount_holder(request, package_id, currency):
    """Живой скидочный платёж этого же пакета, за которым сейчас закреплена скидка.

    Нужен выбору способа оплаты: скидка одноразовая и привязана к первой
    выданной ссылке, поэтому нажатие на другой способ получило бы полную цену,
    хотя в окне выбора показана цена со скидкой. Вызывающий код в этом случае
    не заводит платёж молча, а отдаёт человеку выбор.
    """
    from .exit_discount import _resolve_identity

    try:
        identity = _resolve_identity(request)
        offer = None
        if identity["user"] is not None:
            offer = ExitDiscountOffer.objects.filter(user=identity["user"]).first()
        if offer is None and identity["device_key"]:
            offer = ExitDiscountOffer.objects.filter(device_key=identity["device_key"]).first()
        now = timezone.now()
        if (offer is None or offer.claimed_at is None or offer.redeemed_at is not None
                or not offer.percent or offer.expires_at is None or now > offer.expires_at):
            # Скидки на витрине уже нет — и обещания, которое можно нарушить, тоже.
            return None
        holder = offer.applied_to_payment
        if holder is None or holder.success or holder.user_id != request.user.id:
            return None
        if _offer_free_for_new_payment(offer, now):
            return None
        req = holder.request or {}
        purchase = req.get("token_purchase") or {}
        if not req.get("exit_discount") or str(purchase.get("package_id")) != str(package_id):
            return None
        if str(holder.currency).upper() != str(currency).upper():
            return None
        response = holder.response or {}
        if response.get("callbacks") or not _redirect_url_of(response):
            return None
        # Ссылка, по которой FreedomPay уже не примет оплату, — не предложение.
        try:
            lifetime = int((purchase.get("payload") or {}).get("pg_lifetime") or 0)
        except (TypeError, ValueError):
            lifetime = 0
        if lifetime and now >= holder.created_at + timedelta(seconds=lifetime):
            return None
        return holder
    except Exception:  # noqa: BLE001 — проверка не должна ронять оплату
        return None


def pending_token_payment(user, package_id=None, currency=None, method=None):
    """Незавершённая оплата пакета, к которой можно вернуться.

    Разбор воронки показал, зачем это нужно: 73 брошенные попытки — это всего
    47 человек, один нажимал «Пополнить» десять раз подряд. Каждое нажатие
    заводило новый платёж и новую ссылку, а человек всё это время смотрел в
    одну и ту же не открывшуюся страницу.

    Незавершённой считаем ту, по которой платёжная система не прислала ни
    одного ответа: пришёл ответ — значит человек до формы дошёл, и продолжать
    там уже нечего.

    method — способ оплаты в сомах (payments/kgs_methods.py). Ссылка, созданная
    под один способ, открывает именно его: нажавшему «картой» нельзя отдать
    ссылку на приложение банка. Поэтому со способом возвращаем только платёж
    того же способа, с пустой строкой — только платёж без способа (как было до
    выбора). None — способ не важен: баннеру «вернуться к оплате» годится любая.
    """
    from datetime import timedelta

    from django.utils import timezone as _tz
    from payments.models import Payment

    qs = Payment.objects.filter(
        user=user, success=False,
        request__token_purchase__isnull=False,
        created_at__gte=_tz.now() - timedelta(minutes=RESUME_WINDOW_MINUTES),
    ).order_by("-created_at")
    if package_id:
        qs = qs.filter(request__token_purchase__package_id=int(package_id))
    if currency:
        # Начатая в рублях оплата — не та же самая, что в сомах: человек,
        # переключивший валюту, иначе попадал обратно на страницу ЮKassa.
        qs = qs.filter(currency=str(currency).upper())

    for payment in qs[:20]:
        response = payment.response or {}
        if response.get("callbacks"):
            continue
        # Сравниваем здесь, а не в запросе: у прежних платежей ключа pay_method
        # нет вовсе, и exclude() по JSON-ключу такие строки теряет.
        if method is not None and str((payment.request or {}).get("pay_method") or "") != method:
            continue
        url = _redirect_url_of(response)
        if url:
            return payment, url
    return None, ""


def pending_token_resume(user, package_id=None):
    """Незавершённая оплата любого вида, к которой можно вернуться.

    Карточная — это ссылка на страницу банка, крипта — счёт с адресом и
    таймером; общее у них одно: человек ушёл платить и не закончил. Если
    незакрытыми оказались обе, показываем ту, что новее: она и есть текущее
    намерение.
    """
    from payments.models import CryptoInvoice

    payment, url = pending_token_payment(user, package_id)
    card = {"kind": "card", "payment": payment, "redirect_url": url} if url else None

    invoices = CryptoInvoice.objects.select_related("payment").filter(
        payment__user=user,
        status__in=list(CryptoInvoice.OPEN_STATES),
        expires_at__gt=timezone.now(),
    )
    if package_id:
        invoices = invoices.filter(
            payment__request__token_purchase__package_id=int(package_id))
    invoice = invoices.order_by("-created_at").first()
    crypto = {"kind": "crypto", "payment": invoice.payment, "invoice": invoice} if invoice else None

    if card and crypto:
        return card if card["payment"].created_at >= crypto["payment"].created_at else crypto
    return card or crypto


def _redirect_url_of(response: dict) -> str:
    """Ссылка на оплату из ответа платёжной системы.

    Смотрим и в новое поле, и в исходные ответы: у платежей, созданных до
    появления этой функции, верхнего поля нет, а вернуть человека к ним нужно
    так же.
    """
    if not isinstance(response, dict):
        return ""
    direct = response.get("redirect_url")
    if direct:
        return str(direct)
    init = response.get("token_purchase_init") or {}
    if isinstance(init, dict) and init.get("pg_redirect_url"):
        return str(init["pg_redirect_url"])
    yk = response.get("yookassa_create") or {}
    if isinstance(yk, dict):
        url = (yk.get("confirmation") or {}).get("confirmation_url")
        if url:
            return str(url)
    return ""


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


class PendingPaymentView(APIView):
    """GET /api/plans/purchase/pending/ — незавершённая оплата, если она есть.

    Нужна, чтобы вернуть человека туда, откуда он ушёл. Половина брошенных
    платежей — это повторные нажатия одних и тех же людей: страница оплаты
    закрылась, и единственным способом продолжить было начать всё заново.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        found = pending_token_resume(request.user)
        if not found:
            return Response({"pending": None})

        payment = found["payment"]
        pkg_id = ((payment.request or {}).get("token_purchase") or {}).get("package_id")
        pkg = TokenPackage.objects.filter(pk=pkg_id).first() if pkg_id else None
        pending = {
            "kind": found["kind"],
            "order_id": payment.order_id,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "package": tr(pkg, "name", request_lang(request)) if pkg else "",
            "created_at": payment.created_at.isoformat(),
        }

        if found["kind"] == "crypto":
            from payments.crypto.views import amount_str

            invoice = found["invoice"]
            remaining = max(Decimal(0), invoice.pay_amount - invoice.actually_paid)
            pending.update({
                "redirect_url": None,
                # Экран оплаты открывается по этому адресу — ссылки на чужую
                # страницу у крипты нет.
                "status_url": f"/api/plans/purchase/crypto/{payment.order_id}/",
                "coin": invoice.pay_coin,
                "network": invoice.pay_network,
                "pay_amount": amount_str(invoice.pay_amount),
                "amount_remaining": amount_str(remaining),
                "expires_at": invoice.expires_at.isoformat() if invoice.expires_at else None,
            })
        else:
            pending["redirect_url"] = found["redirect_url"]

        return Response({"pending": pending})


class TokenPurchaseView(APIView):
    """POST /api/plans/purchase/ {"package_id"} — инициировать оплату пакета токенов.

    Переиспользует FreedomPay init_payment flow (как payments.StartOneTimePaymentAPIView).
    Связь пакет↔платёж хранится в Payment.request["token_purchase"] и в order_id (tokpkg-...).
    Callback (payments.FreedomPayTokenPurchase*View) начислит токены по успешной оплате.

    Необязательное поле "method" — способ оплаты в сомах, выбранный на нашей
    стороне (payments/kgs_methods.py): FreedomPay сразу открывает нужный банк
    или форму карты. Без него запрос к FreedomPay остаётся прежним.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from payments.views import _parse_fp_response
        from payments.models import Payment
        from payments import kgs_methods
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

        # Крипта идёт своим путём с самого начала: там не ссылка на банк, а
        # счёт с адресом и таймером, и возвращаться к нему надо иначе.
        if pay_currency == "USD":
            return self._purchase_via_crypto(request, package, base_amount, return_to)

        # Способ оплаты в сомах, выбранный на нашей стороне (банк-приложение
        # или карта). Для рублей смысла не имеет: там платит ЮKassa. Без способа
        # всё идёт как раньше, параметр в параметр.
        method = ""
        method_params = {}
        if pay_currency != "RUB":
            method = str((request.data or {}).get("method") or "").strip().lower()
            if method:
                method_params = kgs_methods.fp_params(method, request.user)
                if method_params is None:
                    # Проверяем до поиска прежней ссылки и до скидки: выключенный
                    # способ не должен ни завести платёж, ни вернуть старую ссылку.
                    return Response({"detail": "method_unavailable"},
                                    status=drf_status.HTTP_400_BAD_REQUEST)

        # Тот же пакет, начатый минуту назад, — это не второй платёж, а тот же
        # самый: человек вернулся и жмёт снова. Отдаём прежнюю ссылку.
        want_currency = "RUB" if pay_currency == "RUB" else currency
        existing, existing_url = pending_token_payment(
            request.user, package.id, currency=want_currency,
            # Ссылка под другой способ — другая страница оплаты, её не отдаём.
            method=None if pay_currency == "RUB" else method)
        if existing_url and method:
            # Ссылка того же способа, но созданная с другим кодом платёжной
            # системы (код единого QR поправили в админке): по ней откроется
            # прежняя, неверная страница — заводим новую.
            stored = ((existing.request or {}).get("token_purchase") or {}).get("payload") or {}
            if any(stored.get(key) != value for key, value in method_params.items()):
                existing, existing_url = None, None
        if method and (request.data or {}).get("full_price") is not True:
            # Скидка закреплена за ссылкой другого способа: этот клик получил бы
            # полную цену, а в окне выбора показана цена со скидкой. Молча так
            # не делаем — отдаём выбор: продолжить ту оплату или платить без
            # скидки (повторный запрос с full_price).
            holder = _discount_holder(request, package.id, currency)
            if holder is not None and not (existing_url and existing.pk == holder.pk):
                return Response({
                    "detail": "discount_held",
                    "amount": str(base_amount),
                    "currency": currency,
                    "held": {
                        "method": str((holder.request or {}).get("pay_method") or ""),
                        "order_id": holder.order_id,
                        "redirect_url": _redirect_url_of(holder.response or {}),
                        "amount": str(holder.amount),
                    },
                }, status=drf_status.HTTP_409_CONFLICT)
        # Прежняя ссылка — полная цена, а человек с тех пор забрал скидку: не
        # подсовываем её, иначе на витрине 392, а платёжка просит 490.
        if existing_url and want_currency != "RUB" and _discount_waiting(request, existing):
            existing_url = None
        if existing_url:
            return Response({"redirect_url": existing_url, "order_id": existing.order_id,
                             "amount": str(existing.amount), "currency": existing.currency,
                             "resumed": True})

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
                and _offer_free_for_new_payment(offer)
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
                # Это человек видит на странице оплаты. Раньше там стояло
                # «Token package #3 for user #958» — техническая строка ровно в
                # ту секунду, когда решают, вводить ли карту.
                "pg_description": f"EsAI: {package.name} — {int(package.tokens or 0)} кредитов",
                "pg_language": "en" if request_lang(request) == "en" else "ru",
                "pg_user_contact_email": (request.user.email or "")[:120],
                "pg_salt": uuid.uuid4().hex,
                "pg_success_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-success")),
                "pg_failure_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-failure")),
                # Адрес, куда FreedomPay сообщает об оплате. Раньше он уходил в
                # pg_post_link — такого параметра у init_payment нет, и работал
                # только адрес из настроек магазина в кабинете. Передаём явно,
                # чтобы не зависеть от кабинета; метод тоже — по умолчанию GET.
                "pg_result_url": request.build_absolute_uri(reverse("payments:freedompay-tokens-postback")),
                "pg_request_method": "POST",
                "pg_testing_mode": int(settings.DEBUG),
            }
            # С телефоном FreedomPay заранее заполняет поле на форме оплаты
            # картой. Для кошельков (MBANK, О!Деньги…) не передаём: там номер
            # может решать, кому уйдёт счёт, а в профиле он ничем не проверен.
            phone = ""
            if method in ("", "card"):
                phone = normalize_kg_phone(getattr(request.user, "tel", ""))
            if phone:
                payload["pg_user_phone"] = phone
            if discount_offer is not None:
                # Скидочная ссылка не должна жить сутки (срок FreedomPay по
                # умолчанию): пока она жива, скидку нельзя отдать другому платежу.
                payload["pg_lifetime"] = str(DISCOUNT_LINK_LIFETIME_SECONDS)
            if method:
                # Выбранный способ: FreedomPay сразу откроет нужный банк или
                # форму карты. Добавляем до подписи — она считается по всем
                # параметрам.
                payload.update(method_params)
                if kgs_methods.METHODS[method][0] in ("app", "qr"):
                    # Брошенная оплата через приложение банка не должна жить
                    # сутки: человек вернётся к ней завтра и заплатит по
                    # вчерашней ссылке, о которой уже забыл. Срок скидочной
                    # ссылки (выше) не трогаем: от него зависит, когда скидку
                    # можно отдать другому платежу.
                    payload.setdefault("pg_lifetime", str(KGS_APP_LINK_LIFETIME_SECONDS))
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
            if method:
                # Только при выбранном способе: у прежних платежей ключа нет,
                # и по его отсутствию их отличают при возврате к оплате.
                request_payload["pay_method"] = method
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

        def _init_payment():
            response = requests.post(init_url, data=payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = _parse_fp_response(response.text)
            except Exception:
                body = {"raw": response.text}
            return response, body

        try:
            response, body = _init_payment()
            if "pg_user_phone" in payload and (
                    response.status_code >= 400
                    or not (body.get("pg_redirect_url") or body.get("redirect_url") or body.get("payment_url"))):
                # Номер из профиля не должен стоить человеку оплаты: если с ним
                # FreedomPay запрос не принял, пробуем один раз без номера.
                # payload лежит и в payment.request — сохраняем то, что ушло.
                payload.pop("pg_user_phone")
                payload.pop("pg_sig")
                payload["pg_sig"] = make_api_signature("init_payment", payload, secret)
                payment.save(update_fields=["request"])
                response, body = _init_payment()
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

        # Кладём ссылку наверх: по ней человека возвращают к незавершённой
        # оплате, и искать её в сыром ответе платёжной системы неудобно.
        payment.response["redirect_url"] = redirect_url
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

    def _purchase_via_crypto(self, request, package, base_amount, return_to="/profile"):
        """Выставить счёт на оплату криптовалютой.

        Ссылки на чужую страницу оплаты здесь нет: процессор даёт адрес и
        точную сумму, экран оплаты рисуем сами. Кредиты начисляются не здесь,
        а после подтверждения сети — на вебхуке и в сверке (payments/crypto).

        Скидка «при уходе» сознательно не применяется, как и у ЮKassa: её
        механика забронирована за FreedomPay-путём, и смешивать её с другой
        валютой — прямой риск неверных сумм.
        """
        from payments.crypto import base as crypto_base
        from payments.crypto import currencies as crypto_currencies
        from payments.crypto import rates as crypto_rates
        from payments.crypto import registry as crypto_registry
        from payments.crypto.views import invoice_json
        from payments.models import CryptoInvoice, Payment
        from payments.views import _log_payment_event

        if not crypto_registry.is_enabled_for(request.user):
            return Response({"detail": "crypto_disabled"}, status=drf_status.HTTP_403_FORBIDDEN)
        if not crypto_registry.is_configured():
            return Response({"detail": "crypto_config_missing"},
                            status=drf_status.HTTP_502_BAD_GATEWAY)

        code = str((request.data or {}).get("crypto_currency") or "").strip().lower()
        if not crypto_currencies.is_allowed(code):
            return Response({"detail": "crypto_currency_not_supported"},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        # Каждый счёт — это запрос к платному API процессора. Десяти попыток в
        # минуту хватит любому живому человеку.
        from django.core.cache import cache as _cache

        bucket = f"crypto:purchase:{request.user.id}"
        if not _cache.add(bucket, 1, 60):
            try:
                hits = _cache.incr(bucket)
            except ValueError:
                hits = 1
            if hits > 10:
                return Response({"detail": "crypto_too_often"},
                                status=drf_status.HTTP_429_TOO_MANY_REQUESTS)

        now = timezone.now()
        open_invoices = CryptoInvoice.objects.filter(
            payment__user=request.user,
            status__in=list(CryptoInvoice.OPEN_STATES),
            expires_at__gt=now,
        )
        # Тот же пакет той же монетой — это не второй счёт, а тот же самый:
        # человек закрыл вкладку и вернулся. Заводить новый адрес нельзя, он
        # может уже отправить деньги на старый.
        same = (open_invoices.filter(
            pay_currency=code,
            payment__request__token_purchase__package_id=package.id)
            .select_related("payment").order_by("-created_at").first())
        if same is not None:
            return Response(invoice_json(same, resumed=True))
        # Счёт создаётся по клику на монету, и человек, сравнивающий три-четыре
        # сети, честно наберёт несколько живых счетов. А вот больше шести —
        # это уже перебор адресов: каждый счёт стоит нам запроса к процессору.
        if open_invoices.count() >= 6:
            return Response({"detail": "crypto_too_many_open_invoices"},
                            status=drf_status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            amount_usd, rate = crypto_rates.kgs_to_usd(base_amount)
        except crypto_base.ProviderError as exc:
            return Response({"detail": exc.code}, status=drf_status.HTTP_502_BAD_GATEWAY)

        adapter = crypto_registry.get_adapter()
        min_usd = None
        try:
            min_usd = adapter.min_amount_usd(code)
        except crypto_base.ProviderError:
            # Минимум не узнали — пусть решает процессор при создании счёта.
            min_usd = None
        if min_usd and amount_usd < min_usd:
            return Response({"detail": "crypto_amount_below_min",
                             "min_usd": str(min_usd), "amount_usd": str(amount_usd)},
                            status=drf_status.HTTP_400_BAD_REQUEST)

        try:
            callback_url = crypto_registry.ipn_url(request)
        except crypto_base.ProviderError as exc:
            logging.getLogger("payments.crypto").error("crypto: %s", exc)
            return Response({"detail": "crypto_config_missing"},
                            status=drf_status.HTTP_502_BAD_GATEWAY)

        order_id = f"tokpkg-{request.user.id}-{package.id}-{uuid.uuid4().hex[:10]}"
        payment = Payment.objects.create(
            user=request.user,
            provider=crypto_registry.provider_code(adapter.name),
            amount=amount_usd,
            currency="USD",
            order_id=order_id,
            description=f"Token package purchase #{package.id} (crypto)",
            is_test=bool(settings.DEBUG or getattr(settings, "NOWPAYMENTS_SANDBOX", False)),
            request={
                "provider": crypto_registry.provider_code(adapter.name),
                "pay_method": "crypto",
                "token_purchase": {
                    "package_id": package.id,
                    "tokens": int(package.tokens or 0),
                    "bonus_tokens": int(package.bonus_tokens or 0),
                },
                "kgs_price": str(base_amount),
                "rate_kgs_to_usd": str(rate),
                "amount_usd": str(amount_usd),
                "pay_currency": code,
                "return_to": return_to,
            },
            response={},
        )

        try:
            created = adapter.create_invoice(
                order_id=order_id,
                amount_usd=amount_usd,
                pay_currency=code,
                ipn_url=callback_url,
                description=f"EsAI credits package {package.id}",
            )
        except crypto_base.ProviderError as exc:
            # В ошибке платежа не должно быть ни ключей, ни сырых ответов, но
            # текст отказа процессора нужен: без него в админке восемнадцать
            # «http_400» подряд, и непонятно, что процессор считал сумму малой.
            reason = str(exc)[:120]
            payment.error = f"crypto_create_failed:{exc.code}: {reason}"
            payment.save(update_fields=["error"])
            # Процессор считает минимум по-своему и говорит об этом разными
            # словами: «amountTo is too small» в обычном режиме, «Crypto amount
            # … is less than minimal» в Custody. Человеку в любом случае нужен
            # ответ «мало», а не «ошибка шлюза».
            if any(k in reason.lower() for k in ("too small", "less than min", "minimal", "minimum")):
                return Response({"detail": "crypto_amount_below_min",
                                 "min_usd": str(min_usd) if min_usd else None,
                                 "amount_usd": str(amount_usd)},
                                status=drf_status.HTTP_400_BAD_REQUEST)
            return Response({"detail": "crypto_request_failed"},
                            status=drf_status.HTTP_502_BAD_GATEWAY)

        ttl_minutes = int(getattr(settings, "CRYPTO_INVOICE_TTL_MINUTES", 60))
        own_deadline = now + timedelta(minutes=ttl_minutes)
        expires_at = min(created.expires_at, own_deadline) if created.expires_at else own_deadline

        invoice = CryptoInvoice.objects.create(
            payment=payment,
            provider=created.provider,
            provider_invoice_id=created.provider_id,
            price_amount=amount_usd,
            price_currency="USD",
            pay_currency=created.pay_currency,
            pay_coin=created.pay_coin,
            pay_network=created.pay_network,
            pay_address=created.pay_address,
            pay_extra_id=created.pay_extra_id,
            pay_amount=created.pay_amount,
            expires_at=expires_at,
        )
        payment.response = {"crypto_create": created.raw}
        payment.save(update_fields=["response"])
        _log_payment_event(payment, "crypto_created")
        invoice.payment = payment
        return Response(invoice_json(invoice), status=drf_status.HTTP_200_OK)

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
            # Поле провайдера раньше не заполнялось (стояло по умолчанию
            # «freedompay»): автосверка спрашивала про рублёвые заказы FreedomPay,
            # а в админке ЮKassa терялась среди карт.
            provider="yookassa",
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
        payment.response = {"yookassa_create": data, "redirect_url": redirect_url}
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
