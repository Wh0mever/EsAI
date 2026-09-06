from django.conf import settings
from django.db import models


class TelegramChat(models.Model):
    """Связь пользователя EsAI с его перепиской в боте.

    Аккаунт у бота и сайта общий (SocialAccount provider=telegram), а вот куда
    писать человеку — знает только бот. Поэтому chat_id и настройки
    уведомлений живут здесь, а не в User: у одного пользователя может не быть
    Telegram вовсе.
    """

    SOURCE_BOT = "bot"
    SOURCE_WEBAPP = "webapp"
    SOURCE_LINK = "link"
    SOURCE_CHOICES = (
        (SOURCE_BOT, "Бот"),
        (SOURCE_WEBAPP, "Mini App"),
        (SOURCE_LINK, "Привязка с сайта"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="telegram_chat", verbose_name="Пользователь")
    telegram_id = models.BigIntegerField(unique=True, db_index=True, verbose_name="Telegram ID")
    chat_id = models.BigIntegerField(verbose_name="Chat ID")
    username = models.CharField(max_length=64, blank=True, default="", verbose_name="@username")
    lang = models.CharField(max_length=5, default="ru", verbose_name="Язык")

    notify_bonus = models.BooleanField(default=True, verbose_name="Ежедневный бонус")
    notify_ready = models.BooleanField(default=True, verbose_name="Готовность видео и мультфильмов")
    notify_topup = models.BooleanField(default=True, verbose_name="Пополнение баланса")
    notify_referral = models.BooleanField(default=True, verbose_name="Реферальные начисления")
    notify_marketing = models.BooleanField(default=False, verbose_name="Новости и акции")

    # Человек нажал «стоп» — писать ему больше нельзя, пока не вернётся сам.
    is_blocked = models.BooleanField(default=False, db_index=True, verbose_name="Бот заблокирован")
    blocked_at = models.DateTimeField(null=True, blank=True, verbose_name="Когда заблокирован")
    consent_terms_at = models.DateTimeField(null=True, blank=True, verbose_name="Согласие с условиями")

    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_BOT,
                              verbose_name="Откуда пришёл")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Чат в Telegram"
        verbose_name_plural = "Чаты в Telegram"
        ordering = ("-last_seen_at",)

    def __str__(self) -> str:
        who = self.username or self.telegram_id
        return f"@{who}" if self.username else str(who)

    def wants(self, kind: str) -> bool:
        """Ждёт ли человек уведомление такого рода."""
        if self.is_blocked:
            return False
        return bool(getattr(self, f"notify_{kind}", True))
