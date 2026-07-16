# users/serializers.py
from .models import User, Notification, NotificationDelivery, UserQuestions, UserFeedback, UserCardBind
from django.db.models import F

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken

ALLOWED_CURRENCIES = ("USD", "RUB", "KGS")


class SignUpSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    tel = serializers.CharField(max_length=20)
    password = serializers.CharField(write_only=True)
    password_repeat = serializers.CharField(write_only=True)
    ip = serializers.CharField(write_only=True)
    referral_uid = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Имя не может быть пустым.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError(
                "Пользователь с таким email уже существует.")
        return value

    def validate_tel(self, value):
        if User.objects.filter(tel=value).exists():
            raise serializers.ValidationError(
                "Пользователь с таким номером телефона уже существует.")
        return value

    def validate_ip(self, value):
        if not value:
            raise serializers.ValidationError("IP адрес обязателен.")
        return value

    def validate(self, data):
        if data['password'] != data['password_repeat']:
            raise serializers.ValidationError("Пароли не совпадают.")
        if len(data['password']) < 8:
            raise serializers.ValidationError(
                "Пароль должен быть не менее 8 символов.")
        if not any(char.isdigit() for char in data['password']):
            raise serializers.ValidationError(
                "Пароль должен содержать хотя бы одну цифру.")
        if not any(char.isalpha() for char in data['password']):
            raise serializers.ValidationError(
                "Пароль должен содержать хотя бы одну букву.")
        return data

    def create(self, validated_data):
        referral_uid = validated_data.get("referral_uid") or ""
        user = User.objects.create_user(
            email=validated_data["email"],
            tel=validated_data["tel"],
            password=validated_data["password"],
            first_name=validated_data["name"],
            ip=validated_data.get("ip")
        )
        # Реферальный бонус теперь начисляется КРЕДИТАМИ через
        # services.maybe_grant_referral_bonus (по cookie esai_ref) на активных
        # путях входа (email-OTP / соц). Старое начисление Vokalo-счётчиков снято.
        return user


class SignInSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)
    tel = serializers.CharField(required=False)
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        email = data.get("email")
        tel = data.get("tel")
        password = data.get("password")

        user = None
        if email:
            user = authenticate(email=email, password=password)
        elif tel:
            user = authenticate(tel=tel, password=password)

        if not user:
            raise serializers.ValidationError("Неверные учетные данные")

        refresh = RefreshToken.for_user(user)

        return {
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "email": user.email,
                "tel": user.tel,
            }
        }


class UserCardBindSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserCardBind
        fields = [
            "card_id",
            "card_hash",
            "card_month",
            "card_year",
            "card_bank",
            "card_country",
        ]


class ProfileSerializer(serializers.ModelSerializer):
    card = serializers.SerializerMethodField()

    class Meta:
        model = User
        # Явный whitelist безопасных полей. НЕ отдаём приватные/привилегированные:
        # password, is_staff, is_superuser, user_permissions, groups, last_login.
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "patronymic",
            "tel",
            "telegram",
            "country",
            "city",
            "is_active",
            "is_confirmed",
            "free_plan_activated",
            "date_joined",
            "last_session",
            "date_of_birth",
            "selected_currency",
            "auto_renew",
            "_2fa",
            "referral_uid",
            "bonus_texts",
            "bonus_images",
            "bonus_songs",
            "bonus_music",
            "token_balance",
            "is_paid",
            "first_paid_at",
            "is_unlimited",
            "memory_enabled",
            "avatar_url",
            "card",
        ]

    def get_card(self, user):
        obj = user.card_binds.order_by("-created_at").first()
        return UserCardBindSerializer(obj).data if obj else None


class CurrencyPreferenceSerializer(serializers.Serializer):
    currency = serializers.CharField()

    def validate_currency(self, value):
        code = (value or "").strip().upper()
        if code not in ALLOWED_CURRENCIES:
            raise serializers.ValidationError("Unsupported currency")
        return code


class NotificationDeliverySerializer(serializers.ModelSerializer):
    # flatten notification fields
    id = serializers.IntegerField(source='notification.id', read_only=True)
    delivery_id = serializers.IntegerField(source='id', read_only=True)
    title = serializers.CharField(source='notification.title', read_only=True)
    body = serializers.CharField(source='notification.body', read_only=True)
    created_at = serializers.DateTimeField(source='notification.created_at', read_only=True)

    class Meta:
        model = NotificationDelivery
        fields = ["id", "delivery_id", "title", "body", "is_read", "created_at", "read_at"]
        
        
class UserQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserQuestions
        fields = ["email", "tel", "name", "question"]

    def validate_tel(self, v):
        if v and len(v) > 50:
            raise serializers.ValidationError("Phone is too long")
        return v


class UserFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserFeedback
        fields = ["id", "name", "email", "rating", "message", "source", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_rating(self, v):
        if v is None:
            return v
        if not (1 <= int(v) <= 5):
            raise serializers.ValidationError("Rating must be between 1 and 5")
        return int(v)

    def validate_message(self, v):
        if not (v or "").strip():
            raise serializers.ValidationError("Message is required")
        return v

    def create(self, validated_data):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            validated_data.setdefault("user", user)
            validated_data.setdefault("email", user.email or "")
            validated_data.setdefault("name", user.first_name or "")
        return UserFeedback.objects.create(**validated_data)
