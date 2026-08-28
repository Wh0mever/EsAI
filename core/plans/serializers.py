from decimal import Decimal, ROUND_HALF_UP
from rest_framework import serializers
from .models import (
    Plan, UserSubscription, GenerationUsage, AddonPurchase,
    TokenPackage, TokenTransaction,
)
from .services import get_currency_per_usd_map
from core.langutils import tr

# price quantize helper
Q2 = Decimal("0.01")

def q2(v: Decimal | None) -> Decimal | None:
    if v is None:
        return None
    return Decimal(v).quantize(Q2, rounding=ROUND_HALF_UP)

class PlanSerializer(serializers.ModelSerializer):
    has_discount = serializers.SerializerMethodField()
    discount_percent = serializers.SerializerMethodField()
    llm_engine_name = serializers.SerializerMethodField()

    # new: prices in RUB/KGS
    price_amount_rub = serializers.SerializerMethodField()
    price_amount_kgs = serializers.SerializerMethodField()
    price_base_amount_rub = serializers.SerializerMethodField()
    price_base_amount_kgs = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = (
            "id", "period", "is_free", "is_active", "sort_order",
            "price_amount", "price_base_amount",
            "has_discount", "discount_percent",
            "llm_engine_id", "llm_engine_name",
            "song_limit", "music_limit", "text_limit", "image_limit",
            "sunday_bonus_songs", "sunday_bonus_music", "sunday_bonus_texts", "sunday_bonus_images",
            "ai_chat_enabled", "realtime_chat_enabled",
            "images_enabled", "music_enabled", "mp4_enabled", "support_enabled",
            "can_purchase_addons",
            "price_amount_rub", "price_amount_kgs",
            "price_base_amount_rub", "price_base_amount_kgs",
            "template_name_ru", "template_name_en", "template_name_kg",
        )

    # ---- discount ----
    def get_has_discount(self, obj: Plan) -> bool:
        return bool(obj.price_base_amount and obj.price_base_amount > obj.price_amount)

    def get_discount_percent(self, obj: Plan) -> int:
        if obj.price_base_amount and obj.price_base_amount > 0:
            try:
                return int(round((1 - (obj.price_amount / obj.price_base_amount)) * 100))
            except Exception:
                return 0
        return 0

    def get_llm_engine_name(self, obj: Plan) -> str | None:
        engine = getattr(obj, "llm_engine", None)
        return getattr(engine, "name", None) if engine else None

    # ---- currency conversion helpers ----
    def _per_usd(self) -> dict:
        # cached on serializer instance; expect context['currency_per_usd'] from view
        cache = getattr(self, "_currency_per_usd_cache", None)
        if cache is not None:
            return cache
        ctx_map = self.context.get("currency_per_usd")
        if isinstance(ctx_map, dict) and ctx_map:
            self._currency_per_usd_cache = ctx_map
            return ctx_map
        # fallback to DB (one-time read if context not provided)
        m = get_currency_per_usd_map(["RUB", "KGS"])
        self._currency_per_usd_cache = m
        return m

    def _usd_to(self, amount_usd: Decimal | None, code: str) -> Decimal | None:
        if amount_usd is None:
            return None
        per_map = self._per_usd()
        rate = per_map.get(code)  # how many <code> in 1 USD
        if not rate:
            return None
        return q2(Decimal(amount_usd) * rate)

    # ---- exposed fields ----
    def get_price_amount_rub(self, obj: Plan):
        return self._usd_to(obj.price_amount, "RUB")

    def get_price_amount_kgs(self, obj: Plan):
        return self._usd_to(obj.price_amount, "KGS")

    def get_price_base_amount_rub(self, obj: Plan):
        return self._usd_to(obj.price_base_amount, "RUB")

    def get_price_base_amount_kgs(self, obj: Plan):
        return self._usd_to(obj.price_base_amount, "KGS")


class GenerationUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationUsage
        fields = ("songs_left", "music_left", "texts_left", "images_left", "sunday_bonus_used")


