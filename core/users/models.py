from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, Group, Permission
from django.db import models
from django.db.utils import IntegrityError
from django.utils import timezone
from django.conf import settings
import xml.etree.ElementTree as ET
import random
import string


def generate_referral_uid(length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choices(alphabet, k=length))


class UserCardBind(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="card_binds")
    card_id = models.CharField(max_length=64, verbose_name="Card ID")
    card_token = models.CharField(max_length=128, verbose_name="Card Token")
    card_hash = models.CharField(max_length=32, verbose_name="Card Hash")
    card_month = models.CharField(max_length=2, verbose_name="Card Expiry Month")
    card_year = models.CharField(max_length=2, verbose_name="Card Expiry Year")
    card_bank = models.CharField(max_length=64, verbose_name="Card Bank")
    card_country = models.CharField(max_length=2, verbose_name="Card Country")
    card_3ds = models.BooleanField(default=False, verbose_name="3DS Enabled")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    def __str__(self):
        return f"UserCardBind(user={self.user_id}, card_id={self.card_id})"

    class Meta:
        verbose_name = "Привязка карты пользователя"
        verbose_name_plural = "Привязки карт пользователей"
        ordering = ["-created_at"]
        constraints = [
            # Идемпотентность привязки карты: реплей подписанного постбэка не
            # плодит дубли (#20). Дополняет get_or_create в freedompay.save_*.
            models.UniqueConstraint(
                fields=["user", "card_token"], name="uniq_usercardbind_user_token"
            ),
        ]


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if not extra_fields.get("is_staff"):
            raise ValueError("Superuser должен иметь is_staff=True.")
        if not extra_fields.get("is_superuser"):
            raise ValueError("Superuser должен иметь is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):

    email = models.EmailField(unique=True, verbose_name='Почта')
    username = models.CharField(
        max_length=150,
        unique=True,
        blank=True,
        null=True,
        verbose_name="Username",
    )
    first_name = models.CharField(max_length=30, blank=True, verbose_name='Имя')
    last_name = models.CharField(max_length=30, blank=True, verbose_name='Фамилия')
    patronymic = models.CharField(max_length=30, blank=True, verbose_name='Отчество')
    tel = models.CharField(max_length=30, blank=True, verbose_name='Телефон')
    telegram = models.CharField(max_length=30, blank=True, verbose_name='Telegram')
    
    country = models.CharField(max_length=30, blank=True, verbose_name='Страна')
    city = models.CharField(max_length=30, blank=True, verbose_name='Город')
    
    is_active = models.BooleanField(default=True, verbose_name='Активен')
    is_staff = models.BooleanField(default=False, verbose_name='Сотрудник')
    is_superuser = models.BooleanField(default=False, verbose_name='Суперпользователь')
    is_confirmed = models.BooleanField(default=False, verbose_name='Подтвержден')
    free_plan_activated = models.BooleanField(default=False, verbose_name='Бесплатный тариф активирован')
    
    date_joined = models.DateTimeField(default=timezone.now, verbose_name='Дата регистрации')
    last_login = models.DateTimeField(null=True, blank=True, verbose_name='Последний вход')
    last_session = models.DateTimeField(null=True, blank=True, verbose_name='Последняя сессия')
    date_of_birth = models.DateField(null=True, blank=True, verbose_name='Дата рождения')
    
    selected_currency = models.CharField(max_length=10, blank=True, verbose_name='Выбранная валюта', default='USD')
    auto_renew = models.BooleanField(default=True, verbose_name="Автосписание")
    
    ip = models.GenericIPAddressField(null=True, blank=True)
    
    groups = models.ManyToManyField(
        Group,
        related_name='custom_user_set',
        blank=True,
        help_text='Группы, к которым принадлежит пользователь',
        verbose_name='группы'
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name='custom_user_permissions_set',
        blank=True,
        help_text='Разрешения, назначенные пользователю',
        verbose_name='разрешения'
    )

    _2fa = models.BooleanField(default=True, verbose_name="Двух факторная аутентификация")

    objects = UserManager()

    # Referral + bonus counters
    referral_uid = models.CharField(
        max_length=16,
        unique=True,
        blank=True,
        null=True,
        default=generate_referral_uid,
        verbose_name='Реферальный UID'
    )
    # Кто пригласил этого пользователя (реферер). Ставится ОДИН РАЗ при
    # регистрации по реф-ссылке. Приглашающий получает % от купленных кредитов
    # приглашённого при каждом пополнении (пожизненно). SET_NULL: удаление
    # реферера не удаляет приглашённых.
    referred_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="referrals",
        verbose_name="Кто пригласил",
    )
    bonus_texts = models.PositiveIntegerField(default=0, verbose_name='Бонусные тексты')
    bonus_images = models.PositiveIntegerField(default=0, verbose_name='Бонусные изображения')
    bonus_songs = models.PositiveIntegerField(default=0, verbose_name='Бонусные песни')
    bonus_music = models.PositiveIntegerField(default=0, verbose_name='Бонусная музыка')

    # Pay-as-you-go token balance (новая токен-система)
    token_balance = models.BigIntegerField(default=0, verbose_name='Баланс токенов')

    # Tier-флаг (ТЗ Этап 3): становится True после первой успешной оплаты.
    # user_tier: guest (аноним) / free (не платил) / paid (is_paid=True).
    is_paid = models.BooleanField(default=False, verbose_name='Платный пользователь')
    first_paid_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата первой оплаты')

    # Безлимитный тестовый аккаунт: все модели (как paid) + снят дневной лимит
    # запросов. НЕ даёт доступа к админке (в отличие от is_staff). Денежный код
    # не обходит — балансом всё равно списывается (для теста кладём большой баланс).
    is_unlimited = models.BooleanField(default=False, verbose_name='Безлимитный (тест)')

    # Аватар из соц-входа (Telegram photo_url / Google picture). Храним URL
    # провайдера как есть (публичный CDN) — не перекачиваем к себе.
    avatar_url = models.URLField(max_length=512, blank=True, default="", verbose_name='Аватар (URL)')

    # Память пользователя (как у ChatGPT/Anthropic): глобальный флаг. По умолчанию
    # включена для всех авторизованных. При False — факты не инъектируются в промпт
    # и не извлекаются из диалогов (см. core/users/memory.py).
    memory_enabled = models.BooleanField(default=True, verbose_name="Память включена")

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email

    # Django admin expectations for AbstractBaseUser implementations
    def get_full_name(self) -> str:
        parts = [self.first_name or "", self.patronymic or "", self.last_name or ""]
        full = " ".join(p for p in parts if p).strip()
        return full or self.email

    def get_short_name(self) -> str:
        return (self.first_name or self.last_name or self.email or "user").strip()

    def _generate_unique_uid(self, length: int = 8) -> str:
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = ''.join(random.choices(alphabet, k=length))
            if not User.objects.filter(referral_uid=code).exists():
                return code

    def save(self, *args, **kwargs):
        # If username is empty, fallback to using email as username
        if (not (self.username or "").strip()) and self.email:
            self.username = self.email

        # Ensure referral_uid is always present and unique
        def uid_exists(uid: str) -> bool:
            qs = User.objects.filter(referral_uid=uid)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            return qs.exists()

        if not self.referral_uid or uid_exists(self.referral_uid):
            self.referral_uid = self._generate_unique_uid()

        attempts = 0
        while True:
            try:
                return super().save(*args, **kwargs)
            except IntegrityError as e:
                # handle rare race condition collisions
                if "referral_uid" in str(e) and attempts < 5:
                    self.referral_uid = self._generate_unique_uid()
                    attempts += 1
                    continue
                raise

    class Meta:
        indexes = [
            models.Index(fields=["referral_uid"]),
        ]
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

        
class UserQuestions(models.Model):
    email = models.EmailField(verbose_name="Email")
    tel = models.CharField(verbose_name="tel", blank=True, null=True, max_length=50)
    name = models.CharField(verbose_name="name", blank=True, null=True, max_length=50)
    question = models.TextField(verbose_name="User question")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created at")
    
    
    def __str__(self):
        return f'{self.email} - {self.created_at}'
    
    class Meta:
        verbose_name = "Вопрос пользователя"
        verbose_name_plural = "Вопросы пользователей"
        ordering = ['-created_at']
        
        
