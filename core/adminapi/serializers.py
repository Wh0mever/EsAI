"""Сериализаторы кастомной админ-панели (/api/manage/).

Приложение без моделей: работаем с моделями из ai/plans/payments/content/users.
Decimal-поля отдаём числами (coerce_to_string=False), чтобы фронту не парсить строки.
"""
from django.contrib.auth import get_user_model
from rest_framework import serializers
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
        return value


class GPTModelAdminSerializer(serializers.ModelSerializer):
    markup_coefficient = serializers.DecimalField(
        max_digits=6, decimal_places=3, coerce_to_string=False, required=False)

    class Meta:
        model = GPTModels
        fields = [
            "id", "name", "openrouter_id", "description", "markup_coefficient",
            "category", "recommended", "free_tier", "supports_vision",
            "is_active", "sort_order", "cartoon_stage",
        ]
        # openrouter_id — системный идентификатор, из панели не меняется
        read_only_fields = ["id", "openrouter_id"]


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
        ]
        read_only_fields = ["id"]


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
    """Полный платёж для списка /payments/."""

    class Meta(PaymentShortSerializer.Meta):
        fields = PaymentShortSerializer.Meta.fields + ["description", "error"]


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
