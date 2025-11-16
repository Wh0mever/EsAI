from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class Currency(models.TextChoices):
    RUB = "RUB", "Russian Ruble"
    KGS = "KGS", "Kyrgyz Som"


class BillingPeriod(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    YEARLY  = "yearly", "Yearly"
    

class CurrencyRate(models.Model):
    # rate_to_usd: сколько 1 единица выбранной валюты стоит в USD
    currency = models.CharField(max_length=3, choices=Currency.choices, unique=True)
    rate_to_usd = models.DecimalField(max_digits=18, decimal_places=8)
    fetched_at = models.DateTimeField(auto_now=True)
    source = models.URLField(blank=True, default="")

    class Meta:
        db_table = "currency_rate"

    def __str__(self):
        return f"{self.currency}={self.rate_to_usd} USD"


class Plan(models.Model):
    # Meta
    is_active = models.BooleanField(default=True)
    is_free = models.BooleanField(default=False)
    period = models.CharField(max_length=10, choices=BillingPeriod.choices)
    duration_days = models.PositiveIntegerField(default=30)
    sort_order = models.PositiveIntegerField(default=100)

    price_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    price_base_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # Engine mapping (frontend resolves to a label)
    llm_engine = models.ForeignKey(
        'ai.GPTModels', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    
    # Template Names
    template_name_ru = models.CharField(max_length=100, null=True, blank=True)
    template_name_en = models.CharField(max_length=100, null=True, blank=True)
    template_name_kg = models.CharField(max_length=100, null=True, blank=True)

    # Limits (0 => unlimited)
    ai_templates_limit = models.PositiveIntegerField(null=True, blank=True)
    operations_per_month_limit = models.PositiveIntegerField(null=True, blank=True)
    covers_limit = models.PositiveIntegerField(null=True, blank=True)

    # Chat response tokens limit (per reply). If null -> fallback to model default.
    chat_output_tokens_limit = models.PositiveIntegerField(null=True, blank=True)

    # Legacy-style content limits to keep your current counters
    song_limit = models.PositiveIntegerField(default=0)   # 0 => unlimited
    music_limit = models.PositiveIntegerField(default=0)  # 0 => unlimited
    text_limit = models.PositiveIntegerField(default=0)   # 0 => unlimited
    image_limit = models.PositiveIntegerField(default=0)  # 0 => unlimited

    # Sunday bonuses (legacy behavior)
    sunday_bonus_songs = models.PositiveIntegerField(default=0)
    sunday_bonus_music = models.PositiveIntegerField(default=0)
    sunday_bonus_texts = models.PositiveIntegerField(default=0)
    sunday_bonus_images = models.PositiveIntegerField(default=0)

    # Feature toggles
    ai_chat_enabled = models.BooleanField(default=False)
    realtime_chat_enabled = models.BooleanField(default=False)
    rewriter_enabled = models.BooleanField(default=False)
    antiplag_enabled = models.BooleanField(default=False)
    images_enabled = models.BooleanField(default=False)
    diffusion_images_enabled = models.BooleanField(default=False)
    blog_master_enabled = models.BooleanField(default=False)
    music_enabled = models.BooleanField(default=False)
    tts_enabled = models.BooleanField(default=False)
    my_templates_enabled = models.BooleanField(default=False)
    manager_enabled = models.BooleanField(default=False)
    support_enabled = models.BooleanField(default=False)

    # Purchases
    can_purchase_addons = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        tag = "FREE" if self.is_free else self.period.upper()
        return f"Plan #{self.id} [{tag}] {self.price_amount}"

    def clean(self):
        # Basic consistency
        if self.is_free:
            if self.price_amount != 0 or (self.price_base_amount and self.price_base_amount != 0):
                raise ValidationError("Free plan must have zero price and no base price.")
        if self.price_base_amount is not None and self.price_base_amount <= self.price_amount:
            raise ValidationError("Base price should be greater than current price.")


class SubscriptionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class PaymentStatus(models.TextChoices):
    PAID = "paid", "Paid"
    UNPAID = "unpaid", "Unpaid"


class UserSubscription(models.Model):
    # Use AUTH_USER_MODEL for flexibility
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")

    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=SubscriptionStatus.choices, default=SubscriptionStatus.ACTIVE)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    payment_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["start_date"]),
        ]

    def __str__(self):
        return f"{self.user} — Plan #{self.plan_id}"

    # Helpers
    def is_unlimited(self, value: int | None) -> bool:
        # Treat None/0 from plan limits as unlimited in usage logic
        return value is None or value == 0

    def apply_addon_to_usage(self, addon: "AddonPurchase") -> None:
        """Increment usage counters by addon amounts."""
        usage = getattr(self, "usage", None)
        if not usage:
            return
        usage.songs_left = (usage.songs_left or 0) + addon.songs_added
        usage.music_left = (usage.music_left or 0) + addon.music_added
        usage.texts_left = (usage.texts_left or 0) + addon.texts_added
        usage.images_left = (usage.images_left or 0) + addon.images_added
        usage.save(update_fields=["songs_left", "music_left", "texts_left", "images_left"])

    # ---- Limits helpers ----
    def _get_usage_locked(self) -> "GenerationUsage":
        from django.db import transaction
        from django.db.models import F
        # Ensure usage row exists and lock for update when mutating
        with transaction.atomic():
            usage, _ = GenerationUsage.objects.select_for_update().get_or_create(subscription=self)
        return usage

    def _has_available(self, kind: str) -> bool:
        """Quick availability check without locking (best-effort)."""
        plan = self.plan
        usage = getattr(self, "usage", None)
        if kind == "text":
            if self.is_unlimited(plan.text_limit):
                return True
            left = (getattr(usage, "texts_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_texts", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "image":
            if self.is_unlimited(plan.image_limit):
                return True
            left = (getattr(usage, "images_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_images", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "song":
            if self.is_unlimited(plan.song_limit):
                return True
            left = (getattr(usage, "songs_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_songs", 0) or 0)
            return (left > 0) or (bonus > 0)
        if kind == "music":
            if self.is_unlimited(plan.music_limit):
                return True
            left = (getattr(usage, "music_left", 0) or 0)
            bonus = (getattr(self.user, "bonus_music", 0) or 0)
            return (left > 0) or (bonus > 0)
        return False

    def can_consume(self, kind: str) -> bool:
        """Public best-effort check if user can perform generation of given kind."""
        return self._has_available(kind)

    def consume(self, kind: str) -> None:
        """
        Consume one unit for the given kind.
        Priority: plan usage -> user bonus. Raises ValidationError if none.
        """
        from django.db import transaction
        from django.core.exceptions import ValidationError
        from django.db.models import F

        plan = self.plan
        with transaction.atomic():
            usage = GenerationUsage.objects.select_for_update().get_or_create(subscription=self)[0]
            user = type(self.user).objects.select_for_update().get(pk=self.user_id)

            if kind == "text":
                if not self.is_unlimited(plan.text_limit):
                    if usage.texts_left and usage.texts_left > 0:
                        usage.texts_left -= 1
                        usage.save(update_fields=["texts_left"])
                        return
                    if user.bonus_texts and user.bonus_texts > 0:
                        user.bonus_texts -= 1
                        user.save(update_fields=["bonus_texts"])
                        return
                    raise ValidationError("Лимит текстов исчерпан")
                # unlimited
                return

            if kind == "image":
                if not self.is_unlimited(plan.image_limit):
                    if usage.images_left and usage.images_left > 0:
                        usage.images_left -= 1
                        usage.save(update_fields=["images_left"])
                        return
                    if user.bonus_images and user.bonus_images > 0:
                        user.bonus_images -= 1
                        user.save(update_fields=["bonus_images"])
                        return
                    raise ValidationError("Лимит изображений исчерпан")
                return

            if kind == "song":
                if not self.is_unlimited(plan.song_limit):
                    if usage.songs_left and usage.songs_left > 0:
                        usage.songs_left -= 1
                        usage.save(update_fields=["songs_left"])
                        return
                    if user.bonus_songs and user.bonus_songs > 0:
                        user.bonus_songs -= 1
                        user.save(update_fields=["bonus_songs"])
                        return
                    raise ValidationError("Лимит песен исчерпан")
                return

            if kind == "music":
                if not self.is_unlimited(plan.music_limit):
                    if usage.music_left and usage.music_left > 0:
                        usage.music_left -= 1
                        usage.save(update_fields=["music_left"])
                        return
                    if user.bonus_music and user.bonus_music > 0:
                        user.bonus_music -= 1
                        user.save(update_fields=["bonus_music"])
                        return
                    raise ValidationError("Лимит музыки исчерпан")
                return

            raise ValidationError("Неизвестный тип ресурса")


class GenerationUsage(models.Model):
    subscription = models.OneToOneField(UserSubscription, on_delete=models.CASCADE, related_name="usage")

    # 0 here means "no remaining limit required" only if the plan is unlimited.
    songs_left = models.IntegerField(default=0)
    music_left = models.IntegerField(default=0)
    texts_left = models.IntegerField(default=0)
    images_left = models.IntegerField(default=0)

    # Sunday bonus bookkeeping
    sunday_bonus_used = models.BooleanField(default=False)

    class Meta:
        indexes = [models.Index(fields=["subscription"])]

    def __str__(self):
        return f"Usage for {self.subscription_id}"

    # Safe decrement helpers
    def _dec(self, field: str, unlimited: bool) -> None:
        """Decrement counter if not unlimited; never go negative."""
        if unlimited:
            return
        value = getattr(self, field, 0)
        if value <= 0:
            raise ValidationError(f"{field} limit exceeded.")
        setattr(self, field, value - 1)

    def consume_song(self, unlimited: bool) -> None:
        self._dec("songs_left", unlimited)

    def consume_music(self, unlimited: bool) -> None:
        self._dec("music_left", unlimited)

    def consume_text(self, unlimited: bool) -> None:
        self._dec("texts_left", unlimited)

    def consume_image(self, unlimited: bool) -> None:
        self._dec("images_left", unlimited)


class AddonType(models.TextChoices):
    SONG_BOOST = "song_boost", "20 Songs"
    MUSIC_PACK = "music_pack", "20 Music"
    TEXT_EXPAND = "text_expand", "50 Texts"
    IMAGE_PACK = "image_pack", "30 Images"
    ALL_IN_ONE = "all_in_one", "Mixed Pack"
    MAX_BOOST = "max_boost", "Max Boost"


class AddonPurchase(models.Model):
    subscription = models.ForeignKey(UserSubscription, on_delete=models.CASCADE, related_name="addons")
    addon_type = models.CharField(max_length=50, choices=AddonType.choices)
    purchase_date = models.DateTimeField(auto_now_add=True)

    songs_added = models.PositiveIntegerField(default=0)
    music_added = models.PositiveIntegerField(default=0)
    texts_added = models.PositiveIntegerField(default=0)
    images_added = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["subscription", "purchase_date"])]

    def __str__(self):
        return f"{self.subscription.user} — {self.get_addon_type_display()}"
