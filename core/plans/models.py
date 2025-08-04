from django.db import models
from users.models import User

# Create your models here.

class TariffPlan(models.Model):
    PLAN_CHOICES = [
        ('free', 'Free'),
        ('basic', 'Basic'),
        ('standard', 'Standard'),
        ('pro', 'Pro'),
        ('premium', 'Premium'),
        ('enterprise', 'Enterprise'),
    ]

    code = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField(default=30)

    song_limit = models.PositiveIntegerField()
    music_limit = models.PositiveIntegerField()
    text_limit = models.PositiveIntegerField()
    image_limit = models.PositiveIntegerField()

    sunday_bonus_songs = models.PositiveIntegerField(default=0)
    sunday_bonus_music = models.PositiveIntegerField(default=0)
    sunday_bonus_texts = models.PositiveIntegerField(default=0)
    sunday_bonus_images = models.PositiveIntegerField(default=0)

    can_purchase_addons = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class UserSubscription(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('inactive', 'Inactive')]
    PAYMENT_STATUS = [('paid', 'Paid'), ('unpaid', 'Unpaid')]
    PAYMENT_METHODS = [
        ('credit_card', 'Credit Card'),
        ('paypal', 'PayPal'),
        ('bank_transfer', 'Bank Transfer'),
        ('freedompay', 'FreedomPay'),
        ('yoomoney', 'ЮMoney'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    plan = models.ForeignKey(TariffPlan, on_delete=models.PROTECT)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHODS, null=True, blank=True)
    payment_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} — {self.plan.name}"


class GenerationUsage(models.Model):
    subscription = models.OneToOneField(UserSubscription, on_delete=models.CASCADE, related_name='usage')

    songs_left = models.IntegerField(default=0)
    music_left = models.IntegerField(default=0)
    texts_left = models.IntegerField(default=0)
    images_left = models.IntegerField(default=0)

    sunday_bonus_used = models.BooleanField(default=False)

    def __str__(self):
        return f"Usage for {self.subscription}"


class AddonPurchase(models.Model):
    ADDON_CHOICES = [
        ('song_boost', '20 Songs'),
        ('music_pack', '20 Music'),
        ('text_expand', '50 Texts'),
        ('image_pack', '30 Images'),
        ('all_in_one', 'Mixed Pack'),
        ('max_boost', 'Max Boost'),
    ]

    subscription = models.ForeignKey(UserSubscription, on_delete=models.CASCADE, related_name='addons')
    addon_type = models.CharField(max_length=50, choices=ADDON_CHOICES)
    purchase_date = models.DateTimeField(auto_now_add=True)

    songs_added = models.PositiveIntegerField(default=0)
    music_added = models.PositiveIntegerField(default=0)
    texts_added = models.PositiveIntegerField(default=0)
    images_added = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.subscription.user.username} — {self.get_addon_type_display()}"