class Notification(models.Model):
    """System notification with support for multiple recipients.

    Note: legacy fields (recipient, is_read, read_at) are removed in favor of per-recipient delivery records.
    """
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='NotificationDelivery',
        related_name='notifications_received',
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"

    def __str__(self):
        return f"Notification({self.title})"

    def add_recipients(self, users: list["User"]):
        now = timezone.now()
        for u in users:
            NotificationDelivery.objects.get_or_create(
                notification=self,
                recipient=u,
                defaults={"is_read": False, "read_at": None, "assigned_at": now},
            )

    def mark_read_for(self, user: "User"):
        try:
            nd = NotificationDelivery.objects.get(notification=self, recipient=user)
            nd.mark_read()
        except NotificationDelivery.DoesNotExist:
            pass


class NotificationDelivery(models.Model):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='deliveries')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_deliveries')
    is_read = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-assigned_at"]
        unique_together = ("notification", "recipient")
        verbose_name = "Доставка уведомления"
        verbose_name_plural = "Доставки уведомлений"

    def __str__(self):
        return f"Delivery(n={self.notification_id}, u={self.recipient_id}, read={self.is_read})"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


class UserFeedback(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedbacks")
    name = models.CharField(max_length=100, blank=True, verbose_name="Имя")
    email = models.EmailField(blank=True, verbose_name="Email")
    rating = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Оценка")
    message = models.TextField(verbose_name="Отзыв")
    source = models.CharField(max_length=100, blank=True, verbose_name="Источник")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")

    class Meta:
        verbose_name = "Отзыв пользователя"
        verbose_name_plural = "Отзывы пользователей"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        who = self.name or (self.user.email if self.user else self.email) or "anonymous"
        return f"Feedback({who}, {self.rating or '-'}★)"


class WebPushSubscription(models.Model):
    """Web Push подписка пользователя (Push API / VAPID).

    Хранит endpoint браузера и ключи шифрования (p256dh/auth), полученные из
    PushSubscription на фронте. По этим данным сервер шлёт web-push (см.
    users/webpush.py) — например, ежедневный пуш «зачислен бонус». Один
    пользователь может иметь несколько подписок (разные браузеры/устройства);
    endpoint уникален. Протухшие подписки (404/410 от push-сервиса) удаляются.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subs",
        verbose_name="Пользователь",
    )
    endpoint = models.TextField(unique=True, verbose_name="Endpoint")
    p256dh = models.CharField(max_length=255, verbose_name="Ключ p256dh")
    auth = models.CharField(max_length=255, verbose_name="Ключ auth")
    user_agent = models.CharField(max_length=300, blank=True, verbose_name="User-Agent")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создана")
    last_ok_at = models.DateTimeField(null=True, verbose_name="Последняя успешная доставка")

    class Meta:
        verbose_name = "Web Push подписка"
        verbose_name_plural = "Web Push подписки"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} - {self.endpoint[:40]}"


class UserMemory(models.Model):
    """Долгоиграющий факт о пользователе (память как у ChatGPT/Anthropic).

    Факты копятся автоматически (source=auto, извлекаются дешёвой LLM из диалогов)
    либо вручную по команде «запомни …» (source=manual). При сборке системного
    промпта верхние факты по importance/updated_at инъектируются компактным блоком.
    Дедуп и кап общего числа — в core/users/memory.py.
    """

    CATEGORY_CHOICES = (
        ("identity", "Личность"),       # имя, возраст, локация, язык
        ("work", "Работа"),             # профессия, компания, роль
        ("preference", "Предпочтения"), # стиль ответов, интересы, привычки
        ("project", "Проект"),          # над чем работает, что делает
        ("other", "Другое"),
    )
    SOURCE_CHOICES = (
        ("auto", "Автоматически"),
        ("manual", "Вручную"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memories",
        verbose_name="Пользователь",
    )
    content = models.TextField(verbose_name="Факт")
    category = models.CharField(
        max_length=20,
        choices=CATEGORY_CHOICES,
        default="other",
        verbose_name="Категория",
    )
    source = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default="auto",
        verbose_name="Источник",
    )
    importance = models.SmallIntegerField(default=1, verbose_name="Важность")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        verbose_name = "Память пользователя"
        verbose_name_plural = "Память пользователей"
        ordering = ["-importance", "-updated_at"]
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        snippet = (self.content or "")[:50]
        return f"Memory(user={self.user_id}, {self.category}: {snippet})"
