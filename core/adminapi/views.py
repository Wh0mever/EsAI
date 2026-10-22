import re
"""Кастомная админ-панель (/api/manage/): только staff, JWT Bearer.

Идиома кодовой базы — APIView (см. ai/views.py), без вьюсетов и DRF-пагинаторов.
"""
import os

import requests as http_requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication

from ai.models import GPTModels
from content.models import BlogPost, SiteSettings
from payments.models import Payment
from plans.models import (ExitDiscountOffer, PromoCode, TokenPackage, TokenTransaction,
                          MERGE_SPEND_REASONS, VSTUDIO_SPEND_REASONS)
from plans.wallet import clawback_tokens, credit_tokens

from .permissions import IsStaff
from .runtime import CACHE_PREFIX, delete_runtime, get_runtime, set_runtime
from .serializers import (
    BlogPostFullSerializer,
    BlogPostListSerializer,
    GPTModelAdminSerializer,
    PaymentAdminSerializer,
    PaymentShortSerializer,
    PromoCodeAdminSerializer,
    TokenPackageAdminSerializer,
    TokenTransactionAdminSerializer,
    UserAdminSerializer,
)

User = get_user_model()

PAGE_SIZE = 50


def _paginate(qs, request, page_size=PAGE_SIZE):
    """Простая ручная пагинация: ?page=N, срез по page_size."""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    count = qs.count()
    start = (page - 1) * page_size
    return count, qs[start:start + page_size]


def _effective_openrouter_key() -> str:
    """Действующий ключ OpenRouter: runtime-настройка из админки, затем env."""
    runtime_key = (get_runtime("OPENROUTER_API_KEY", "") or "").strip()
    return runtime_key or (os.environ.get("OPENROUTER_API_KEY") or "").strip()


def _openrouter_summary():
    """Деньги OpenRouter: сумма по всем аккаунтам и сколько на рабочем.

    Раньше на дашборде висел остаток одного ключа из настроек. С появлением
    аккаунтов это стало прямой ложью: показывался счёт, с которого уже никто
    не тратит. Клиент спросил «суммарно не?» — суммарно и показываем, а рядом
    отдельной строкой рабочий счёт: тратится-то с него.
    """
    try:
        from ai.models import OpenRouterAccount

        rows = list(OpenRouterAccount.objects.all())
    except Exception:
        rows = []
    if not rows:
        return {"total": _openrouter_balance(), "active": None,
                "active_title": "", "accounts": 0}
    total = sum(float(a.balance_usd or 0) for a in rows)
    active = next((a for a in rows if a.is_active), None)
    return {
        "total": round(total, 2),
        "active": round(float(active.balance_usd or 0), 2) if active else None,
        "active_title": active.title if active else "",
        "accounts": len(rows),
    }


def _openrouter_balance():
    """Остаток на счёте OpenRouter в USD; None при любой ошибке (ключ/сеть/формат)."""
    try:
        key = _effective_openrouter_key()
        if not key:
            return None
        resp = http_requests.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
            timeout=6,
        )
        data = (resp.json() or {}).get("data") or {}
        return round(float(data.get("total_credits", 0)) - float(data.get("total_usage", 0)), 2)
    except Exception:
        return None


class StaffAPIView(APIView):
    """База для всех эндпоинтов панели: JWT + is_staff."""
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsStaff]


# ---------------------------------------------------------------- summary ---

class SummaryView(StaffAPIView):
    def get(self, request):
        today = timezone.localdate()

        # Тестовые оплаты (единый QR в тестовой среде) идут без денег: кредиты
        # сотруднику начисляются, но в выручку они не попадают.
        revenue = (
            Payment.objects.filter(success=True, currency="KGS", is_test=False)
            .aggregate(s=Sum("amount"))["s"] or 0
        )

        # Списания за чат идут с delta < 0 — знак разворачиваем в положительный расход.
        # Видеостудия списывает под своими причинами (vstudio_*): без них её
        # выручка на дашборде не видна вовсе, поэтому считаем их вместе с чатом
        # и отдельной строкой. Склейка (merge_video) и её звук (merge_voice,
        # merge_music) — тоже траты за готовое, они в общей сумме.
        spend_qs = TokenTransaction.objects.filter(reason__in=(
            "chat", *VSTUDIO_SPEND_REASONS, *MERGE_SPEND_REASONS))
        spend_today_qs = spend_qs.filter(created_at__date=today)
        spent_total = -(spend_qs.aggregate(s=Sum("delta"))["s"] or 0)
        spent_today = -(spend_today_qs.aggregate(s=Sum("delta"))["s"] or 0)
        vstudio_qs = TokenTransaction.objects.filter(reason__in=VSTUDIO_SPEND_REASONS)
        vstudio_total = -(vstudio_qs.aggregate(s=Sum("delta"))["s"] or 0)
        vstudio_today = -(vstudio_qs.filter(created_at__date=today)
                          .aggregate(s=Sum("delta"))["s"] or 0)

        recent = Payment.objects.select_related("user").order_by("-created_at", "-id")[:10]

        return Response({
            "users_total": User.objects.count(),
            "users_paid": User.objects.filter(is_paid=True).count(),
            "revenue_kgs": float(revenue),
            "credits_spent_total": int(spent_total),
            "credits_spent_today": int(spent_today),
            "credits_spent_vstudio_total": int(vstudio_total),
            "credits_spent_vstudio_today": int(vstudio_today),
            "requests_today": spend_today_qs.count(),
            "requests_total": spend_qs.count(),
            "openrouter": _openrouter_summary(),
            "recent_payments": PaymentShortSerializer(recent, many=True).data,
        })


# ----------------------------------------------------------------- models ---

class ModelsListView(StaffAPIView):
    def get(self, request):
        qs = GPTModels.objects.all().order_by("sort_order", "id")
        return Response(GPTModelAdminSerializer(qs, many=True, context={"request": request}).data)

    def post(self, request):
        """«Добавить модель» по ID из каталога OpenRouter: строка встаёт выключенной."""
        from . import prices

        return prices.add_model(request)


class ModelDetailView(StaffAPIView):
    def patch(self, request, pk):
        from . import prices

        obj = get_object_or_404(GPTModels, pk=pk)
        ser = GPTModelAdminSerializer(obj, data=request.data, partial=True)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        # Правка в журнал и сброс кэшей цен: наценка, себестоимость, тариф и
        # включение модели меняют цены сразу, а не через десять минут кэша.
        prices.save_model(ser, actor=request.user, request=request)
        return Response(GPTModelAdminSerializer(obj, context={"request": request}).data)


# --------------------------------------------------------------- packages ---

class PackagesListView(StaffAPIView):
    def get(self, request):
        qs = TokenPackage.objects.all().order_by("sort_order", "id")
        return Response(TokenPackageAdminSerializer(qs, many=True).data)


class PackageDetailView(StaffAPIView):
    def patch(self, request, pk):
        from . import prices

        obj = get_object_or_404(TokenPackage, pk=pk)
        ser = TokenPackageAdminSerializer(obj, data=request.data, partial=True)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        ser.save()
        # Самый дешёвый кредит из пакетов — основа всех цен видео (и цен с наценкой).
        prices.invalidate()
        return Response(ser.data)


# ------------------------------------------------------------------ users ---

class UsersListView(StaffAPIView):
    def get(self, request):
        qs = User.objects.all().order_by("-date_joined")
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(email__icontains=q)
                | Q(username__icontains=q)
                | Q(telegram__icontains=q)
            )
        count, page_qs = _paginate(qs, request)
        return Response({
            "count": count,
            "results": UserAdminSerializer(page_qs, many=True).data,
        })