class UserSubscriptionSerializer(serializers.ModelSerializer):
    plan = PlanSerializer(read_only=True)
    usage = GenerationUsageSerializer(read_only=True)

    # Computed remaining counters (plan usage + user bonus if plan limited)
    remaining_texts = serializers.SerializerMethodField()
    remaining_images = serializers.SerializerMethodField()
    remaining_songs = serializers.SerializerMethodField()
    remaining_music = serializers.SerializerMethodField()

    # Unlimited flags for convenience on client
    is_texts_unlimited = serializers.SerializerMethodField()
    is_images_unlimited = serializers.SerializerMethodField()
    is_songs_unlimited = serializers.SerializerMethodField()
    is_music_unlimited = serializers.SerializerMethodField()

    class Meta:
        model = UserSubscription
        fields = (
            "id", "plan", "status", "payment_status",
            "start_date", "end_date", "payment_date", "usage", "auto_renew", "grace_until", "billing_issue_code",
            # computed remaining
            "remaining_texts", "remaining_images", "remaining_songs", "remaining_music",
            # unlimited flags
            "is_texts_unlimited", "is_images_unlimited", "is_songs_unlimited", "is_music_unlimited",
        )

    def _is_unlimited(self, limit_value) -> bool:
        return limit_value is None

    def _remaining(self, limit_value, left: int | None, bonus: int | None) -> int | None:
        # If unlimited plan for this resource, return None to indicate infinity
        if self._is_unlimited(limit_value):
            return None
        return int((left or 0) + (bonus or 0))

    def get_is_texts_unlimited(self, obj: UserSubscription) -> bool:
        return self._is_unlimited(getattr(obj.plan, "text_limit", 0))

    def get_is_images_unlimited(self, obj: UserSubscription) -> bool:
        return self._is_unlimited(getattr(obj.plan, "image_limit", 0))

    def get_is_songs_unlimited(self, obj: UserSubscription) -> bool:
        return self._is_unlimited(getattr(obj.plan, "song_limit", 0))

    def get_is_music_unlimited(self, obj: UserSubscription) -> bool:
        return self._is_unlimited(getattr(obj.plan, "music_limit", 0))

    def get_remaining_texts(self, obj: UserSubscription) -> int | None:
        user = getattr(obj, "user", None)
        usage = getattr(obj, "usage", None)
        return self._remaining(getattr(obj.plan, "text_limit", 0), getattr(usage, "texts_left", 0), getattr(user, "bonus_texts", 0))

    def get_remaining_images(self, obj: UserSubscription) -> int | None:
        user = getattr(obj, "user", None)
        usage = getattr(obj, "usage", None)
        return self._remaining(getattr(obj.plan, "image_limit", 0), getattr(usage, "images_left", 0), getattr(user, "bonus_images", 0))

    def get_remaining_songs(self, obj: UserSubscription) -> int | None:
        user = getattr(obj, "user", None)
        usage = getattr(obj, "usage", None)
        return self._remaining(getattr(obj.plan, "song_limit", 0), getattr(usage, "songs_left", 0), getattr(user, "bonus_songs", 0))

    def get_remaining_music(self, obj: UserSubscription) -> int | None:
        user = getattr(obj, "user", None)
        usage = getattr(obj, "usage", None)
        return self._remaining(getattr(obj.plan, "music_limit", 0), getattr(usage, "music_left", 0), getattr(user, "bonus_music", 0))


class AddonPurchaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = AddonPurchase
        fields = (
            "id", "purchase_date", "music_added", "texts_added", "images_added",
        )


class TokenPackageSerializer(serializers.ModelSerializer):
    """Витрина пакетов. Имя, подпись и бейдж приходят уже на нужном языке.

    Поля остаются теми же (name/description/badge), а не превращаются в
    name_en и подобные: фронту незачем знать про переводы, он показывает то,
    что дали. Язык кладётся во view через context["lang"].
    """
    name = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()

    class Meta:
        model = TokenPackage
        fields = (
            "id", "name", "tokens", "bonus_tokens", "price", "currency",
            "description", "badge", "featured", "sort_order",
        )

    def _lang(self) -> str:
        return self.context.get("lang") or "ru"

    def get_name(self, obj) -> str:
        return tr(obj, "name", self._lang())

    def get_description(self, obj) -> str:
        return tr(obj, "description", self._lang())

    def get_badge(self, obj) -> str:
        return tr(obj, "badge", self._lang())


class TokenTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TokenTransaction
        fields = ("id", "delta", "reason", "balance_after", "created_at", "meta")
