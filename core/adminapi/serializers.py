"""Сериализаторы кастомной админ-панели (/api/manage/).

Приложение без моделей: работаем с моделями из ai/plans/payments/content/users.
Decimal-поля отдаём числами (coerce_to_string=False), чтобы фронту не парсить строки.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.validators import UniqueValidator

from ai.models import GPTModels
from content.models import BlogPost
from payments.models import Payment
from plans.models import PromoCode, TokenPackage, TokenTransaction

User = get_user_model()


class PromoCodeAdminSerializer(serializers.ModelSerializer):
    """CRUD промокодов в панели.

    code нормализуется в UPPER; уникальность отдаём как 400 (UniqueValidator),
    а не как IntegrityError/500. bonus_credits > 0.
    """
    code = serializers.CharField(
        max_length=40,
        validators=[UniqueValidator(
            # коды хранятся в UPPER — уникальность проверяем регистронезависимо,
            # чтобы "abc" не прошёл при существующем "ABC"
            queryset=PromoCode.objects.all(),
            lookup="iexact",
            message="Промокод с таким кодом уже существует.",
        )],
    )
    bonus_credits = serializers.IntegerField(min_value=1)

    class Meta:
        model = PromoCode
        fields = [
            "id", "code", "bonus_credits", "expires_at", "max_activations",
            "used_count", "per_user_once", "new_users_only", "is_active",
            "created_at", "note",
        ]
        read_only_fields = ["id", "used_count", "created_at"]

    def validate_code(self, value):
        value = (value or "").strip().upper()
        if not value:
            raise serializers.ValidationError("Код не может быть пустым.")
        # Промокоды и коды креаторов (EsAI Creators) делят одно пространство
        # имён: иначе один и тот же код и начислял бы кредиты, и привязывал к
        # креатору. Сбой программы создание промокода не блокирует.
        try:
            from creators.codes import creator_code_exists

            taken = bool(creator_code_exists(value))
        except Exception:
            taken = False
        if taken:
            raise serializers.ValidationError("Этот код занят промокодом креатора.")
        return value


class _OptionalDecimal(serializers.DecimalField):
    """Число из формы панели: строка с запятой тоже число, пустая строка — null."""

    def run_validation(self, data=empty):
        if isinstance(data, str):
            data = data.strip().replace(",", ".")
            if not data:
                data = None
        return super().run_validation(data)


def _decimal_errors(label: str, hint: str, places: int) -> dict:
    # Границы проверяют валидаторы Django: их текст ещё раз проходит через «%»-подстановку.
    bound = f"{label}: {hint}".replace("%", "%%")
    return {
        "invalid": f"{label}: {hint}",
        "min_value": bound,
        "max_value": bound,
        "max_digits": f"{label}: {hint}",
        "max_whole_digits": f"{label}: {hint}",
        "max_decimal_places": f"{label}: не больше {places} знаков после запятой",
        "max_string_length": f"{label}: {hint}",
    }


class GPTModelAdminSerializer(serializers.ModelSerializer):
    markup_coefficient = serializers.DecimalField(
        max_digits=6, decimal_places=3, coerce_to_string=False, required=False)
    # Цена по себестоимости (ai/pricing.py, режим «наценка»). Пусто — общая наценка.
    markup_pct = _OptionalDecimal(
        max_digits=6, decimal_places=2, min_value=Decimal("0"), max_value=Decimal("1000"),
        allow_null=True, required=False, coerce_to_string=False,
        error_messages=_decimal_errors("Наценка", "от 0 до 1000 %; пусто — общая наценка", 2))
    unit_cost_usd = _OptionalDecimal(
        max_digits=10, decimal_places=6, min_value=Decimal("0"), max_value=Decimal("1000"),
        allow_null=True, required=False, coerce_to_string=False,
        error_messages=_decimal_errors(
            "Себестоимость картинки", "сумма в долларах от 0 до 1000, например 0.039; пусто — не задана", 6))
    ref_cost_usd = _OptionalDecimal(
        max_digits=10, decimal_places=6, min_value=Decimal("0"), max_value=Decimal("1000"),
        allow_null=True, required=False, coerce_to_string=False,
        error_messages=_decimal_errors(
            "Себестоимость входного фото", "сумма в долларах от 0 до 1000, например 0.06; пусто — бесплатно", 6))
    # Только чтение: себестоимость и цена типичной генерации в обоих режимах (adminapi.prices).
    pricing = serializers.SerializerMethodField()
    cost_sample = serializers.SerializerMethodField()
    price_sample = serializers.SerializerMethodField()
    price_sample_other = serializers.SerializerMethodField()
    vstudio_supported = serializers.SerializerMethodField()

    class Meta:
        model = GPTModels
        fields = [
            "id", "name", "openrouter_id", "description", "markup_coefficient",
            "category", "recommended", "free_tier", "supports_vision",
            "is_active", "sort_order", "cartoon_stage",
            # Видеостудия: показывать модель и правки поверх реестра caps.
            "vstudio_enabled", "vstudio_overrides",
            "markup_pct", "unit_cost_usd", "ref_cost_usd",
            "pricing", "cost_sample", "price_sample", "price_sample_other", "vstudio_supported",
        ]
        # openrouter_id — системный идентификатор, из панели не меняется
        read_only_fields = ["id", "openrouter_id"]

    def _prices(self, obj) -> dict:
        from .prices import model_info

        return model_info(obj, self.context) or {}

    def get_pricing(self, obj):
        return self._prices(obj).get("pricing")

    def get_cost_sample(self, obj):
        return self._prices(obj).get("cost_sample")

    def get_price_sample(self, obj):
        return self._prices(obj).get("price_sample")

    def get_price_sample_other(self, obj):
        return self._prices(obj).get("price_sample_other")

    def get_vstudio_supported(self, obj) -> bool:
        from .prices import vstudio_supported

        return vstudio_supported(obj)

    def validate(self, attrs):
        # Себестоимость за штуку есть только у картинок: у видео она из каталога
        # OpenRouter, у текста — тариф за токены.
        category = attrs.get("category", getattr(self.instance, "category", ""))
        if category != "image":
            for field in ("unit_cost_usd", "ref_cost_usd"):
                if attrs.get(field) is not None:
                    raise serializers.ValidationError({field: [
                        "Себестоимость за картинку задаётся только у моделей картинок (категория «Изображения»)"]})
        return attrs

    def validate_vstudio_overrides(self, value):
        """Те же проверки, что в Django-админке: белый список ключей и лимиты вендора."""
        from django.core.exceptions import ValidationError as DjangoValidationError

        from ai.models import validate_vstudio_overrides

        model_ref = (getattr(self.instance, "openrouter_id", "") or
                     str((getattr(self, "initial_data", None) or {}).get("openrouter_id") or ""))
        try:
            return validate_vstudio_overrides(value, model_ref)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None


class TokenPackageAdminSerializer(serializers.ModelSerializer):
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=False, required=False)

    class Meta:
        model = TokenPackage
        fields = [
            "id", "name", "tokens", "bonus_tokens", "price", "badge",
            "featured", "is_active", "sort_order", "description",
            # Переводы витрины: без них на английской и кыргызской странице
            # среди переведённого интерфейса остаётся русский текст пакета.
            "name_en", "name_kg", "badge_en", "badge_kg",
            "description_en", "description_kg",
            # Оплата в боте: цена в Stars и бонус; подсказка считается по курсу.
            "stars_price", "stars_bonus_tokens", "stars_suggested",
        ]
        read_only_fields = ["id", "stars_suggested"]

    stars_suggested = serializers.SerializerMethodField()

    def get_stars_suggested(self, obj):
        try:
            from plans.stars import suggest_stars_price

            return suggest_stars_price(obj)
        except Exception:  # noqa: BLE001
            return None


class UserAdminSerializer(serializers.ModelSerializer):
    # username в модели nullable — контракт требует пустую строку вместо null
    username = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "username", "first_name", "last_name", "telegram",
            "token_balance", "is_paid", "is_staff", "date_joined", "last_login",
        ]

    def get_username(self, obj):
        return obj.username or ""


class TokenTransactionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenTransaction
        fields = ["id", "delta", "reason", "balance_after", "created_at", "meta"]


class PaymentShortSerializer(serializers.ModelSerializer):
    """Краткий платёж для summary.recent_payments."""
    user_email = serializers.SerializerMethodField()
    amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=False)

    class Meta:
        model = Payment
        fields = ["id", "created_at", "user_email", "amount", "currency",
                  "success", "order_id"]

    def get_user_email(self, obj):
        return obj.user.email if obj.user else ""


class PaymentAdminSerializer(PaymentShortSerializer):
    """Полный платёж для списка /payments/.

    У крипты «неуспешно» и «ещё не оплачено» — разные вещи: счёт живёт до часа,
    и всё это время платёж не успешен, но и не провален. Поэтому рядом с
    success идёт pending и подробности счёта. То же у единого QR (GoPay): счёт
    живёт минуты, и пока его срок не вышел, платёж ждёт оплату, а не провален.
    """

    provider = serializers.CharField(read_only=True)
    method = serializers.SerializerMethodField()
    pending = serializers.SerializerMethodField()
    crypto = serializers.SerializerMethodField()
    stars = serializers.SerializerMethodField()
    qr = serializers.SerializerMethodField()

    class Meta(PaymentShortSerializer.Meta):
        fields = PaymentShortSerializer.Meta.fields + [
            "description", "error", "provider", "method", "pending", "crypto", "stars",
            "is_test", "qr"]

    def get_method(self, obj) -> str:
        """Способ оплаты в сомах, выбранный до ухода на FreedomPay (пусто — не выбирали).

        У крипты и Stars в том же поле запроса лежит «crypto»/«stars» — это уже
        видно по provider, поэтому отдаём только способы сомовой оплаты.
        """
        from payments import kgs_methods

        request = obj.request if isinstance(obj.request, dict) else {}
        value = str(request.get("pay_method") or "")
        return value if value in kgs_methods.METHODS else ""

    def get_stars(self, obj):
        invoice = getattr(obj, "star_invoice", None)
        if invoice is None:
            return None
        return {
            "status": invoice.status,
            "telegram_id": invoice.telegram_id,
            "stars": invoice.stars_amount,
            "tokens": invoice.total_tokens,
            "charge_id": invoice.telegram_payment_charge_id or "",
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
            "refunded_at": invoice.refunded_at.isoformat() if invoice.refunded_at else None,
            "refund_reason": invoice.refund_reason,
        }

    def get_pending(self, obj) -> bool:
        if obj.success:
            return False
        invoice = getattr(obj, "crypto_invoice", None)
        if invoice is not None and invoice.is_open:
            return True
        # Единый QR ждёт оплату, только пока он живой: открыт у GoPay, наш срок
        # не вышел и покупатель его не оставил. Оставленный счёт ещё может быть
        # оплачен, но «ждём оплату» про него уже неправда.
        qr = getattr(obj, "gopay_invoice", None)
        return bool(qr is not None and qr.is_open and qr.cancel_requested_at is None
                    and qr.expires_at is not None and qr.expires_at > timezone.now())

    def get_qr(self, obj):
        """Счёт единого QR (GoPay) или None. Ссылок на оплату и самого QR тут нет."""
        invoice = getattr(obj, "gopay_invoice", None)
        if invoice is None:
            return None
        flags = invoice.flags if isinstance(invoice.flags, dict) else {}

        def iso(value):
            return value.isoformat() if value else None

        return {
            "status": invoice.status,
            "env": invoice.env,
            "provider_payment_id": invoice.provider_payment_id,
            "expires_at": iso(invoice.expires_at),
            "committed_at": iso(invoice.committed_at),
            "bank_op_date": iso(invoice.bank_op_date),
            "receipt_url": invoice.receipt_url or "",
            # Покупатель ушёл с этого QR, а GoPay его (ещё) не отменил.
            "abandoned": bool(flags.get("abandoned")),
            "flags": flags,
        }

    def get_crypto(self, obj):
        invoice = getattr(obj, "crypto_invoice", None)
        if invoice is None:
            return None
        return {
            "status": invoice.status,
            "coin": invoice.pay_coin,
            "network": invoice.pay_network,
            "pay_amount": str(invoice.pay_amount.normalize()),
            "actually_paid": str(invoice.actually_paid.normalize()),
            "credited_tokens": int(invoice.credited_tokens or 0),
            "tx_hash": invoice.tx_hash or "",
            "expires_at": invoice.expires_at.isoformat() if invoice.expires_at else None,
            "flags": invoice.flags or {},
        }


class BlogPostListSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlogPost
        fields = ["id", "slug", "title_ru", "is_published", "published_at",
                  "created_at"]


class BlogPostFullSerializer(serializers.ModelSerializer):
    # en/kg-версии необязательны: при пустых значениях view подставит ru-версию.
    # slug тоже опционален — модель сгенерирует его из заголовка сама.
    slug = serializers.SlugField(
        max_length=255, required=False, allow_blank=True,
        # ручное переопределение поля убирает авто-UniqueValidator — возвращаем,
        # иначе дубль slug уронит запрос в IntegrityError (500 вместо 400)
        validators=[UniqueValidator(queryset=BlogPost.objects.all())])
    title_en = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    title_kg = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    content_en = serializers.CharField(required=False, allow_blank=True, default="")
    content_kg = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = BlogPost
        fields = [
            "id", "slug", "title_ru", "title_en", "title_kg",
            "content_ru", "content_en", "content_kg",
            "excerpt", "meta_title", "meta_description", "author",
            "is_published", "published_at",
        ]
        # published_at выставляется правилом публикации (model.save), не руками
        read_only_fields = ["id", "published_at"]