class UserCreditView(StaffAPIView):
    """Ручная корректировка баланса: + начислить / − списать (clamp по балансу)."""

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)

        try:
            amount = int(request.data.get("amount"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "amount должен быть целым числом"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if amount == 0:
            return Response(
                {"detail": "amount не может быть нулём"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        note = str(request.data.get("note") or "")
        meta = {"note": note, "by": request.user.email}

        if amount > 0:
            balance = credit_tokens(user, amount, "admin", meta=meta)
        else:
            # clawback_tokens списывает min(amount, баланс) — в минус не уходит
            clawback_tokens(user, -amount, reason="admin", meta=meta)
            user.refresh_from_db(fields=["token_balance"])
            balance = int(user.token_balance or 0)

        return Response({"ok": True, "balance": int(balance)})


class UserTransactionsView(StaffAPIView):
    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        qs = TokenTransaction.objects.filter(user=user).order_by("-created_at", "-id")[:100]
        return Response(TokenTransactionAdminSerializer(qs, many=True).data)


# --------------------------------------------------------------- payments ---

def _unsettled_gopay_payment_ids() -> list:
    """Платежи единого QR, по которым GoPay подтвердил оплату, а кредитов нет.

    Те же строки, что считает счётчик «Оплачено, но не зачислено» в настройках:
    счёт оплачен, платёж не успешен, возврат не отмечен и начисленное не изъято.
    Отметки возврата сверяем в Python — таких строк единицы, а отбор по ключу
    JSON ведёт себя по-разному на SQLite (тесты) и PostgreSQL (бой).
    """
    from payments.models import GoPayInvoice

    rows = (GoPayInvoice.objects.select_related("payment")
            .filter(status=GoPayInvoice.STATUS_COMMITTED, payment__success=False))
    ids = []
    for invoice in rows:
        response = invoice.payment.response
        response = response if isinstance(response, dict) else {}
        if not (response.get("admin_refund") or response.get("token_purchase_clawed_back")):
            ids.append(invoice.payment_id)
    return ids


class PaymentsListView(StaffAPIView):
    """Список платежей. Крипта живёт дольше карточной оплаты, поэтому здесь
    появились фильтры: иначе незакрытый криптосчёт не найти среди сотен строк.
    Единый QR добавил свои: тестовые оплаты и «оплачено, но не зачислено»."""

    def get(self, request):
        # Все три счёта подтягиваем тем же запросом: сериализатор читает их у
        # каждой строки, и без этого страница из 50 платежей — это 150 запросов.
        qs = (Payment.objects
              .select_related("user", "crypto_invoice", "gopay_invoice", "star_invoice")
              .order_by("-created_at", "-id"))

        provider = str(request.query_params.get("provider") or "").strip()
        if provider:
            qs = qs.filter(provider=provider)

        success = str(request.query_params.get("success") or "").strip()
        if success in ("0", "1"):
            qs = qs.filter(success=(success == "1"))

        is_test = str(request.query_params.get("is_test") or "").strip()
        if is_test in ("0", "1"):
            qs = qs.filter(is_test=(is_test == "1"))

        if str(request.query_params.get("needs_review") or "") == "1":
            qs = qs.filter(Q(crypto_invoice__flags__has_key="needs_review")
                           | Q(gopay_invoice__flags__has_key="needs_review"))

        if str(request.query_params.get("unsettled") or "") == "1":
            qs = qs.filter(pk__in=_unsettled_gopay_payment_ids())

        query = str(request.query_params.get("q") or "").strip()
        if query:
            qs = qs.filter(Q(order_id__icontains=query) | Q(user__email__icontains=query))

        count, page_qs = _paginate(qs, request)
        return Response({
            "count": count,
            "results": PaymentAdminSerializer(page_qs, many=True).data,
        })


# ------------------------------------------------------------------- blog ---

def _fill_blog_lang_defaults(validated_data):
    """en/kg-версии по умолчанию равны ru-версии (правило контракта на POST)."""
    if not validated_data.get("title_en"):
        validated_data["title_en"] = validated_data.get("title_ru", "")
    if not validated_data.get("title_kg"):
        validated_data["title_kg"] = validated_data.get("title_ru", "")
    if not validated_data.get("content_en"):
        validated_data["content_en"] = validated_data.get("content_ru", "")
    if not validated_data.get("content_kg"):
        validated_data["content_kg"] = validated_data.get("content_ru", "")


class BlogListCreateView(StaffAPIView):
    def get(self, request):
        qs = BlogPost.objects.all().order_by("-created_at")
        return Response(BlogPostListSerializer(qs, many=True).data)

    def post(self, request):
        ser = BlogPostFullSerializer(data=request.data)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        _fill_blog_lang_defaults(ser.validated_data)
        # published_at при is_published=True проставит BlogPost.save (правило публикации)
        post = ser.save()
        return Response(
            BlogPostFullSerializer(post).data, status=status.HTTP_201_CREATED
        )


class BlogDetailView(StaffAPIView):
    def get(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk)
        return Response(BlogPostFullSerializer(post).data)

    def patch(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk)
        ser = BlogPostFullSerializer(post, data=request.data, partial=True)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        post = ser.save()  # правило публикации — в BlogPost.save
        return Response(BlogPostFullSerializer(post).data)

    def delete(self, request, pk):
        post = get_object_or_404(BlogPost, pk=pk)
        post.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------- config ---

class ConfigView(StaffAPIView):
    """Read-only снимок биллинг-настроек из django settings."""

    def get(self, request):
        return Response({
            "welcome_bonus": getattr(settings, "WELCOME_BONUS_TOKENS", 0),
            "referral_bonus": getattr(settings, "REFERRAL_BONUS_TOKENS", 0),
            "daily_retention_target": getattr(settings, "DAILY_RETENTION_TARGET", 0),
            "web_search_surcharge": getattr(settings, "WEB_SEARCH_SURCHARGE_CREDITS", 0),
            "token_credit_divisor": getattr(settings, "TOKEN_CREDIT_DIVISOR", 1000),
            "free_daily_requests": getattr(settings, "FREE_DAILY_REQUESTS", 0),
            "paid_daily_requests": getattr(settings, "PAID_DAILY_REQUESTS", 0),
            "image_auto_route": bool(getattr(settings, "IMAGE_GEN_AUTO_ROUTE", True)),
        })


# ---------------------------------------------------------- exit-discount ---

class ExitDiscountStatsView(StaffAPIView):
    """Статистика воронки скидки при уходе со страницы pricing (pricing exit-intent).

    shown -> claimed -> redeemed. Проценты считаются от предыдущего шага
    воронки, а не от общего shown, чтобы показывать реальную конверсию
    каждого этапа.
    """

    def get(self, request):
        shown = ExitDiscountOffer.objects.filter(shown_at__isnull=False).count()
        claimed = ExitDiscountOffer.objects.filter(claimed_at__isnull=False).count()
        redeemed = ExitDiscountOffer.objects.filter(redeemed_at__isnull=False).count()
        claim_rate_pct = round(claimed / shown * 100, 1) if shown > 0 else 0
        redeem_rate_pct = round(redeemed / claimed * 100, 1) if claimed > 0 else 0
        return Response({
            "shown": shown,
            "claimed": claimed,
            "redeemed": redeemed,
            "claim_rate_pct": claim_rate_pct,
            "redeem_rate_pct": redeem_rate_pct,
        })


# --------------------------------------------------------------- settings ---

# Поля-инты контракта settings/: имя в API -> (runtime-ключ, settings-атрибут, дефолт)
_INT_SETTINGS = {
    "welcome_bonus": ("WELCOME_BONUS_TOKENS", "WELCOME_BONUS_TOKENS", 0),
    "referral_bonus": ("REFERRAL_BONUS_TOKENS", "REFERRAL_BONUS_TOKENS", 0),
    "daily_retention_target": ("DAILY_RETENTION_TARGET", "DAILY_RETENTION_TARGET", 0),
    # Порог: у кого баланс МЕНЬШЕ этого значения — тому ежедневный бонус
    # доводит баланс до daily_retention_target. Обычно равен target
    # («каждый день пополняем до N»). Держать рядом с target обязательно:
    # рассинхрон этих двух чисел уже один раз убил всю механику удержания.
    "daily_retention_threshold": ("DAILY_RETENTION_THRESHOLD", "DAILY_RETENTION_THRESHOLD", 0),
    "web_search_surcharge": ("WEB_SEARCH_SURCHARGE_CREDITS", "WEB_SEARCH_SURCHARGE_CREDITS", 0),
    "free_daily_requests": ("FREE_DAILY_REQUESTS", "FREE_DAILY_REQUESTS", 0),
    "paid_daily_requests": ("PAID_DAILY_REQUESTS", "PAID_DAILY_REQUESTS", 0),
    "exit_discount_minutes": ("EXIT_DISCOUNT_MINUTES", "EXIT_DISCOUNT_MINUTES", 15),
    # Калькулятор "На что хватит?" (Этап 3, п.14): пороги "разумно полезного
    # объёма" за категорию, используются plans/credit_value.py для выбора
    # recommended-пакета под сценарий использования.
    "credit_calc_text_min_count": ("credit_calc_text_min_count", "CREDIT_CALC_TEXT_MIN_COUNT", 200),
    "credit_calc_image_min_count": ("credit_calc_image_min_count", "CREDIT_CALC_IMAGE_MIN_COUNT", 100),
    "credit_calc_video_min_count": ("credit_calc_video_min_count", "CREDIT_CALC_VIDEO_MIN_COUNT", 5),
    "credit_calc_document_min_count": ("credit_calc_document_min_count", "CREDIT_CALC_DOCUMENT_MIN_COUNT", 200),
}

# Контакты сайта: email/phone — поля SiteSettings, остальное — social_links (JSON;
# отдельных колонок под address/facebook/... в модели нет).
_SITE_LINK_KEYS = ("address", "telegram", "instagram", "facebook", "twitter")

# Калькулятор ценности кредитов (plans/credit_value.py): поле API -> (runtime-ключ,
# settings-атрибут дефолта, требуемый GPTModels.category для валидации).
# category=None значит "любая КРОМЕ image/video" (нет отдельной GPTModels-категории
# 'text'/'document' — это просто обычная текстовая/чатовая модель).
_CREDIT_CALC_MODEL_FIELDS = {
    "credit_calc_text_model": ("credit_calc_text_model", "CREDIT_CALC_TEXT_MODEL_ID", None),
    "credit_calc_image_model": ("credit_calc_image_model", "CREDIT_CALC_IMAGE_MODEL_ID", "image"),
    "credit_calc_video_model": ("credit_calc_video_model", "CREDIT_CALC_VIDEO_MODEL_ID", "video"),
    "credit_calc_document_model": ("credit_calc_document_model", "CREDIT_CALC_DOCUMENT_MODEL_ID", None),
}


def _mask_key(key: str):
    """Первые 10 + последние 4 символа; полный ключ НИКОГДА не возвращаем.

    Для аномально коротких ключей (<=14 символов) префикс+суффикс покрыли бы
    ключ целиком — маскируем жёстче."""
    key = (key or "").strip()
    if not key:
        return None
    if len(key) <= 14:
        return f"{key[:2]}...{key[-2:]}"
    return f"{key[:10]}...{key[-4:]}"


# ------------------------------------------------------ единый QR (GoPay) ---

# Что можно прислать в блоке «gopay». force — не настройка, а подтверждение
# «удаляю ключ, хотя по среде есть незавершённые счета».
_GOPAY_PATCH_KEYS = ("mode", "env", "lifetime_minutes", "send_buyer_email", "test", "live", "force")


def _gopay_snapshot() -> dict:
    """Блок «gopay» снимка настроек: конфигурация и живое состояние.

    Значений секретов здесь нет вовсе: у публичного ключа — «…» и четыре
    последних символа, у двух секретов — только «задан / не задан».
    """
    from payments.gopay import config as gopay_config

    block = gopay_config.public_state()
    try:
        from django.db import transaction

        from payments.gopay import service as gopay_service

        # Счётчики читают базу. Точка сохранения: сбой чтения не должен
        # отравить транзакцию запроса — тогда трёх ключей просто нет, а
        # страница настроек открывается.
        with transaction.atomic():
            block.update(gopay_service.admin_state())
    except Exception:  # noqa: BLE001
        pass
    return block


def _gopay_bad(detail: str):
    return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)


def _drop_runtime_cache(keys) -> None:
    try:
        from django.core.cache import cache

        cache.delete_many([CACHE_PREFIX + key for key in keys])
    except Exception:  # noqa: BLE001 — кэш сам истечёт через полминуты
        pass


def _gopay_patch(request, raw):
    """Проверить и записать блок «gopay». Отказ — Response, иначе None.

    Сначала проверяется всё, потом пишется всё: блок сохраняется одной кнопкой,
    и ошибка в одном ключе не должна оставить уже переключённый режим.
    Ни один текст ошибки не повторяет присланное значение.
    """
    from django.db import transaction

    from audit.services import log_admin_action
    from payments.gopay import config as gopay_config
    from payments.gopay import service as gopay_service

    # Подменив ключи, можно увести оплаты покупателей на чужую точку GoPay —
    # поэтому это решение только главного администратора, а не любого сотрудника.
    if not request.user.is_superuser:
        return Response(
            {"code": "superuser_required",
             "detail": "Это действие доступно только главному администратору"},
            status=status.HTTP_403_FORBIDDEN)

    if not isinstance(raw, dict):
        return _gopay_bad("gopay должен быть объектом")
    if any(key not in _GOPAY_PATCH_KEYS for key in raw):
        return _gopay_bad("gopay: неизвестное поле; допустимо "
                          + ", ".join(_GOPAY_PATCH_KEYS))

    new_mode = new_env = new_lifetime = new_email = None
    if "mode" in raw:
        # Только строки: str(True) дал бы «true», а это не режим.
        value = raw["mode"]
        new_mode = value.strip().lower() if isinstance(value, str) else ""
        if new_mode not in gopay_config.MODES:
            return _gopay_bad("gopay: mode — допустимо off, staff или on")
    if "env" in raw:
        value = raw["env"]
        new_env = value.strip().lower() if isinstance(value, str) else ""
        if new_env not in gopay_config.ENVS:
            return _gopay_bad("gopay: env — допустимо test или live")
    if "lifetime_minutes" in raw:
        value = raw["lifetime_minutes"]
        # bool — подкласс int: True стал бы «1 минутой».
        if (isinstance(value, bool) or not isinstance(value, int)
                or not (gopay_config.LIFETIME_MIN_MINUTES <= value
                        <= gopay_config.LIFETIME_MAX_MINUTES)):
            return _gopay_bad(
                f"gopay: lifetime_minutes — целое число от {gopay_config.LIFETIME_MIN_MINUTES} "
                f"до {gopay_config.LIFETIME_MAX_MINUTES}")
        new_lifetime = value
    if "send_buyer_email" in raw:
        # Строка "false" из формы стала бы True — а это передача почты наружу.
        if not isinstance(raw["send_buyer_email"], bool):
            return _gopay_bad("gopay: send_buyer_email — true или false")
        new_email = raw["send_buyer_email"]
    if "force" in raw and not isinstance(raw["force"], bool):
        return _gopay_bad("gopay: force — true или false")
    force = raw.get("force") is True

    # (среда, поле) -> новое значение; пустая строка — убрать значение из админки.
    secrets = {}
    for env_name in gopay_config.ENVS:
        if env_name not in raw:
            continue
        block = raw[env_name]
        if not isinstance(block, dict):
            return _gopay_bad(f"gopay: {env_name} должен быть объектом")
        if any(key not in gopay_config.SECRET_FIELDS for key in block):
            return _gopay_bad(f"gopay: {env_name} — неизвестное поле; допустимо "
                              + ", ".join(gopay_config.SECRET_FIELDS))
        for field in gopay_config.SECRET_FIELDS:
            if field not in block:
                continue
            try:
                secrets[(env_name, field)] = gopay_config.clean_secret(block[field])
            except ValueError as exc:
                # Текст clean_secret значения не содержит — только требование.
                return _gopay_bad(f"gopay: {env_name}.{field} — {exc}")

    current = {env_name: gopay_config.credentials(env_name) for env_name in gopay_config.ENVS}

    def resulting(env_name: str, field: str) -> str:
        """Каким ключ станет после этого запроса."""
        if (env_name, field) not in secrets:
            return getattr(current[env_name], field)
        # Удалили значение из админки — снова действует ключ из окружения.
        fallback = getattr(settings, gopay_config.runtime_key(env_name, field), "")
        return secrets[(env_name, field)] or str(fallback or "").strip()

    # Наличие ключей проверяем, только когда сам запрос может сделать QR
    # видимым: включает режим или трогает среду. Сохранить одни ключи можно
    # всегда — первым действием владельца вполне может быть ввод боевой пары
    # при ещё тестовой среде, и отказ «введите ключ» сразу после ввода ключа
    # был бы нелепым. Видимым такой запрос ничего не делает: среду без ключей
    # не показывает сама проверка доступности.
    if (new_mode is not None and new_mode != gopay_config.MODE_OFF) or new_env is not None:
        mode_after = new_mode if new_mode is not None else gopay_config.mode()
        env_after = new_env if new_env is not None else gopay_config.env()
        if mode_after != gopay_config.MODE_OFF and not (
                resulting(env_after, "api_key") and resulting(env_after, "api_secret")):
            return _gopay_bad("gopay: сначала введите API-ключ и секрет для выбранной среды")
        if mode_after == gopay_config.MODE_ON and not resulting(env_after, "webhook_secret"):
            # Без секрета вебхуков оплату узнаём только опросом — для всех
            # покупателей так открывать нельзя.
            return _gopay_bad("gopay: для режима «Включено» нужен секрет вебхуков")

    # Одинаковый ключ в обеих средах — значит, тестовую пару вставили в боевые
    # поля или наоборот: счёт создался бы не в той среде.
    test_key = resulting(gopay_config.ENV_TEST, "api_key")
    if test_key and test_key == resulting(gopay_config.ENV_LIVE, "api_key"):
        return _gopay_bad("gopay: ключи Test и Live совпадают")

    # Ключи, которыми ещё кто-то пользуется. Статус счёта спрашивается ключами
    # ЕГО среды: уберём их — оплаченный счёт не зачислится. Удаление требует
    # подтверждения, замена (ротация) разрешена, но попадает в журнал.
    in_flight = {}
    for env_name in gopay_config.ENVS:
        changed = [field for field in gopay_config.SECRET_FIELDS
                   if (env_name, field) in secrets
                   and resulting(env_name, field) != getattr(current[env_name], field)]
        if not changed:
            continue
        count = gopay_service.in_flight_count(env_name)
        if count <= 0:
            continue
        if not force and any(secrets[(env_name, field)] == "" for field in changed):
            return Response(
                {"code": "gopay_in_flight", "count": count,
                 "detail": (f"gopay: по этой среде есть незавершённые QR-счета ({count}). "
                            "Без ключей оплаченный счёт не будет зачислен. "
                            "Повторите с подтверждением, если уверены.")},
                status=status.HTTP_409_CONFLICT)
        in_flight[env_name] = count

    # --- запись ---
    writes = []      # (runtime-ключ, значение); None — удалить строку
    if new_mode is not None:
        writes.append((gopay_config.RT_MODE, new_mode))
    if new_env is not None:
        writes.append((gopay_config.RT_ENV, new_env))
    if new_lifetime is not None:
        writes.append((gopay_config.RT_LIFETIME, new_lifetime))
    if new_email is not None:
        writes.append((gopay_config.RT_SEND_BUYER_EMAIL, new_email))
    for (env_name, field), value in secrets.items():
        writes.append((gopay_config.runtime_key(env_name, field), value if value else None))
    if not writes:
        return None

    keys = [key for key, _value in writes]
    before = gopay_config.public_state()
    try:
        for key, value in writes:
            if value is None:
                delete_runtime(key)
            else:
                set_runtime(key, value)
        # public_state() значений не содержит — значит, их нет и в журнале.
        after = {"gopay": gopay_config.public_state()}
        if in_flight:
            after["gopay_in_flight"] = in_flight
        # В журнал — в той же транзакции: не записалось, откатятся и настройки.
        log_admin_action(request.user, "settings.edit", before={"gopay": before},
                         after=after, request=request)
    except Exception:
        # Запрос откатится, а в кэше уже лежат значения, которых в базе не будет.
        _drop_runtime_cache(keys)
        raise
    # Пока транзакция не закрыта, соседний процесс мог прочитать из базы старое
    # значение и положить его в кэш на полминуты — после фиксации сбрасываем.
    transaction.on_commit(lambda: _drop_runtime_cache(keys))
    return None


def _settings_snapshot() -> dict:
    """Единый снимок для GET и ответа PATCH (контракт settings/)."""
    site = SiteSettings.get_solo()
    links = site.social_links or {}
    snapshot = {
        "openrouter_key_masked": _mask_key(_effective_openrouter_key()),
        "image_auto_route": bool(get_runtime(
            "IMAGE_GEN_AUTO_ROUTE",
            bool(getattr(settings, "IMAGE_GEN_AUTO_ROUTE", True)),
        )),
        "site": {
            "email": site.contact_email or "",
            "phone": site.contact_phone or "",
            **{k: str(links.get(k) or "") for k in _SITE_LINK_KEYS},
        },
    }
    for field, (rt_key, settings_attr, default) in _INT_SETTINGS.items():
        base = int(getattr(settings, settings_attr, default) or 0)
        snapshot[field] = int(get_runtime(rt_key, base))
    # referral_percent: 0..100, дефолт 10 (согласовано с клиентом)
    snapshot["referral_percent"] = int(get_runtime("REFERRAL_PERCENT", 10))
    # exit_discount_percent: 0..100, дефолт из settings.EXIT_DISCOUNT_PERCENT (env, 20)
    snapshot["exit_discount_percent"] = int(get_runtime(
        "EXIT_DISCOUNT_PERCENT",
        int(getattr(settings, "EXIT_DISCOUNT_PERCENT", 20)),
    ))
    # exit_discount_enabled: общий выключатель оффера скидки при уходе
    snapshot["exit_discount_enabled"] = bool(get_runtime(
        "EXIT_DISCOUNT_ENABLED",
        bool(getattr(settings, "EXIT_DISCOUNT_ENABLED", True)),
    ))
    # currency_kgs_to_rub_rate: витринный курс KGS -> RUB для переключателя
    # валют на /pricing (НЕ платёжный курс, см. plans/views.py CurrencyRateView
    # и settings.CURRENCY_KGS_TO_RUB_RATE) — админ обязан держать его актуальным.
    snapshot["currency_kgs_to_rub_rate"] = float(get_runtime(
        "currency_kgs_to_rub_rate",
        float(getattr(settings, "CURRENCY_KGS_TO_RUB_RATE", 0.95)),
    ))
    # --- криптооплата ---
    # Режим виден всегда: по нему сразу понятно, открыт ли способ оплаты и кому.
    # Ключи наружу не отдаются никогда — только маска и признак «задан».
    from payments.crypto import currencies as _crypto_currencies
    from payments.crypto import rates as _crypto_rates
    from payments.crypto import registry as _crypto_registry

    snapshot["crypto_payments_mode"] = _crypto_registry.mode()
    snapshot["crypto_configured"] = _crypto_registry.is_configured()
    # --- видеостудия: режим off/staff/on ---
    # Действующий режим (правка из админки поверх VSTUDIO_MODE из окружения)
    # и значение окружения — видно, переопределён ли он здесь.
    snapshot["vstudio_mode_env"] = str(getattr(settings, "VSTUDIO_MODE", "staff") or "staff")
    snapshot["vstudio_mode_override"] = str(get_runtime("vstudio_mode", "") or "")
    try:
        from vstudio.views import studio_mode as _vstudio_mode

        snapshot["vstudio_mode"] = _vstudio_mode()
    except Exception:  # noqa: BLE001 — приложение не подключено: показываем окружение
        snapshot["vstudio_mode"] = snapshot["vstudio_mode_env"]
    from cartoon import audio as _studio_audio

    snapshot["elevenlabs_configured"] = _studio_audio.is_configured()
    snapshot["elevenlabs_key_masked"] = _mask_key(_studio_audio.api_key())
    _audio_prices = _studio_audio.prices()
    snapshot["studio_voice_credits_per_1k"] = _audio_prices["voice_per_1k"]
    snapshot["studio_voice_min_credits"] = _audio_prices["voice_min"]
    snapshot["studio_music_credits_per_min"] = _audio_prices["music_per_min"]
    snapshot["studio_sfx_credits"] = _audio_prices["sfx"]
    from cartoon.pricing import studio_scene_price as _studio_scene_price

    snapshot["studio_scene_credits"] = _studio_scene_price()
    snapshot["nowpayments_key_masked"] = _mask_key(_crypto_registry.api_key())
    snapshot["nowpayments_ipn_secret_masked"] = _mask_key(_crypto_registry.ipn_secret())
    snapshot["nowpayments_sandbox"] = bool(getattr(settings, "NOWPAYMENTS_SANDBOX", False))
    snapshot["crypto_allowed_currencies"] = ",".join(_crypto_currencies.allowed_codes())
    snapshot["crypto_fee_paid_by_user"] = _crypto_registry.fee_paid_by_user()
    snapshot["nowpayments_fixed_rate"] = _crypto_registry.fixed_rate()
    snapshot["crypto_settlement_currency"] = _crypto_registry.settlement_currency()
    # Курс, по которому реально выставляется счёт, и рядом — рыночный, чтобы
    # админ видел, насколько зафиксированное вручную значение отстало.
    snapshot["currency_kgs_to_usd_rate"] = float(_crypto_rates.kgs_to_usd_rate())
    snapshot["currency_kgs_to_usd_manual"] = float(get_runtime("currency_kgs_to_usd_rate", 0.0))
    market = _crypto_rates.market_rate()
    snapshot["currency_kgs_to_usd_market"] = float(market) if market else None

    # --- оплата в сомах: выбор способа до ухода на FreedomPay ---
    # Отдаём действующие значения: включённые способы уже с единым QR, если
    # его код задан, — так в админке видно ровно то, что увидит покупатель.
    from payments import kgs_methods as _kgs_methods

    snapshot["kgs_methods_mode"] = _kgs_methods.mode()
    snapshot["kgs_methods_enabled"] = ",".join(_kgs_methods.enabled_keys())
    snapshot["kgs_elqr_ps_code"] = _kgs_methods.elqr_code()
    snapshot["kgs_methods_known"] = list(_kgs_methods.ORDER)

    # --- единый QR (GoPay) ---
    snapshot["gopay"] = _gopay_snapshot()

    # Калькулятор ценности кредитов: эталонные модели по категориям (openrouter_id)
    # + размер "страницы" документа в токенах.
    for field, (rt_key, settings_attr, _category) in _CREDIT_CALC_MODEL_FIELDS.items():
        default_id = str(getattr(settings, settings_attr, "") or "")
        snapshot[field] = str(get_runtime(rt_key, default_id))
    snapshot["credit_calc_document_tokens_per_page"] = int(get_runtime(
        "credit_calc_document_tokens_per_page",
        int(getattr(settings, "CREDIT_CALC_DOCUMENT_TOKENS_PER_PAGE", 650) or 650),
    ))
    # "Типичный" размер текстового сообщения в токенах (см. credit_value.py) —
    # ОЦЕНКА, не измеренное значение (см. комментарий у settings.CREDIT_CALC_TEXT_TOKENS_PER_REPLY).
    snapshot["credit_calc_text_tokens_per_reply"] = int(get_runtime(
        "credit_calc_text_tokens_per_reply",
        int(getattr(settings, "CREDIT_CALC_TEXT_TOKENS_PER_REPLY", 2500) or 2500),
    ))
    return snapshot


class SettingsView(StaffAPIView):
    """Runtime-настройки: меняются из админки без рестарта (хранятся в AppSetting).

    Кэш get_runtime — 30с, поэтому воркеры подхватывают новые значения максимум
    через полминуты. daily_retention_target celery-таск прочитает только после
    пересборки celery-контейнера (его код запечён).
    """

    def get(self, request):
        return Response(_settings_snapshot())

    def patch(self, request):
        data = request.data or {}

        # --- единый QR (GoPay): режим, среда, срок счёта, ключи ---
        # Первым блоком: отказ (права, проверка, ключи в работе) должен
        # случиться до того, как из этого запроса записано хоть что-то.
        if "gopay" in data:
            refusal = _gopay_patch(request, data["gopay"])
            if refusal is not None:
                return refusal

        # --- целочисленные настройки (>= 0) ---
        for field, (rt_key, _attr, _d) in _INT_SETTINGS.items():
            if field not in data:
                continue
            try:
                value = int(data[field])
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"{field} должен быть целым числом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if value < 0:
                return Response(
                    {"detail": f"{field} не может быть отрицательным"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime(rt_key, value)

        # --- реферальный процент (0..100) ---
        if "referral_percent" in data:
            try:
                percent = int(data["referral_percent"])
            except (TypeError, ValueError):
                return Response(
                    {"detail": "referral_percent должен быть целым числом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if percent < 0 or percent > 100:
                return Response(
                    {"detail": "referral_percent должен быть в диапазоне 0..100"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("REFERRAL_PERCENT", percent)

        # --- процент скидки при уходе со страницы pricing (0..100) ---
        if "exit_discount_percent" in data:
            try:
                percent = int(data["exit_discount_percent"])
            except (TypeError, ValueError):
                return Response(
                    {"detail": "exit_discount_percent должен быть целым числом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if percent < 0 or percent > 100:
                return Response(
                    {"detail": "exit_discount_percent должен быть в диапазоне 0..100"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("EXIT_DISCOUNT_PERCENT", percent)

        # --- тумблер авто-роутинга картинок ---
        if "image_auto_route" in data:
            set_runtime("IMAGE_GEN_AUTO_ROUTE", bool(data["image_auto_route"]))

        # --- тумблер оффера скидки при уходе со страницы pricing ---
        if "exit_discount_enabled" in data:
            set_runtime("EXIT_DISCOUNT_ENABLED", bool(data["exit_discount_enabled"]))

        # --- курс KGS -> RUB для витринного переключателя валют (0.01..100) ---
        if "currency_kgs_to_rub_rate" in data:
            try:
                rate = float(data["currency_kgs_to_rub_rate"])
            except (TypeError, ValueError):
                return Response(
                    {"detail": "currency_kgs_to_rub_rate должен быть числом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if rate <= 0 or rate > 100:
                return Response(
                    {"detail": "currency_kgs_to_rub_rate должен быть в диапазоне 0..100"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("currency_kgs_to_rub_rate", rate)

        # --- калькулятор ценности кредитов: эталонные модели по категориям ---
        for field, (rt_key, _attr, required_category) in _CREDIT_CALC_MODEL_FIELDS.items():
            if field not in data:
                continue
            # null/"" явно переданное — сброс override'а обратно на settings-дефолт
            # (delete_runtime), а НЕ ошибка валидации и НЕ запись пустой строки.
            if data[field] is None or str(data[field]).strip() == "":
                delete_runtime(rt_key)
                continue
            openrouter_id = str(data[field]).strip()
            qs = GPTModels.objects.filter(openrouter_id=openrouter_id, is_active=True)
            if required_category:
                qs = qs.filter(category=required_category)
            else:
                qs = qs.exclude(category__in=["image", "video"])
            if not qs.exists():
                return Response(
                    {"detail": (
                        f"{field}: модель с openrouter_id={openrouter_id!r} не найдена, "
                        f"неактивна или не подходит по категории"
                    )},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime(rt_key, openrouter_id)

        # --- калькулятор ценности кредитов: токенов на "страницу" документа ---
        if "credit_calc_document_tokens_per_page" in data:
            raw = data["credit_calc_document_tokens_per_page"]
            if raw is None or str(raw).strip() == "":
                delete_runtime("credit_calc_document_tokens_per_page")
            else:
                try:
                    tokens_per_page = int(raw)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "credit_calc_document_tokens_per_page должен быть целым числом"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if tokens_per_page <= 0:
                    return Response(
                        {"detail": "credit_calc_document_tokens_per_page должен быть больше нуля"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                set_runtime("credit_calc_document_tokens_per_page", tokens_per_page)

        # --- калькулятор ценности кредитов: "типичный" размер сообщения в токенах ---
        if "credit_calc_text_tokens_per_reply" in data:
            raw = data["credit_calc_text_tokens_per_reply"]
            if raw is None or str(raw).strip() == "":
                delete_runtime("credit_calc_text_tokens_per_reply")
            else:
                try:
                    tokens_per_reply = int(raw)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "credit_calc_text_tokens_per_reply должен быть целым числом"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if tokens_per_reply <= 0:
                    return Response(
                        {"detail": "credit_calc_text_tokens_per_reply должен быть больше нуля"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                set_runtime("credit_calc_text_tokens_per_reply", tokens_per_reply)

        # --- видеостудия: режим off/staff/on; пустое значение — вернуть окружение ---
        if "vstudio_mode" in data:
            mode = str(data["vstudio_mode"] or "").strip().lower()
            if mode == "":
                delete_runtime("vstudio_mode")
            elif mode in ("off", "staff", "on"):
                set_runtime("vstudio_mode", mode)
            else:
                return Response(
                    {"detail": "vstudio_mode: допустимо off, staff, on или пусто (как в окружении)"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # --- криптооплата: режим, ключи, курс, монеты ---
        if "crypto_payments_mode" in data:
            from payments.crypto import registry as crypto_registry

            mode = str(data["crypto_payments_mode"] or "").strip().lower()
            if mode not in crypto_registry.MODES:
                return Response(
                    {"detail": "crypto_payments_mode: допустимо off, staff или on"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("crypto_payments_mode", mode)

        # --- оплата в сомах: режим выбора способа, список способов, код единого QR ---
        # Блок в админке сохраняется одной кнопкой, поэтому сначала проверяем
        # все три поля и только потом пишем: иначе ошибка в коде QR оставила бы
        # уже переключённый режим, а человек видел бы «не сохранено».
        if any(k in data for k in ("kgs_methods_mode", "kgs_methods_enabled", "kgs_elqr_ps_code")):
            from payments import kgs_methods

            kgs_mode = kgs_enabled = kgs_code = None
            if "kgs_methods_mode" in data:
                # Только строки: str(True) дал бы «True» — а для кода QR это
                # уже годное по виду значение, которое ушло бы в FreedomPay.
                raw_mode = data["kgs_methods_mode"]
                kgs_mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else ""
                if kgs_mode not in kgs_methods.MODES:
                    return Response(
                        {"detail": "kgs_methods_mode: допустимо off, staff или on"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            if "kgs_methods_enabled" in data:
                raw_enabled = data["kgs_methods_enabled"]
                # null и прочие не-списки молча выключили бы все способы разом.
                if not (isinstance(raw_enabled, str) or (
                        isinstance(raw_enabled, (list, tuple))
                        and all(isinstance(item, str) for item in raw_enabled))):
                    return Response(
                        {"detail": "kgs_methods_enabled: список способов — строкой через "
                                   "запятую или массивом строк"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                kgs_enabled, unknown = kgs_methods.normalize_enabled(raw_enabled)
                if unknown:
                    return Response(
                        {"detail": "kgs_methods_enabled: неизвестный способ оплаты — "
                                   + ", ".join(unknown)},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            if "kgs_elqr_ps_code" in data:
                raw_code = data["kgs_elqr_ps_code"]
                if raw_code is not None and not isinstance(raw_code, str):
                    return Response(
                        {"detail": "kgs_elqr_ps_code: код платёжной системы — строка"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                kgs_code = (raw_code or "").strip()
                if kgs_code and not kgs_methods.ELQR_CODE_RE.fullmatch(kgs_code):
                    return Response(
                        {"detail": "kgs_elqr_ps_code: код платёжной системы от Freedom Pay — "
                                   "латинские буквы, цифры и «_», от 3 до 32 символов"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            if kgs_mode is not None:
                set_runtime("kgs_methods_mode", kgs_mode)
            if kgs_enabled is not None:
                # Храним в порядке показа и без единого QR: он включается своим кодом.
                set_runtime("kgs_methods_enabled", ",".join(kgs_enabled))
            if kgs_code:
                set_runtime("kgs_elqr_ps_code", kgs_code)
            elif kgs_code is not None:
                # Пусто — кода нет: кнопка единого QR пропадает с витрины.
                delete_runtime("kgs_elqr_ps_code")

        # Звук и сцены студии: цены — целые неотрицательные (0 у сцены — по тарифу модели).
        for field in ("studio_voice_credits_per_1k", "studio_voice_min_credits",
                      "studio_music_credits_per_min", "studio_sfx_credits",
                      "studio_scene_credits"):
            if field not in data:
                continue
            try:
                value = int(data[field])
            except (TypeError, ValueError):
                return Response({"detail": f"{field} должен быть целым числом"},
                                status=status.HTTP_400_BAD_REQUEST)
            if value < 0 or value > 100000:
                return Response({"detail": f"{field} должен быть в диапазоне 0..100000"},
                                status=status.HTTP_400_BAD_REQUEST)
            set_runtime(field, value)

        # Ключи — write-only. Пустая строка означает «убрать значение из
        # админки», чтобы снова действовал ключ из окружения.
        for field, rt_key in (("nowpayments_api_key", "NOWPAYMENTS_API_KEY"),
                              ("nowpayments_ipn_secret", "NOWPAYMENTS_IPN_SECRET"),
                              ("elevenlabs_api_key", "ELEVENLABS_API_KEY")):
            if field not in data:
                continue
            value = str(data[field] or "").strip()
            if value:
                set_runtime(rt_key, value)
            else:
                delete_runtime(rt_key)

        if "currency_kgs_to_usd_rate" in data:
            raw = data["currency_kgs_to_usd_rate"]
            # Ручной курс — первый источник базы комиссии креаторов: от него
            # зависит сумма USDT по каждой оплате в сомах и рублях.
            old_rate = get_runtime("currency_kgs_to_usd_rate", 0.0) or None
            new_rate = None
            if raw is None or str(raw).strip() == "":
                # Сброс на живой курс из CurrencyRate — так и должно быть по
                # умолчанию, ручная фиксация нужна только в особых случаях.
                delete_runtime("currency_kgs_to_usd_rate")
            else:
                try:
                    usd_rate = float(raw)
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "currency_kgs_to_usd_rate должен быть числом"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                # Один сом дороже доллара не бывает; ошибка в этом поле — это
                # счёт в сто раз больше или меньше.
                if not (0 < usd_rate <= 1):
                    return Response(
                        {"detail": "currency_kgs_to_usd_rate должен быть в диапазоне 0..1"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                set_runtime("currency_kgs_to_usd_rate", usd_rate)
                new_rate = usd_rate
            if new_rate != old_rate:
                # В журнал — в той же транзакции: не записалось, откатится и курс.
                from audit.services import log_admin_action

                log_admin_action(request.user, "settings.edit",
                                 before={"currency_kgs_to_usd_rate": old_rate},
                                 after={"currency_kgs_to_usd_rate": new_rate},
                                 request=request)

        if "crypto_fee_paid_by_user" in data:
            from django.core.cache import cache as _cache
            from payments.crypto.views import currencies_cache_key as _cur_key

            raw = data["crypto_fee_paid_by_user"]
            # Строка "false" из формы превращалась бы bool()-ом в True — а это
            # флаг, по которому у покупателя берут комиссию сверху.
            if isinstance(raw, bool):
                fee_by_user = raw
            elif str(raw).strip().lower() in ("1", "true", "yes", "on"):
                fee_by_user = True
            elif str(raw).strip().lower() in ("0", "false", "no", "off"):
                fee_by_user = False
            else:
                return Response(
                    {"detail": "crypto_fee_paid_by_user должен быть булевым"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("crypto_fee_paid_by_user", fee_by_user)
            # Флаг отдаётся вместе со списком монет — сбрасываем его кэш.
            _cache.delete(_cur_key())

        if "crypto_settlement_currency" in data:
            from django.core.cache import cache as _cache
            from payments.crypto.views import currencies_cache_key as _cur_key3

            # Кэш сбрасываем ДО смены значения: ключ включает валюту выплат,
            # и после смены старый ключ уже не найти.
            _cache.delete(_cur_key3())
            code = str(data["crypto_settlement_currency"] or "").strip().lower()
            if code and not re.fullmatch(r"[a-z0-9]{2,20}", code):
                return Response(
                    {"detail": "crypto_settlement_currency: код монеты процессора, например usdtbsc"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if code:
                set_runtime("crypto_settlement_currency", code)
            else:
                delete_runtime("crypto_settlement_currency")

        if "crypto_allowed_currencies" in data:
            from django.core.cache import cache as _cache

            raw = data["crypto_allowed_currencies"]
            codes = raw if isinstance(raw, list) else str(raw or "").split(",")
            cleaned = [str(c).strip().lower() for c in codes if str(c).strip()]
            set_runtime("crypto_allowed_currencies", ",".join(cleaned))
            # Список монет кэшируется на витрине — сбрасываем, иначе изменение
            # доедет только через десять минут.
            from payments.crypto.views import currencies_cache_key as _cur_key2

            _cache.delete(_cur_key2())

        # --- ключ OpenRouter (write-only: назад отдаём только маску) ---
        if "openrouter_key" in data:
            key = str(data["openrouter_key"] or "").strip()
            if not key:
                return Response(
                    {"detail": "openrouter_key не может быть пустым"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            set_runtime("OPENROUTER_API_KEY", key)

        # --- контакты сайта (SiteSettings-синглтон) ---
        site_patch = data.get("site")
        if site_patch is not None:
            if not isinstance(site_patch, dict):
                return Response(
                    {"detail": "site должен быть объектом"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            site = SiteSettings.get_solo()
            if "email" in site_patch:
                site.contact_email = str(site_patch["email"] or "").strip()
            if "phone" in site_patch:
                site.contact_phone = str(site_patch["phone"] or "").strip()
            links = dict(site.social_links or {})
            for k in _SITE_LINK_KEYS:
                if k in site_patch:
                    links[k] = str(site_patch[k] or "").strip()
            site.social_links = links
            site.save()

        # Цена сцены мультфильма и курс сом→$ (по нему считается цена кредита)
        # входят в цены: без сброса кэша они доезжали бы через десять минут.
        if "studio_scene_credits" in data or "currency_kgs_to_usd_rate" in data:
            from . import prices

            prices.invalidate()

        return Response(_settings_snapshot())


class PaymentRecheckView(StaffAPIView):
    """POST /payments/<id>/recheck/ — спросить процессор заново.

    Нужна, когда вебхук не дошёл, а деньги человек отправил: вместо ручного
    начисления «на глаз» админ жмёт кнопку, и платёж проходит ровно тот же
    путь, что и обычно, — со всеми проверками и идемпотентностью.
    """

    def post(self, request, pk):
        payment = get_object_or_404(Payment, pk=pk)
        invoice = getattr(payment, "crypto_invoice", None)

        # Единый QR (GoPay): спрашиваем статус сами, ключами среды счёта, и
        # применяем ответ тем же путём, что вебхук и сверка, — с теми же
        # проверками и той же идемпотентностью. Предохранитель «GoPay не
        # отвечает» здесь не действует: кнопку нажал человек.
        if invoice is None:
            from payments.gopay import service as gopay_service
            from payments.gopay.client import GoPayError

            gp = gopay_service.invoice_of(payment)
            if gp is not None:
                try:
                    result = gopay_service.refresh_invoice(gp, source="admin")
                except GoPayError as exc:
                    # В ответ идёт только наш короткий код, без текста GoPay.
                    return Response({"detail": f"GoPay не ответил: {exc.code}"},
                                    status=status.HTTP_502_BAD_GATEWAY)
                payment.refresh_from_db()
                return Response({"result": result,
                                 "payment": PaymentAdminSerializer(payment).data})
            if payment.provider == "gopay":
                # Счёт у GoPay создать не удалось: общая сверка FreedomPay такой
                # платёж не знает, а «в очереди» было бы неправдой.
                return Response(
                    {"detail": "QR по этому заказу не был создан — проверять нечего."},
                    status=status.HTTP_400_BAD_REQUEST)

        if invoice is None:
            # Не крипта — отдаём задаче сверки FreedomPay, она умеет это сама.
            from payments.tasks import reconcile_pending_token_payments

            try:
                reconcile_pending_token_payments.delay()
            except Exception:  # noqa: BLE001
                return Response({"detail": "Очередь недоступна"},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
            return Response({"queued": True})

        from payments.crypto import credit as crypto_credit
        from payments.crypto import registry as crypto_registry
        from payments.crypto.base import ProviderError

        try:
            state = crypto_registry.get_adapter(invoice.provider).fetch_invoice(
                invoice.provider_invoice_id)
        except ProviderError as exc:
            return Response({"detail": f"Процессор не ответил: {exc}"},
                            status=status.HTTP_502_BAD_GATEWAY)
        result = crypto_credit.apply_provider_status(invoice, state, source="admin")
        payment.refresh_from_db()
        return Response({"result": result,
                         "payment": PaymentAdminSerializer(payment).data})


class PaymentRefundStarsView(StaffAPIView):
    """POST /payments/<id>/refund-stars/ {reason, force} — вернуть Stars покупателю.

    Возврат в Telegram только полный; кредиты изымаются тем же клобэком, что
    и при возврате карточной оплаты. Если человек уже потратил кредиты, без
    force возврат не делаем — это спор, а не кнопка.

    Если по платежу начислена комиссия креатора, возврат отменяет и её — это
    уже денежное решение («отметить платёж возвращённым»), его принимает
    только главный администратор. Платежи без комиссии возвращает любой
    сотрудник, как и раньше.
    """

    def post(self, request, pk):
        import logging

        from django.db import transaction

        from botapi import stars as stars_service

        payment = get_object_or_404(Payment, pk=pk)
        invoice = getattr(payment, "star_invoice", None)
        if invoice is None:
            return Response({"detail": "not_stars_payment"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            from creators.commission import open_for_payment

            # Точка сохранения: сбой чтения не должен отравить транзакцию запроса.
            with transaction.atomic():
                rows = open_for_payment(payment.pk)
            needs_su = bool(rows)
        except Exception:  # noqa: BLE001
            # Не смогли проверить — считаем, что комиссия есть: лучше отказать
            # сотруднику, чем молча отменить чужой заработок.
            logging.getLogger("creators").exception(
                "refund-stars: комиссии платежа %s не прочитаны", payment.pk)
            rows, needs_su = [], True
        if needs_su and not request.user.is_superuser:
            # До любого обращения к Telegram.
            return Response(
                {"code": "superuser_required",
                 "detail": "Это действие доступно только главному администратору"},
                status=status.HTTP_403_FORBIDDEN)

        reason = str((request.data or {}).get("reason") or "admin")[:120]
        force = bool((request.data or {}).get("force"))
        try:
            result = stars_service.refund(invoice, reason=reason, by=request.user, force=force)
        except stars_service.StarsError as exc:
            return Response({"detail": exc.code, **exc.extra}, status=exc.http)

        # Обычно комиссию уже отменил общий код возврата (изъятие кредитов);
        # вызов здесь закрывает платёж без пользователя, куда тот код не доходит.
        from payments.referral import reverse_creator_commission

        if result.get("status") != "foreign_charge":
            # foreign_charge — возвращён другой платёж по тому же счёту: этот не трогаем.
            reverse_creator_commission(payment, "refund:telegram_stars")
        try:
            from audit.services import log_admin_action

            # Stars уже возвращены в Telegram: сбой записи журнала не должен
            # откатить отметку о возврате, поэтому своя точка сохранения.
            with transaction.atomic():
                log_admin_action(
                    request.user, "payment.mark_refunded", target=payment,
                    creator=rows[0].creator if rows else None,
                    after={"kind": "refund", "via": "refund-stars", "reversed": len(rows),
                           "result": result.get("status")},
                    reason=reason, request=request)
        except Exception:  # noqa: BLE001
            logging.getLogger("creators").exception(
                "refund-stars: запись в журнал не сделана, платёж %s", payment.pk)

        payment.refresh_from_db()
        return Response({"result": result, "payment": PaymentAdminSerializer(payment).data})


class SettingsTestElevenLabsView(StaffAPIView):
    """Проверка ключа ElevenLabs: {ok, error, voices}."""

    def post(self, request):
        from cartoon import audio as studio_audio

        return Response(studio_audio.healthcheck())


class SettingsTestNowPaymentsView(StaffAPIView):
    """Проверка подключения к крипто-процессору: {ok, error, coins}."""

    def post(self, request):
        from payments.crypto import registry as crypto_registry

        if not crypto_registry.is_configured():
            return Response({"ok": False, "error": "API-ключ NOWPayments не задан."})
        try:
            return Response(crypto_registry.get_adapter().healthcheck())
        except Exception as exc:  # noqa: BLE001
            return Response({"ok": False, "error": str(exc)[:200]})


class SettingsTestGoPayView(StaffAPIView):
    """Проверка ключей единого QR: {env?} -> {ok, env, apps, webhook_secret_set, error, provider_code}.

    Шлёт GoPay безвредный подписанный запрос списка банковских приложений
    ключами выбранной среды (без env — активной). Чего зелёный ответ НЕ
    доказывает: тестовая это пара или боевая и активирована ли организация —
    это покажет только первый созданный QR. Пустой список приложений — успех:
    у тестового ключа банков может не быть вовсе.
    """

    _IP_HINT = " Проверьте также ограничение по IP для боевого ключа в кабинете GoPay."

    @classmethod
    def _error_text(cls, env: str, result: dict) -> str:
        kind = str(result.get("kind") or "other")
        if kind == "auth":
            text = "GoPay не принял ключ или подпись. Проверьте API-ключ и секрет."
        elif kind == "org_inactive":
            text = "Организация в GoPay не активирована (код 0016)."
        elif kind == "rate_limited":
            text = "Лимит запросов GoPay, повторите через минуту."
        elif kind == "unavailable":
            text = ("GoPay не отвечает. Проверьте сеть сервера и ограничение по IP "
                    "для боевого ключа.")
        else:
            code = result.get("provider_code") or result.get("http_status") or ""
            text = "GoPay отклонил запрос" + (f" (код {code})" if code else "") + "."
        # Как GoPay отвечает адресу не из белого списка, не описано: это может
        # быть и 401/403 (JSON или HTML), а не таймаут.
        if env == "live" and kind in ("auth", "other"):
            text += cls._IP_HINT
        return text

    def post(self, request):
        from payments.gopay import client as gopay_client
        from payments.gopay import config as gopay_config
        from payments.gopay import service as gopay_service

        data = request.data if hasattr(request.data, "get") else {}
        env = data.get("env")
        if env is None:
            env = gopay_config.env()
        elif not isinstance(env, str) or env not in gopay_config.ENVS:
            return Response({"detail": "env: допустимо test или live"},
                            status=status.HTTP_400_BAD_REQUEST)

        answer = {"ok": False, "env": env, "apps": None, "webhook_secret_set": False,
                  "error": None, "provider_code": None}
        try:
            answer["webhook_secret_set"] = bool(gopay_config.credentials(env).webhook_secret)
            try:
                client = gopay_client.get_client(env)
            except gopay_client.GoPayError:
                answer["error"] = "Ключ и секрет для этой среды не заданы."
                return Response(answer)

            # Предохранитель не спрашиваем: проверку попросил человек. Исход
            # идёт в «здоровье» GoPay — после удачной проверки красная строка
            # о сбое в настройках гаснет.
            result = client.healthcheck()
            if result.get("ok"):
                gopay_service.note_result(env, None)
                answer.update(ok=True, apps=int(result.get("apps") or 0))
                return Response(answer)

            gopay_service.note_result(env, gopay_client.GoPayError(
                "", code=str(result.get("code") or "gopay_error"),
                kind=str(result.get("kind") or "other"),
                provider_code=str(result.get("provider_code") or ""),
                http_status=result.get("http_status")))
            answer["error"] = self._error_text(env, result)
            answer["provider_code"] = str(result.get("provider_code") or "") or None
        except Exception:  # noqa: BLE001 — кнопка проверки не должна давать 500
            answer.update(ok=False, apps=None,
                          error="Не удалось выполнить проверку. Повторите позже.")
        return Response(answer)


class SettingsTestOpenRouterView(StaffAPIView):
    """Проверка ключа OpenRouter: {key?} -> {ok, balance_usd, error}.

    Без key проверяется ТЕКУЩИЙ действующий ключ (runtime -> env).
    """

    def post(self, request):
        key = str((request.data or {}).get("key") or "").strip()
        if not key:
            key = _effective_openrouter_key()
        if not key:
            return Response({
                "ok": False, "balance_usd": None,
                "error": "Ключ OpenRouter не задан.",
            })
        try:
            resp = http_requests.get(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {key}"},
                timeout=8,
            )
            if resp.status_code != 200:
                return Response({
                    "ok": False, "balance_usd": None,
                    "error": f"OpenRouter ответил HTTP {resp.status_code}",
                })
            data = (resp.json() or {}).get("data") or {}
            balance = round(
                float(data.get("total_credits", 0)) - float(data.get("total_usage", 0)), 2
            )
            return Response({"ok": True, "balance_usd": balance, "error": None})
        except Exception as exc:
            return Response({"ok": False, "balance_usd": None, "error": str(exc)})


# ------------------------------------------------------------ promo-codes ---

class PromoCodesListView(StaffAPIView):
    """GET список промокодов, POST создать новый."""

    def get(self, request):
        qs = PromoCode.objects.all().order_by("-created_at", "-id")
        return Response(PromoCodeAdminSerializer(qs, many=True).data)

    def post(self, request):
        ser = PromoCodeAdminSerializer(data=request.data)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        promo = ser.save()
        return Response(
            PromoCodeAdminSerializer(promo).data, status=status.HTTP_201_CREATED
        )


class PromoCodeDetailView(StaffAPIView):
    """PATCH обновить подмножество полей, DELETE удалить."""

    def patch(self, request, pk):
        promo = get_object_or_404(PromoCode, pk=pk)
        ser = PromoCodeAdminSerializer(promo, data=request.data, partial=True)
        if not ser.is_valid():
            return Response({"detail": ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        promo = ser.save()
        return Response(PromoCodeAdminSerializer(promo).data)

    def delete(self, request, pk):
        promo = get_object_or_404(PromoCode, pk=pk)
        promo.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ login ---

class AdminLoginAPIView(APIView):
    """Вход в /admin-new по email+паролю. Только для staff-аккаунтов.

    Отдаёт стандартную JWT-пару (та же, что у обычного входа) — фронт кладёт её
    в cookies и работает как обычный авторизованный пользователь-администратор.
    Троттлинг анонимный — защита от перебора пароля.
    """
    authentication_classes = []  # логин — без токена
    permission_classes = []

    def post(self, request):
        from rest_framework.throttling import AnonRateThrottle
        from rest_framework_simplejwt.tokens import RefreshToken

        email = str(request.data.get("email") or "").strip().lower()
        password = str(request.data.get("password") or "")
        if not email or not password:
            return Response({"detail": "Укажите email и пароль."}, status=400)

        User = get_user_model()
        user = User.objects.filter(email__iexact=email).first()
        # Единый ответ для «нет юзера» / «не тот пароль» / «не админ» —
        # не раскрываем, какой именно фактор не совпал.
        if not user or not user.check_password(password) or not user.is_staff or not user.is_active:
            return Response({"detail": "Неверный email или пароль."}, status=403)

        refresh = RefreshToken.for_user(user)
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "email": user.email,
        })

    def get_throttles(self):
        from rest_framework.throttling import AnonRateThrottle

        class LoginThrottle(AnonRateThrottle):
            rate = "10/min"

        return [LoginThrottle()]


class FunnelView(StaffAPIView):
    """GET /api/manage/funnel/?days=30 — где теряются несостоявшиеся платежи."""

    def get(self, request):
        from payments.funnel import funnel_report

        try:
            days = max(1, min(365, int(request.query_params.get("days") or 30)))
        except (TypeError, ValueError):
            days = 30
        return Response(funnel_report(days))
